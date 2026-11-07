"""
ds18b20.py - DS18B20 접촉 온도 프로브(방수형 3선) 여러 개를 Linux 1-Wire 로 읽는다 (w1-gpio + w1_therm)

결선: 빨강 VDD -> 3.3 V, 검정 GND, 노랑 DQ -> BCM 4 (40핀 7번).
      DQ 와 3.3 V 사이에 4.7 kΩ 하나 (프로브마다가 아니라 버스 전체에 하나. 프로브 키트의 어댑터 기판에는
      이미 붙어 있으니 따로 달지 않는다). 5 V 로 풀업하면 Pi 가 망가진다.
      기생 전원(2선) 방식은 쓰지 않는다 (85 ℃ 오류가 잦다).
켜기: /boot/firmware/config.txt 에 dtoverlay=w1-gpio (Pi 5 는 w1-gpio-pi5) 후 재부팅
      -> /sys/bus/w1/devices/28-xxxxxxxxxxxx/w1_slave

w1_slave (읽을 때마다 커널이 변환을 시켜 12 비트에서 약 0.75 초 걸린다)
    72 01 4b 46 7f ff 0e 10 57 : crc=57 YES
    72 01 4b 46 7f ff 0e 10 57 t=23125              -> 23.125 ℃
실패로 보는 것
  - crc 가 NO, 또는 9 바이트의 CRC-8(Maxim) 이 맞지 않음
  - 9 바이트가 모두 0 (DQ 가 GND 에 붙으면 CRC 도 0 이라 통과해 버린다)
  - 85.000 ℃: 전원이 켜진 직후의 초기값(변환이 안 된 것). 직전 값이 75 ℃ 이상일 때만 진짜로 받아들인다
    (진짜로 85 ℃ 까지 오르려면 그 전에 60 ℃ 위험 단계를 지난다)
  - 측정 범위(-55~125 ℃) 밖
  - 빈 값: 요즘 커널은 응답이 없거나 CRC 가 계속 틀리면 w1_slave 를 비워서 준다

느린 읽기가 1 초 판정 루프를 붙잡지 않도록 실제 장비에서는 ProbeGroup(threaded=True) 가
별도 스레드에서 프로브를 차례로 읽고, 판정 루프는 최근 값만 가져간다. max_age_s(10 초) 넘게
새 값이 없는 프로브는 읽기 실패(None)로 본다. 스레드 쪽은 프로브마다 연속 두 값 중 낮은 값을 내놓는다:
한 값이 2~3 초 동안 여러 판정에 쓰이므로, 한 번 튄 값이 판정의 확인 시간(2 초)을 통과하지 않게 하려는 것이다.
"""
from __future__ import annotations

import os
import re
import threading
import time

W1_DIR = "/sys/bus/w1/devices"
ID_RE = re.compile(r"^28-[0-9a-f]{12}$")
POWER_ON_C = 85.0
POWER_ON_TRUST_FROM_C = 75.0


def crc8_maxim(data: bytes) -> int:
    """1-Wire CRC-8 (다항식 x^8+x^5+x^4+1, 반사, 초기값 0). 확인값 crc8_maxim(b"123456789") == 0xA1"""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def parse_w1_slave(text: str) -> float:
    """w1_slave 내용 -> ℃. 이상하면 IOError"""
    lines = text.strip().splitlines()
    if not lines:
        raise IOError("빈 값 (응답이 없거나 CRC 가 계속 틀려 커널이 값을 버림)")
    if len(lines) < 2:
        raise IOError(f"w1_slave 내용이 짧음: {text.strip()!r}")
    try:
        raw = bytes(int(x, 16) for x in lines[0].split(":")[0].split())
    except ValueError:
        raise IOError(f"w1_slave 첫 줄을 읽을 수 없음: {lines[0]!r}") from None
    if len(raw) != 9:
        raise IOError(f"스크래치패드 길이가 {len(raw)} 바이트")
    if not lines[0].rstrip().endswith("YES") or crc8_maxim(raw[:8]) != raw[8]:
        raise IOError(f"CRC 불일치 ({lines[0].strip()})")
    if not any(raw):
        raise IOError("스크래치패드가 모두 0 (DQ 가 GND 에 붙었는지 확인)")
    m = re.search(r"t=(-?\d+)", lines[1])
    if not m:
        raise IOError(f"t= 가 없음: {lines[1]!r}")
    c = int(m.group(1)) / 1000.0
    if not -55.0 <= c <= 125.0:
        raise IOError(f"측정 범위 밖: {c} ℃")
    return c


