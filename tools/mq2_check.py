"""
mq2_check.py - MQ-2 연기 센서 하나만 ADS1115 로 읽어 보는 도구 (다른 센서 없이 먼저 살릴 때)

    python3 tools/mq2_check.py                    # 1 초마다 값, Ctrl+C 로 끝
    python3 tools/mq2_check.py --minutes 30       # 30 분 돌고 끝 (예열 곡선 보기)
    python3 tools/mq2_check.py --config config.battery.yaml   # 주소, 채널, 분압을 설정에서
    python3 tools/mq2_check.py --fake --minutes 5 --speed 0   # 하드웨어 없이 이 스크립트 시험
      --addr 0x48  --channel 0  --divider 1.5      설정 대신 직접
      --out DIR    CSV 를 둘 곳 (기본 ~/fire_logs/mq2). 끝나도 파일이 남는다

화면 한 줄: 경과 시간, A0 핀 전압, MQ-2 AO 전압(= A0 x 분압), 기준선 대비, 최근 1 분 기울기, 상태
  상태  예열 중    켠 지 3 분 안 (값이 높게 시작해 내려오는 것이 정상)
        내려가는 중 1 분에 10 mV 넘게 내려감 (아직 안정 전)
        안정       1 분 변화 ±10 mV 안
        올라감     기준보다 0.3 V 넘게 높음 (가스, 연기 시험 때 이것이 나와야 함)
처음에 A0~A3 네 채널을 한 번씩 읽어 보여 준다: AO 를 어느 채널에 꽂았는지, 핀이 떠 있는지 알 수 있다.

fire-detect 가 돌고 있으면 같은 I2C 를 쓰지만 ADS1115 는 한 번 변환마다 주고받아 대개 같이 돌아도 된다.
값이 이상하면 fire-detect 를 멈추고 다시 본다.
"""
from __future__ import annotations

import argparse
import collections
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fire_detect.config import load  # noqa: E402
from fire_detect.drivers.ads1115 import ADS1115  # noqa: E402

WARMUP_S = 180.0
STABLE_MV_PER_MIN = 10.0
SMOKE_DV = 0.30


def diagnose(a0: float, ao: float) -> str:
    """한 번 읽은 값으로 결선 문제를 짐작"""
    if a0 >= 3.25:
        return "A0 가 3.3 V 근처: 분압 저항이 빠졌거나 AO 가 바로 A0 에 꽂힘 (ADS1115 입력 한계), 결선 확인"
    if ao < 0.02:
        return "거의 0 V: MQ-2 전원(5 V, GND) 이나 AO 선, 10 kΩ 확인. 모듈 전원 LED 가 켜졌는지"
    return ""


