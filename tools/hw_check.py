"""
hw_check.py - 화재 감지기(ess_01) 보드를 처음 꾸릴 때 부품을 하나씩 확인한다.

    python3 tools/hw_check.py i2c                # I2C 센서(AMG8833, SHT31, ADS1115, MLX90614)가 응답하는지
    python3 tools/hw_check.py w1                 # 1-Wire 접촉 프로브(DS18B20)가 몇 개 보이는지
    python3 tools/hw_check.py w1 --n 20          #   + 20 바퀴(약 50 초) 프로브 온도를 보여 줌 (하나씩 손으로 쥐어 위치 구별)
    python3 tools/hw_check.py sensors --n 10     # 센서를 모두 10 번 읽고 값이 말이 되는지
    python3 tools/hw_check.py outputs            # LED, 부저, DC 릴레이, SSR 을 하나씩 켰다 끔 (사람이 보고 답함)
    python3 tools/hw_check.py button             # 래치 해제 버튼 (30 초 기다림)
    python3 tools/hw_check.py all                # i2c + w1 + sensors (출력은 따로 돌릴 것)
      --config FILE   주소와 핀을 설정 파일에서 (기본: /etc/fire-detect/config.yaml 이 있으면 그것)
      --fake          하드웨어 없이 이 스크립트를 시험 (가짜 센서, 가짜 출력)

주의
  - fire-detect 서비스가 돌고 있으면 같은 GPIO 를 잡고 있다. 먼저 sudo systemctl stop fire-detect.
    서비스가 멈춰 있는 동안은 출력이 풀려 충전이 끊긴 상태다 (안전 쪽).
  - outputs 는 SSR 을 2 초 켠다. SSR 의 AC 쪽(파워뱅크 충전 라인)을 반드시 빼 두고 돌릴 것.
  - 끝나면 오류가 나도 모든 출력을 끈다.
종료 코드: 0 모두 통과, 1 실패가 있음, 2 시작하지 못함
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fire_detect.config import Config, load  # noqa: E402
from fire_detect.drivers.ads1115 import ADS1115  # noqa: E402
from fire_detect.drivers.amg8833 import AMG8833  # noqa: E402
from fire_detect.drivers.ds18b20 import POWER_ON_C, ProbeGroup, normalize_ids, parse_w1_slave  # noqa: E402
from fire_detect.drivers.mlx90614 import MLX90614  # noqa: E402
from fire_detect.drivers.sht31 import SHT31  # noqa: E402

DEFAULT_CONFIG = "/etc/fire-detect/config.yaml"
PASS, FAIL, WARN, SKIP = "통과", "실패", "주의", "안 씀"
AC_CONFIRM = "AC 분리"

# 출력 시험 순서: 위험이 적은 것부터. (키, 이름, 켰을 때 질문, 끈 뒤 질문)
# 릴레이와 SSR 은 끈 뒤에도 묻는다: 3.3 V 신호로는 붙기만 하고 확실히 떨어지지 않는 모듈이 있다
OUTPUTS = [
    ("green", "녹색 LED", "켜졌습니까", None),
    ("yellow", "황색 LED", "켜졌습니까", None),
    ("red", "적색 LED", "켜졌습니까", None),
    ("buzzer", "부저", "소리가 났습니까", None),
    ("dc", "DC 차단 릴레이", "딸깍 붙고 릴레이 표시 LED 가 켜졌습니까", "다시 딸깍 떨어지고 표시 LED 가 꺼졌습니까"),
    ("ssr", "AC 충전 SSR", "SSR 의 입력 표시 LED 가 켜졌습니까", "SSR 의 입력 표시 LED 가 꺼졌습니까"),
]


def report(rows: list[tuple[str, str, str]]) -> bool:
    w = max(len(r[0]) for r in rows) if rows else 0
    for name, result, detail in rows:
        print(f"  [{result}] {name.ljust(w)}  {detail}")
    return all(r[1] != FAIL for r in rows)


# ------------------------------------------------------------------ 버스, 출력 열기
def open_bus(cfg: Config, fake: bool):
    sc = cfg.sensors
    if fake:
        from fire_detect.simulate import Scenario, make_bus
        return make_bus(Scenario("normal"), sc.amg8833_address, sc.sht31_address, sc.ads1115_address,
                        sc.smoke_divider, sc.mlx90614_address)
    from fire_detect.drivers.i2c_bus import SMBus2Bus
    return SMBus2Bus(cfg.i2c_bus)


def open_w1(fake: bool):
    if fake:
        from fire_detect.simulate import FakeW1, Scenario
        return FakeW1(Scenario("normal"))
    from fire_detect.drivers.ds18b20 import W1Sysfs
    return W1Sysfs()


def probes_used(cfg: Config) -> bool:
    return bool(cfg.sensors.ds18b20_ids) or cfg.sensors.ds18b20_count > 0


class FakeDev:
    """--fake 용 출력 장치. 켜고 끈 기록만 남긴다"""

    def __init__(self, name: str, log: list):
        self.name, self.log, self.value = name, log, False

    def on(self):
        self.value = True
        self.log.append((self.name, "on"))

    def off(self):
        self.value = False
        self.log.append((self.name, "off"))

    def close(self):
        self.value = False


def open_outputs(cfg: Config, fake: bool, log: list) -> dict:
    p = cfg.pins
    pins = dict(green=p.led_green, yellow=p.led_yellow, red=p.led_red, buzzer=p.buzzer, dc=p.dc_relay, ssr=p.ssr)
    if fake:
        return {k: (FakeDev(k, log) if pin >= 0 else None) for k, pin in pins.items()}
    from fire_detect.outputs import GpioOutputs          # 서비스와 같은 방식(active_low 포함)으로 연다
    return GpioOutputs(p).dev


def service_running() -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "fire-detect"], check=False).returncode == 0
    except OSError:
        return False


# ------------------------------------------------------------------ 시험
def check_i2c(cfg: Config, bus) -> bool:
    sc = cfg.sensors
    print(f"I2C 버스 {cfg.i2c_bus} 응답 확인")
    rows = []
    devs = [("AMG8833 열화상", AMG8833(bus, sc.amg8833_address)),
            ("SHT31 온습도", SHT31(bus, sc.sht31_address)),
            ("ADS1115 (MQ-2)", ADS1115(bus, sc.ads1115_address))]
    if sc.mlx90614_address >= 0:
        devs.append(("MLX90614 적외선", MLX90614(bus, sc.mlx90614_address)))
    else:
        rows.append(("MLX90614 적외선", SKIP, "설정에서 mlx90614_address: -1"))
    for name, dev in devs:
        try:
            dev.begin()
            rows.append((name, PASS, f"0x{dev.addr:02X} 응답"))
        except Exception as e:                              # noqa: BLE001  배선 문제는 무엇이든 실패로
            rows.append((name, FAIL, f"0x{dev.addr:02X} 응답 없음 ({e}). 전원(3.3 V), SDA 3번, SCL 5번, GND 확인"))
    ok = report(rows)
    print("  OLED(0x3C) 는 선택 부품이라 여기서 보지 않음. sudo i2cdetect -y 1 로 확인")
    return ok


def check_w1(cfg: Config, w1, rounds: int = 0, sleep=time.sleep) -> bool:
    """1-Wire 에 보이는 DS18B20 ID 를 설정과 맞춰 본다. rounds > 0 이면 그동안 온도를 보여 줘 위치를 구별하게 한다"""
    sc = cfg.sensors
    if not probes_used(cfg):
        return report([("DS18B20 접촉 프로브", SKIP, "설정에서 ds18b20_count: 0")])
    print("1-Wire (BCM 4, 40핀 7번) 접촉 프로브 확인")
    try:
        found = w1.ids()
    except Exception as e:                                  # noqa: BLE001
        return report([("DS18B20 접촉 프로브", FAIL, str(e))])
    rows = []
    want_ids = normalize_ids(sc.ds18b20_ids)                # 서비스와 같은 규칙 (대문자, 공백, 문자열 하나)
    if want_ids:
        for i, rid in enumerate(want_ids):
            seen = rid in found
            rows.append((f"프로브{i + 1}", PASS if seen else FAIL, f"{rid} {'보임' if seen else '안 보임'}"))
        extra = [x for x in found if x not in want_ids]
        if extra:
            rows.append(("설정에 없는 프로브", WARN, ", ".join(extra)))
    else:
        want = sc.ds18b20_count
        hint = "" if len(found) >= want else ". 1-Wire 켜짐(dtoverlay), DQ 와 3.3 V 사이 4.7 kΩ, 3선 결선 확인"
        rows.append(("DS18B20 접촉 프로브", PASS if len(found) == want else FAIL,
                     f"{len(found)}/{want} 개: {', '.join(found) or '없음'}{hint}"))
    ok = report(rows)
    ids = want_ids or found
    if rounds > 0 and ids:
        print(f"프로브 구별: {rounds} 바퀴 (프로브 하나 읽는 데 약 0.75 초) 동안 프로브를 하나씩 10 초씩 손으로 "
              "쥐어 보십시오. 괄호 안은 처음보다 오른 ℃ 이고, 지금 쥐고 있는 프로브가 계속 오릅니다.")
        first: dict[str, float] = {}
        t0 = time.monotonic()
        for k in range(rounds):
            cells = []
            for rid in ids:
                try:
                    v = parse_w1_slave(w1.read_slave(rid))
                except Exception:                           # noqa: BLE001
                    cells.append(f"{rid}    --        ")
                    continue
                if v == POWER_ON_C:                         # 전원 초기값 (변환 안 됨): 오름으로 치지 않음
                    cells.append(f"{rid}  85?        ")
                    continue
                first.setdefault(rid, v)
                cells.append(f"{rid} {v:5.1f} ({v - first[rid]:+4.1f})")
            print(f"  {time.monotonic() - t0:5.0f}s  " + "   ".join(cells))
            if k < rounds - 1:
                sleep(0.2)
        print("  위치를 고정하려면 설정의 sensors.ds18b20_ids 에 [상판, 측면, 뒷면] 순서로 ID 를 적습니다.")
    return ok


def check_sensors(cfg: Config, bus, n: int, sleep=time.sleep, w1=None) -> bool:
    sc = cfg.sensors
    amg, sht, adc = AMG8833(bus, sc.amg8833_address), SHT31(bus, sc.sht31_address), ADS1115(bus, sc.ads1115_address)
    devs = [("AMG8833", amg), ("SHT31", sht), ("ADS1115", adc)]
    ir = MLX90614(bus, sc.mlx90614_address) if sc.mlx90614_address >= 0 else None
    if ir is not None:
        devs.append(("MLX90614", ir))
    probes = ProbeGroup(w1, sc.ds18b20_ids, sc.ds18b20_count) if w1 is not None and probes_used(cfg) else None
    if probes is not None:
        devs.append(("DS18B20", probes))
    alive = {}
    for name, dev in devs:
        try:
            info = dev.begin()
            alive[name] = True
            if name == "DS18B20":
                print(f"  {info}")
        except Exception as e:                              # noqa: BLE001
            alive[name] = False
            print(f"  {name} 시작 실패: {e}")
    therm, px_min, px_mean, px_max, temp, rh, a0, ir_obj, ir_die = [], [], [], [], [], [], [], [], []
    probe_vals = [[] for _ in range(probes.count)] if probes is not None else []
    errors = {k: 0 for k in alive}
    probe_err = [0] * len(probe_vals)
    print(f"센서 {n} 번 읽기 (1 초 간격{', 프로브는 하나에 약 0.75 초' if probes is not None else ''})")
    for i in range(n):
        if alive["AMG8833"]:
            try:
                therm.append(amg.read_thermistor_c())
                px = amg.read_pixels()
                px_min.append(min(px))
                px_mean.append(sum(px) / len(px))
                px_max.append(max(px))
            except Exception:                               # noqa: BLE001
                errors["AMG8833"] += 1
        if alive["SHT31"]:
            try:
                t, h = sht.read()
                temp.append(t)
                rh.append(h)
            except Exception:                               # noqa: BLE001
                errors["SHT31"] += 1
        if alive["ADS1115"]:
            try:
                a0.append(adc.read_volts(sc.smoke_channel))
            except Exception:                               # noqa: BLE001
                errors["ADS1115"] += 1
        if alive.get("MLX90614"):
            try:
                o, d = ir.read()
                ir_obj.append(o)
                ir_die.append(d)
            except Exception:                               # noqa: BLE001
                errors["MLX90614"] += 1
        if alive.get("DS18B20"):
            try:
                vals = probes.read()
            except Exception:                               # noqa: BLE001
                vals = [None] * probes.count
            for k, v in enumerate(vals):
                if v is None:
                    probe_err[k] += 1
                else:
                    probe_vals[k].append(v)
        if i < n - 1:
            sleep(1.0)

    amb = statistics.mean(temp) if temp else None
    rows = []
    # SHT31
    if not alive["SHT31"] or not temp:
        rows.append(("SHT31", FAIL, "읽지 못함"))
    else:
        t, h = statistics.mean(temp), statistics.mean(rh)
        ok = -10.0 < t < 60.0 and 0.0 <= h <= 100.0 and errors["SHT31"] == 0
        rows.append(("SHT31", PASS if ok else FAIL, f"{t:.1f} ℃, {h:.0f} %RH, 읽기 오류 {errors['SHT31']}"))
    # AMG8833
    if not alive["AMG8833"] or not therm:
        rows.append(("AMG8833", FAIL, "읽지 못함"))
    else:
        th, lo, mean, hi = statistics.mean(therm), min(px_min), statistics.mean(px_mean), max(px_max)
        ok = -10.0 < th < 80.0 and -20.0 < lo and hi < 120.0 and errors["AMG8833"] == 0
        detail = f"보드 {th:.1f} ℃, 화소 최저 {lo:.1f} 평균 {mean:.1f} 최고 {hi:.1f} ℃, 읽기 오류 {errors['AMG8833']}"
        result = PASS if ok else FAIL
        if ok and amb is not None and abs(mean - amb) > 10.0:
            result, detail = WARN, detail + ". 화소 평균이 주변 온도와 10 ℃ 넘게 다름 (화각에 뜨거운 것이 있는지)"
        rows.append(("AMG8833", result, detail))
    # ADS1115 + MQ-2
    if not alive["ADS1115"] or not a0:
        rows.append(("ADS1115 + MQ-2", FAIL, "읽지 못함"))
    else:
        v = statistics.mean(a0)
        ao = v * sc.smoke_divider
        if v > 3.3:
            result, note = FAIL, ". A0 가 3.3 V 를 넘음: 분압 저항(10 kΩ, 20 kΩ) 확인"
        elif ao < 0.1:
            result, note = WARN, ". MQ-2 출력이 거의 0: 히터 5 V, AO 결선 확인"
        else:
            result, note = PASS, ". 켠 뒤 3 분은 예열 중이라 값이 내려가는 것이 정상"
        if errors["ADS1115"]:
            result = FAIL
        rows.append(("ADS1115 + MQ-2", result,
                     f"A0 {v:.3f} V, MQ-2 출력 {ao:.2f} V (분압 {sc.smoke_divider}), 읽기 오류 {errors['ADS1115']}{note}"))
    # MLX90614
    if ir is not None:
        if not alive["MLX90614"] or not ir_obj:
            rows.append(("MLX90614 적외선", FAIL, "읽지 못함"))
        else:
            o, d = statistics.mean(ir_obj), statistics.mean(ir_die)
            ok = -20.0 < o < 120.0 and -10.0 < d < 80.0 and errors["MLX90614"] == 0
            result = PASS if ok else FAIL
            detail = f"물체 {o:.1f} ℃, 센서 {d:.1f} ℃, 읽기 오류 {errors['MLX90614']}"
            if errors["MLX90614"]:
                detail += ". PEC 오류가 나면 배선, I2C 속도(100 kHz 이하) 확인"
            if ok and amb is not None and abs(o - amb) > 10.0:
                result, detail = WARN, detail + ". 주변 온도와 10 ℃ 넘게 다름 (보는 면이 뜨겁거나 반사가 심한지)"
            rows.append(("MLX90614 적외선", result, detail))
    # DS18B20
    if probes is not None:
        if not alive["DS18B20"]:
            rows.append(("DS18B20 접촉 프로브", FAIL, "읽지 못함"))
        for k, name in enumerate(probes.names() if alive["DS18B20"] else []):
            rid = probes.ids[k] or "없음"
            if not probe_vals[k]:
                rows.append((f"{name} DS18B20", FAIL, f"{rid} 읽지 못함 ({probes.errors.get(rid, '안 보임')})"))
                continue
            m = statistics.mean(probe_vals[k])
            ok = -10.0 < m < 60.0 and probe_err[k] == 0
            result = PASS if ok else FAIL
            detail = f"{rid} {m:.2f} ℃, 읽기 오류 {probe_err[k]}"
            if ok and amb is not None and abs(m - amb) > 10.0:
                result, detail = WARN, detail + ". 주변 온도와 10 ℃ 넘게 다름 (손에 쥐고 있거나 뜨거운 곳인지)"
            rows.append((f"{name} DS18B20", result, detail))
    return report(rows)


def check_outputs(cfg: Config, fake: bool, assume_yes: bool, ask=input, sleep=time.sleep, on_s: float = 2.0,
                  log: list | None = None) -> bool:
    print("출력 시험. SSR 은 파워뱅크 충전 AC 라인을 켜고 끄는 장치입니다.")
    print("SSR 의 AC 쪽 결선을 빼 두었을 때만 진행하십시오. 220 V 결선 작업은 사람이 합니다.")
    if not assume_yes:
        if ask(f"SSR 의 AC 쪽을 뺐으면 '{AC_CONFIRM}' 라고 입력: ").strip() != AC_CONFIRM:
            print("확인이 없어 출력 시험을 하지 않습니다.")
            return False
    log = log if log is not None else []
    devs = open_outputs(cfg, fake, log)
    if not assume_yes:
        ask("지금 모든 출력이 꺼져 있어야 합니다. 이미 딸깍 붙어 있거나 켜진 것이 있으면 active_low 설정이 반대입니다. "
            "확인했으면 Enter: ")
    rows = []
    try:
        for key, label, question, off_question in OUTPUTS:
            dev = devs.get(key)
            if dev is None:
                rows.append((label, SKIP, "설정에서 -1"))
                continue
            dev.on()
            sleep(on_s)
            answer = "y" if assume_yes else ask(f"{label}: {question}? (y/n): ")
            dev.off()
            sleep(0.3)
            good = answer.strip().lower().startswith("y")
            if not good:
                rows.append((label, FAIL, "켜지지 않음. 결선, 전원, active_low 설정 확인"))
                continue
            if off_question:
                sleep(on_s / 2)
                released = "y" if assume_yes else ask(f"{label}: {off_question}? (y/n): ")
                if not released.strip().lower().startswith("y"):
                    rows.append((label, FAIL, "꺼지지 않음. 3.3 V 신호로 안 떨어지는 모듈: README 2장 하드웨어 주의 "
                                              "(JD-VCC 분리나 트랜지스터 구동)"))
                    continue
            rows.append((label, PASS, ""))
    finally:
        for dev in devs.values():
            if dev is not None:
                try:
                    dev.off()
                    dev.close()
                except Exception:                           # noqa: BLE001  닫다가 난 오류로 끄기를 멈추지 않음
                    pass
    print("모든 출력을 껐습니다.")
    return report(rows)


def check_button(cfg: Config, fake: bool, timeout_s: float = 30.0) -> bool:
    pin = cfg.pins.reset_button
    if pin < 0:
        return report([("래치 해제 버튼", SKIP, "설정에서 -1")])
    if fake:
        return report([("래치 해제 버튼", PASS, f"GPIO {pin} (가짜)")])
    from gpiozero import Button
    btn = Button(pin, pull_up=True)
    try:
        if btn.is_pressed:
            return report([("래치 해제 버튼", FAIL, f"GPIO {pin} 가 처음부터 눌린 상태 (GND 단락 확인)")])
        print(f"{timeout_s:.0f} 초 안에 버튼을 한 번 누르십시오 (GPIO {pin}, 누르면 GND)")
        pressed = btn.wait_for_press(timeout=timeout_s)
        return report([("래치 해제 버튼", PASS if pressed else FAIL,
                        "눌림 확인" if pressed else "눌림이 없음. 버튼 한쪽은 GPIO, 다른 쪽은 GND")])
    finally:
        btn.close()


# ------------------------------------------------------------------ 실행
def main(argv=None, ask=input, sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description="화재 감지기 보드 부품 확인")
    ap.add_argument("what", choices=["i2c", "w1", "sensors", "outputs", "button", "all"])
    ap.add_argument("--config", help=f"설정 YAML (기본: {DEFAULT_CONFIG} 이 있으면 그것)")
    ap.add_argument("--n", type=int, default=None, help="읽기 횟수 (sensors 기본 10, w1 은 주면 그동안 온도 표시)")
    ap.add_argument("--fake", action="store_true", help="하드웨어 없이 스크립트 시험")
    ap.add_argument("--yes", action="store_true", help="묻지 않고 진행 (--fake 와 함께 시험할 때만)")
    ap.add_argument("--force", action="store_true", help="fire-detect 서비스가 돌고 있어도 진행")
    a = ap.parse_args(argv)

    if a.yes and not a.fake:
        print("--yes 는 --fake 와 함께만 쓸 수 있습니다 (실제 출력은 사람이 보고 답해야 함).")
        return 2
    path = a.config or (DEFAULT_CONFIG if os.path.exists(DEFAULT_CONFIG) else None)
    cfg = load(path)
    print(f"설정: {path or '기본값'}{', 가짜 하드웨어' if a.fake else ''}")
    if not a.fake and not a.force and service_running():
        print("fire-detect 서비스가 돌고 있습니다. sudo systemctl stop fire-detect 후 다시 실행하고, "
              "끝나면 sudo systemctl start fire-detect.")
        return 2

    ok = True
    w1 = open_w1(a.fake)
    if a.what in ("w1", "all"):
        ok &= check_w1(cfg, w1, rounds=a.n if a.what == "w1" and a.n else 0, sleep=sleep)
    if a.what in ("i2c", "sensors", "all"):
        try:
            bus = open_bus(cfg, a.fake)
        except Exception as e:                              # noqa: BLE001
            print(f"I2C 버스 {cfg.i2c_bus} 를 열 수 없음: {e}. dtparam=i2c_arm=on, i2c 그룹 권한 확인")
            return 2
        try:
            if a.what in ("i2c", "all"):
                ok &= check_i2c(cfg, bus)
            if a.what in ("sensors", "all"):
                ok &= check_sensors(cfg, bus, a.n or 10, sleep=sleep, w1=w1)
        finally:
            bus.close()
    if a.what == "outputs":
        ok &= check_outputs(cfg, a.fake, a.yes, ask=ask, sleep=sleep)
    if a.what == "button":
        ok &= check_button(cfg, a.fake)
    print("결과:", "모두 통과" if ok else "실패가 있음")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