def normalize_ids(ids) -> list[str]:
    """설정의 ds18b20_ids -> 소문자, 공백 없는 목록 (문자열 하나만 적어도 목록으로)"""
    if isinstance(ids, str):
        ids = [ids]
    return [str(i).strip().lower() for i in (ids or [])]


class W1Sysfs:
    """실제 1-Wire 버스 (/sys/bus/w1/devices)"""

    def __init__(self, base: str = W1_DIR):
        self.base = base

    def ids(self) -> list[str]:
        try:
            names = os.listdir(self.base)
        except FileNotFoundError:
            raise IOError(f"{self.base} 가 없음: 1-Wire 가 꺼져 있음 (dtoverlay=w1-gpio 후 재부팅)") from None
        return sorted(n for n in names if ID_RE.match(n))

    def read_slave(self, rom_id: str) -> str:
        with open(os.path.join(self.base, rom_id, "w1_slave"), encoding="ascii", errors="replace") as f:
            return f.read()


class ProbeGroup:
    """DS18B20 여러 개. read() -> 프로브 순서대로 ℃ 목록 (못 읽은 프로브는 None, 모두 못 읽으면 IOError)

    ids 를 주면 그 순서가 프로브 1, 2, 3 (위치가 고정됨). 비우면 begin() 에서 찾은 ID 를 정렬한 순서.
    """

    def __init__(self, w1, ids=(), count: int = 3, threaded: bool = False, max_age_s: float = 10.0,
                 period_s: float = 2.0, clock=time.monotonic, log=lambda m: None):
        ids = normalize_ids(ids)
        bad = [i for i in ids if not ID_RE.match(i)]
        if bad:
            raise ValueError(f"DS18B20 ID 형식이 틀림: {bad} (예: 28-0316a2799aff)")
        self.w1 = w1
        self.fixed_ids = ids
        self.count = len(ids) if ids else int(count)
        if self.count < 1:
            raise ValueError("DS18B20 개수는 1 이상")
        self.ids: list[str | None] = list(ids) if ids else [None] * self.count
        self.threaded = threaded
        self.max_age_s = max_age_s
        self.period_s = period_s
        self.clock = clock
        self.log = log
        self.last_good: dict[str, float] = {}               # 85 ℃ 판단용 직전 값
        self._prev: dict[str, float] = {}                   # 스레드: 바로 앞 값 (연속 두 값 중 낮은 값을 내놓기)
        self.raw: dict[str, float] = {}                     # 마지막으로 읽은 날값 (끊길 때 판정이 단계를 붙잡는 데 씀)
        self.latest: dict[str, tuple[float, float]] = {}    # id -> (시각, ℃). 스레드가 채운다
        self.errors: dict[str, str] = {}                    # id -> 마지막 오류
        self.started_at: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    def begin(self) -> str:
        found = self.w1.ids()
        notes = []
        if self.fixed_ids:
            missing = [i for i in self.fixed_ids if i not in found]
            if len(missing) == len(self.fixed_ids):
                raise IOError(f"설정한 DS18B20 이 하나도 안 보임 (찾은 것: {', '.join(found) or '없음'})")
            if missing:
                notes.append(f"안 보임: {', '.join(missing)}")
            ids = list(self.fixed_ids)
        else:
            if not found:
                raise IOError("1-Wire 에 DS18B20 이 없음 (배선, DQ-3.3 V 4.7 kΩ, dtoverlay=w1-gpio 확인)")
            # 한 번 정한 번호는 바꾸지 않는다: 프로브가 끊겼다 다시 찾아도 프로브 2 는 계속 같은 ID.
            # (바뀌면 판정이 기억하는 '끊기기 전 값'이 다른 프로브 것이 된다) 빈 자리만 새로 찾은 것으로 채운다
            ids = list(self.ids)
            spare = [f for f in found if f not in ids]
            for k in range(self.count):
                if ids[k] is None and spare:
                    ids[k] = spare.pop(0)
            if None in ids:
                notes.append(f"{ids.count(None)} 개 모자람")
            if spare:
                notes.append(f"더 찾았지만 안 씀: {', '.join(spare)}")
            gone = [i for i in ids if i is not None and i not in found]
            if gone:
                notes.append(f"안 보임: {', '.join(gone)}")
        self.ids = ids
        if self.threaded:
            if self._thread is None or not self._thread.is_alive():
                self._prev.clear()                           # 오래된 값과 짝짓지 않게
                self.started_at = self.clock()
                self._thread = threading.Thread(target=self._loop, name="ds18b20", daemon=True)
                self._thread.start()
            elif not any(v is not None for v in self._fresh()):
                # 다시 연결하는 중인데 읽히는 프로브가 없음: 연결됨/끊김이 번갈아 기록되지 않게 실패로 둔다
                raise IOError("DS18B20 을 하나도 못 읽음" + (f": {self.problem(self._fresh())}"))
        names = ", ".join(f"{n} {rid or '없음'}" for n, rid in zip(self.names(), ids))
        return f"DS18B20 {sum(i is not None for i in ids)}/{self.count} ({names})" + (
            f" [{'; '.join(notes)}]" if notes else "")

    def names(self) -> list[str]:
        return [f"프로브{i + 1}" for i in range(self.count)]

    def _read_one(self, rid: str) -> float:
        try:
            text = self.w1.read_slave(rid)
        except FileNotFoundError:
            raise IOError("안 보임 (1-Wire 에서 사라짐)") from None
        c = parse_w1_slave(text)
        if c == POWER_ON_C and self.last_good.get(rid, -1e9) < POWER_ON_TRUST_FROM_C:
            raise IOError("85 ℃ 초기값 (변환이 안 됨: 전원, 배선 확인)")
        self.last_good[rid] = c
        self.raw[rid] = c
        return c

    def _loop(self) -> None:
        """별도 스레드: 프로브를 차례로 읽어 latest 에 넣는다. 어떤 오류에도 멈추지 않는다"""
        while not self._stop.is_set():
            t0 = time.monotonic()
            for rid in list(self.ids):
                if self._stop.is_set():
                    return
                if rid is None:
                    continue
                try:
                    v = self._read_one(rid)
                except Exception as e:                       # noqa: BLE001  스레드가 죽으면 프로브 감시가 멈춘다
                    self.errors[rid] = str(e)
                    self._prev.pop(rid, None)                # 실패 뒤의 첫 값은 오래된 값이 아니라 다음 값과 짝짓는다
                    continue
                prev, self._prev[rid] = self._prev.get(rid), v
                self.errors.pop(rid, None)
                if prev is not None:                         # 첫 값은 다음 값과 함께 쓴다
                    self.latest[rid] = (self.clock(), min(prev, v))
            self._stop.wait(max(0.05, self.period_s - (time.monotonic() - t0)))

    def last_raw(self) -> list[float | None]:
        """프로브마다 마지막으로 읽은 날값 (오래됐어도). 판정은 이것을 '끊기기 직전 값' 으로만 쓴다:
        두 값 중 낮은 값만 내놓다 보니, 뜨거운 마지막 한 값을 남기고 끊기면 그 값이 판정에 안 들어가기 때문"""
        return [self.raw.get(rid) if rid else None for rid in self.ids]

    def _fresh(self) -> list[float | None]:
        """스레드가 읽은 값 중 max_age_s 안의 것 (프로브 순서)"""
        now = self.clock()
        out = []
        for rid in self.ids:
            got = self.latest.get(rid) if rid else None
            out.append(got[1] if got and now - got[0] <= self.max_age_s else None)
        return out

    def read(self) -> list[float | None]:
        if self.threaded:
            out = self._fresh()
            if all(v is None for v in out) and self.started_at is not None and \
                    self.clock() - self.started_at < self.max_age_s:
                return out                                   # 막 시작해서 첫 값을 기다리는 중 (실패로 세지 않음)
        else:
            out = []
            for rid in self.ids:
                if rid is None:
                    out.append(None)
                    continue
                try:
                    out.append(self._read_one(rid))
                    self.errors.pop(rid, None)
                except (OSError, ValueError) as e:
                    self.errors[rid] = str(e)
                    out.append(None)
        if all(v is None for v in out):
            raise IOError("DS18B20 을 하나도 못 읽음" + (f": {self.problem(out)}" if self.problem(out) else ""))
        return out

    def problem(self, values: list) -> str:
        """못 읽은 프로브와 이유 (DeviceHealth.message 용)"""
        out = []
        for name, rid, v in zip(self.names(), self.ids, values):
            if v is None:
                why = "안 보임" if rid is None else self.errors.get(rid, f"{self.max_age_s:.0f} 초 넘게 새 값 없음")
                out.append(f"{name} {why}")
        return "; ".join(out)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