def slope_mv_per_min(pts) -> float:
    """최근 점들의 최소제곱 기울기 (mV/분). 한 점 튀는 잡음에 덜 흔들림"""
    n = len(pts)
    mx = sum(t for t, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((t - mx) ** 2 for t, _ in pts)
    return sum((t - mx) * (v - my) for t, v in pts) / sxx * 1000 * 60 if sxx > 0 else 0.0


def status(elapsed: float, ao: float, base: float | None, slope_mv: float | None) -> str:
    if base is not None and ao - base > SMOKE_DV:
        return "올라감"
    if elapsed < WARMUP_S:
        return "예열 중"
    if slope_mv is None:
        return "-"
    if slope_mv < -STABLE_MV_PER_MIN:
        return "내려가는 중"
    if slope_mv > STABLE_MV_PER_MIN:
        return "오르는 중"
    return "안정"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MQ-2 + ADS1115 단독 확인")
    ap.add_argument("--config", help="설정 YAML (sensors.ads1115_address, smoke_channel, smoke_divider)")
    ap.add_argument("--addr", type=lambda s: int(s, 0))
    ap.add_argument("--channel", type=int)
    ap.add_argument("--divider", type=float)
    ap.add_argument("--minutes", type=float, help="이만큼 돌고 끝 (없으면 Ctrl+C 까지)")
    ap.add_argument("--out", default="~/fire_logs/mq2")
    ap.add_argument("--fake", action="store_true", help="가짜 ADS1115 (시뮬레이터)")
    ap.add_argument("--speed", type=float, default=1.0, help="--fake 일 때 배속 (0 = 기다리지 않음)")
    a = ap.parse_args(argv)

    sc = load(a.config).sensors
    addr = a.addr if a.addr is not None else sc.ads1115_address
    ch = a.channel if a.channel is not None else sc.smoke_channel
    div = a.divider if a.divider is not None else sc.smoke_divider

    if a.fake:
        from fire_detect.simulate import Scenario, make_bus
        scen = Scenario("normal")
        bus = make_bus(scen, ads=addr, divider=div)
        adc = ADS1115(bus, addr, sleep=lambda s: None)
        wall0 = time.time()
        now = lambda: wall0 + scen.t                                  # noqa: E731
        def wait(s):
            scen.t += s
            if a.speed > 0:
                time.sleep(s / a.speed)
    else:
        from fire_detect.drivers.i2c_bus import SMBus2Bus
        try:
            bus = SMBus2Bus(1)
        except Exception as e:
            print(f"I2C 버스 1 을 열 수 없음: {e}\n  dtparam=i2c_arm=on, i2c 그룹 권한, sudo i2cdetect -y 1 을 확인")
            return 2
        adc = ADS1115(bus, addr)
        now, wait = time.time, time.sleep

    print(f"ADS1115 0x{addr:02X}, MQ-2 채널 A{ch}, 분압 {div}")
    try:
        chans = [adc.read_volts(c) for c in range(4)]
    except OSError as e:
        print(f"ADS1115 응답 없음: {e}\n  sudo i2cdetect -y 1 에 {addr:02x} 가 보이는지, ADS1115 VDD 3.3 V, GND, SDA 핀 3, SCL 핀 5, ADDR-GND 확인")
        return 2
    print("채널 한 번씩: " + ", ".join(f"A{c} {v:.3f} V" for c, v in enumerate(chans))
          + "  (AO 를 꽂지 않은 채널은 아무 값이나 나올 수 있음)")

    out = Path(os.path.expanduser(a.out))
    out.mkdir(parents=True, exist_ok=True)
    t_start = now()
    stem = f"mq2_{datetime.fromtimestamp(t_start, timezone.utc):%Y%m%d_%H%M%S}"
    path, k = out / f"{stem}.csv", 1
    while path.exists():
        path, k = out / f"{stem}_{k}.csv", k + 1
    fh = open(path, "w", newline="", encoding="utf-8")
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["time_unix", "time_iso", "elapsed_s", "a0_v", "ao_v", "baseline_v", "slope_mv_per_min", "status"])
    print(f"기록: {path}")
    print("  경과     A0(V)   AO(V)   기준대비    1분변화     상태")

    hist = collections.deque()          # (elapsed, ao) 최근 60 초
    base = None
    first_diag = ""
    n_err = 0
    end = a.minutes * 60 if a.minutes else None
    try:
        while end is None or now() - t_start < end:
            t = now()
            el = t - t_start
            try:
                a0 = adc.read_volts(ch)
            except OSError as e:
                n_err += 1
                print(f"{el:7.0f}s  읽기 실패 ({n_err}): {e}")
                wait(1.0)
                continue
            ao = a0 * div
            hist.append((el, ao))
            while hist and el - hist[0][0] > 60:
                hist.popleft()
            slope = slope_mv_per_min(hist) if el - hist[0][0] >= 30 else None
            if el >= WARMUP_S and base is None:
                base = ao
            elif base is not None and ao - base <= SMOKE_DV:
                base += (ao - base) * (1.0 / 600.0)              # 천천히 따라가는 기준선 (fire-detect 와 같은 600 초)
            st = status(el, ao, base, slope)
            d = diagnose(a0, ao)
            if d and d != first_diag:
                print(f"  ! {d}")
                first_diag = d
            rel = f"{ao - base:+.3f}" if base is not None else "   -  "
            sl = f"{slope:+7.1f}" if slope is not None else "     - "
            print(f"{el:7.0f}s  {a0:6.3f}  {ao:6.3f}  {rel:>8}  {sl} mV/분  {st}", flush=True)
            w.writerow([f"{t:.3f}", datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds"),
                        f"{el:.1f}", f"{a0:.4f}", f"{ao:.4f}", f"{base:.4f}" if base is not None else "",
                        f"{slope:.1f}" if slope is not None else "", st])
            fh.flush()
            wait(max(0.0, 1.0 - (now() - t)))
    except KeyboardInterrupt:
        pass
    finally:
        fh.close()
    print(f"끝. 기록 {path} (읽기 실패 {n_err} 회)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
