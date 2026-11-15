"""
bench_test.py - 보조배터리 벤치 구성의 전체 기능 시험 (사람과 같이, 약 10~15 분)

    python3 tools/bench_test.py                         # config.battery.yaml, 모든 단계
    python3 tools/bench_test.py --skip hot,gas          # 뜨거운 컵, 가스 시험 빼고
    python3 tools/bench_test.py --fake                  # 하드웨어 없이 이 스크립트 시험 (사람 역할도 자동)
      --config FILE   기본 config.battery.yaml
      --out DIR       결과 폴더 (기본 ~/fire_logs/bench_<UTC시각>). 기록, 그래프, report.md 가 남는다

fire-detect 와 같은 코드(build, step)로 1 초마다 읽고 판정하면서, 단계마다 사람에게 할 일을 묻고
판정이 기대대로 바뀌는지 자동으로 확인한다. LED, 부저는 사람이 보고 y/n 으로 답한다.

  1 환경        Pi 입력 전압, 시각 동기화, LED 와 부저 GPIO
  2 센서 연결   AMG8833, SHT31, ADS1115 (+ 설정에 있으면 MLX90614, DS18B20)
  3 평상시      30 초 정상(녹색) 유지, 값이 말이 되는지 (주변 온습도, 열화상, 연기 전압)
  4 주의        손바닥을 멀리 -> 주의 (황색)
  5 경고        손바닥을 가까이 -> 경고 (적색 깜빡임, 부저 간헐)
  6 복귀        손을 치움 -> 정상 (녹색)
  7 위험 (hot)  뜨거운 물컵 -> 위험 래치 (적색, 부저 계속), 뜨거울 때 해제 요청 무시, 치운 뒤 래치 유지, 해제
  8 연기 (gas)  MQ-2 예열(3 분) 뒤 라이터 가스(불 없이) -> 위험, 가스가 빠진 뒤 해제
  9 기록        fire, thermal CSV, jsonl, 그래프 PNG

주의
  - fire-detect 가 이미 돌고 있으면 LED, 부저 GPIO 를 못 연다. 먼저 끝낼 것 (Ctrl+C 또는 sudo systemctl stop fire-detect)
  - 선을 뽑는 시험은 하지 않는다 (결선 변경은 보조배터리를 뺀 뒤에). 열화상 끊김은 simulate 시험으로 확인된다
  - 뜨거운 물은 화상 주의, 라이터 가스는 환기, 불꽃 금지
  - 어느 질문에서든 q 를 입력하면 그때까지 결과로 보고서를 쓰고 끝낸다
종료 코드: 0 실패 없음, 1 실패 있음, 2 시작하지 못함
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fire_detect import system_info  # noqa: E402
from fire_detect.alarm import FLAG_SHT_INVALID, LEVEL_CAUTION, LEVEL_DANGER, LEVEL_NORMAL, LEVEL_WARNING  # noqa: E402
from fire_detect.app import build  # noqa: E402
from fire_detect.config import load  # noqa: E402
from fire_detect.sensors import OK_ADS1115, OK_AMG8833, OK_DS18B20, OK_MLX90614, OK_SHT31  # noqa: E402

PASS, FAIL, WARN, SKIP = "통과", "실패", "주의", "건너뜀"
NAMES = {0: "정상", 1: "주의", 2: "경고", 3: "위험"}
STEPS = ("env", "sensors", "baseline", "caution", "warning", "clear", "hot", "gas", "logs")


class Quit(Exception):
    """사람이 q 로 끝냄"""


def ok(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def f1(v, nd=1) -> str:
    return f"{v:.{nd}f}" if ok(v) else "--"


@dataclass
class Result:
    step: str
    name: str
    result: str
    detail: str = ""


@dataclass
class Report:
    rows: list[Result] = field(default_factory=list)

    def add(self, step, name, result, detail=""):
        r = Result(step, name, result, detail)
        self.rows.append(r)
        mark = {PASS: "  [통과]", FAIL: "  [실패]", WARN: "  [주의]", SKIP: "  [건너뜀]"}[result]
        print(f"{mark} {name}" + (f": {detail}" if detail else ""), flush=True)
        return r

    @property
    def failed(self) -> bool:
        return any(r.result == FAIL for r in self.rows)


# ------------------------------------------------------------------ 사람 (실제, 가짜)
class Human:
    """실제 사람: 할 일을 보여 주고 Enter, 확인 질문은 y/n. s 는 건너뜀, q 는 끝냄"""

    def __init__(self, ask=input):
        self.ask = ask

    def do(self, key: str, text: str, skippable: bool = False) -> bool:
        print()
        hint = " (건너뛰려면 s)" if skippable else ""
        a = self.ask(f">> {text}. 준비되면 Enter{hint}: ").strip().lower()
        if a == "q":
            raise Quit()
        return not (skippable and a == "s")

    def confirm(self, key: str, question: str) -> bool | None:
        a = self.ask(f">> {question} (y/n, 모르겠으면 Enter): ").strip().lower()
        if a == "q":
            raise Quit()
        if a.startswith("y"):
            return True
        if a.startswith("n"):
            return False
        return None


class FakeWorld:
    """--fake: 가짜 센서 장면을 사람의 행동에 맞춰 바꾼다 (시뮬레이터의 normal 시나리오 위에)"""

    ACTIONS = {"face_wall": (0.0, 0.0), "hand_far": (7.0, 0.0), "hand_near": (15.0, 0.0), "hand_away": (0.0, 0.0),
               "hot_cup": (45.0, 0.0), "cup_away": (0.0, 0.0), "gas": (0.0, 0.6)}

    def __init__(self, scen, seed: int = 7):
        self.rise = 0.0
        self.smoke = 0.0
        self.rng = random.Random(seed)
        scen.hotspot_rise = lambda: self.rise                        # 인스턴스 메서드를 바꿔 장면을 조종
        scen.smoke_v = lambda: 0.80 + self.rng.gauss(0, 0.005) + self.smoke

    def tick(self):
        if self.smoke > 0:
            self.smoke = max(0.0, self.smoke - 0.01)                 # 가스는 1 분쯤에 걸쳐 빠짐


class FakeHuman(Human):
    def __init__(self, world: FakeWorld, answers: dict | None = None):
        super().__init__(ask=lambda q: "")
        self.world = world
        self.answers = answers or {}

    def do(self, key, text, skippable=False):
        print(f"\n>> {text} (가짜 사람: {key})")
        if key in FakeWorld.ACTIONS:
            self.world.rise, gas = FakeWorld.ACTIONS[key]
            if gas:
                self.world.smoke = gas
        return True

    def confirm(self, key, question):
        print(f">> {question} (가짜 사람: y)")
        return self.answers.get(key, True)


# ------------------------------------------------------------------ 시험대
class Bench:
    def __init__(self, cfg, out: Path, fake: bool, human_ask=input):
        self.cfg = cfg
        self.out = out
        self.fake = fake
        self.app_log: list[str] = []
        cfg.reset_file = str(out / "reset.request")                 # 다른 fire-detect 와 섞이지 않게
        cfg.latch_file = ""
        tty = sys.stdout.isatty()

        def log(m):
            self.app_log.append(f"{time.strftime('%H:%M:%S')} {m}")
            print(("\n" if tty else "") + f"     (fire-detect: {m})", flush=True)
        self.app, self.scen = build(cfg, "normal" if fake else None, str(out / "logs"), False, log=log)
        if fake:
            self.world = FakeWorld(self.scen)
            self.human = FakeHuman(self.world)
        else:
            self.world = None
            self.human = Human(human_ask)
        self.t0 = self.app.clock()
        self.next_t = time.monotonic()
        self.last = None
        self.ticks = 0
        self.tty = sys.stdout.isatty()

    def elapsed(self) -> float:
        return self.app.clock() - self.t0

    def tick(self):
        s = self.app.step()
        self.last = s
        self.ticks += 1
        if self.fake:
            self.scen.t += self.cfg.period_s
            self.world.tick()
        else:
            self.next_t += self.cfg.period_s
            time.sleep(max(0.0, self.next_t - time.monotonic()))
        if self.tty:
            print(f"\r     [{NAMES.get(s.level, '?')}{' 래치' if s.latched else ''}{' 감시불가' if s.fault else ''}] "
                  f"최고 {f1(s.surface_max_c)} 주변 {f1(s.ambient_temp_c)}℃ {f1(s.ambient_rh_pct, 0)}% "
                  f"뜨거운 화소 {s.hot_pixels} 연기 {f1(s.smoke_v, 3)}V   ", end="", flush=True)
        return s

    def endline(self):
        if self.tty:
            print()

    def run(self, seconds: float) -> list:
        out = [self.tick() for _ in range(max(1, int(round(seconds / self.cfg.period_s))))]
        self.endline()
        return out

    def wait_for(self, pred, timeout: float):
        """pred(status) 가 참이 될 때까지. (참이 됐나, 걸린 초, 마지막 status)"""
        start = self.elapsed()
        while self.elapsed() - start < timeout:
            s = self.tick()
            if pred(s):
                self.endline()
                return True, self.elapsed() - start, s
        self.endline()
        return False, self.elapsed() - start, self.last

    def reset(self):
        Path(self.cfg.reset_file).touch()

    def close(self):
        with contextlib.suppress(Exception):
            self.app.close()


# ------------------------------------------------------------------ 단계
def step_env(b: Bench, rep: Report):
    if b.fake:
        rep.add("env", "환경", SKIP, "가짜 하드웨어")
        return
    v = system_info.supply_v()
    if ok(v):
        rep.add("env", "Pi 5 입력 전압", PASS if v >= 4.75 else WARN,
                f"{v:.2f} V" + ("" if v >= 4.75 else " (4.75 V 아래: 보조배터리나 케이블이 약함)"))
    else:
        rep.add("env", "Pi 5 입력 전압", SKIP, "vcgencmd 로 못 읽음 (Ubuntu 는 libraspberrypi-bin 필요)")
    rep.add("env", "시각 동기화", PASS if system_info.clock_synced() else WARN,
            "" if system_info.clock_synced() else "NTP 안 맞음: 기록에 TIME_UNSYNCED (핫스팟 등에 붙여 맞출 것)")
    p = b.cfg.pins
    used = any(x >= 0 for x in (p.buzzer, p.led_red, p.led_yellow, p.led_green))
    if not used:
        rep.add("env", "LED, 부저 GPIO", SKIP, "설정에 없음")
    elif b.app.gpio_ok:
        rep.add("env", "LED, 부저 GPIO", PASS, "열림")
    else:
        rep.add("env", "LED, 부저 GPIO", FAIL, "못 엶: fire-detect 가 돌고 있나, gpio(dialout) 그룹, BATTERY_BENCH 2-2")


def step_sensors(b: Bench, rep: Report) -> bool:
    mask = b.app.hub.begin()
    sc = b.cfg.sensors
    want = [("AMG8833 열화상", OK_AMG8833, True), ("SHT31 온습도", OK_SHT31, True), ("ADS1115 + MQ-2", OK_ADS1115, True),
            ("MLX90614 적외선", OK_MLX90614, sc.mlx90614_address >= 0),
            ("DS18B20 접촉 프로브", OK_DS18B20, bool(sc.ds18b20_ids) or sc.ds18b20_count > 0)]
    for name, bit, used in want:
        if not used:
            continue
        good = bool(mask & bit)
        slot = next((sl for sl in b.app.hub.slots.values() if sl.bit == bit), None)
        hint = {OK_SHT31: "i2cdetect 에 44, SDA, SCL 이 바뀌지 않았는지, VIN 3.3 V",
                OK_AMG8833: "i2cdetect 에 69 (또는 68: 설정 고침)", OK_ADS1115: "i2cdetect 에 48"}.get(bit, "")
        rep.add("sensors", name, PASS if good else FAIL,
                "연결됨" if good else f"응답 없음 ({slot.last_error if slot else ''}) {hint}".strip())
    return bool(mask & OK_AMG8833)


def step_baseline(b: Bench, rep: Report):
    b.human.do("face_wall", "열화상을 아무것도 없는 벽 쪽으로 두고, 손과 뜨거운 것(Pi, MQ-2 히터, 조명)을 시야에서 치우세요")
    print("     30 초 동안 평상시 값을 봅니다 (켠 직후 10 초는 시작 대기)")
    ss = b.run(30)
    tail = ss[-15:]
    lv = max(s.level for s in tail)
    if lv == LEVEL_NORMAL and not any(s.fault for s in tail):
        rep.add("baseline", "평상시 정상 유지 (마지막 15 초)", PASS)
    else:
        s = max(tail, key=lambda x: x.level)
        rep.add("baseline", "평상시 정상 유지 (마지막 15 초)", FAIL,
                f"{NAMES[lv]}: {s.reason}. 시야에 뜨거운 것이 있거나 주변 온도가 틀어짐 (SHT31)")
    last = ss[-1]
    amb, rh = last.ambient_temp_c, last.ambient_rh_pct
    if last.flags & FLAG_SHT_INVALID:
        rep.add("baseline", "주변 온습도 (SHT31)", FAIL,
                f"SHT31 값 없음. 주변 온도를 열화상 최저 화소({f1(amb)} ℃)로 대신 쓰는 중이라 판정이 틀어질 수 있음")
    elif ok(amb) and ok(rh) and 0 <= amb <= 45 and 5 <= rh <= 95:
        rep.add("baseline", "주변 온습도 (SHT31)", PASS, f"{amb:.1f} ℃, {rh:.0f} %")
    else:
        rep.add("baseline", "주변 온습도 (SHT31)", FAIL, f"{f1(amb)} ℃, {f1(rh, 0)} %: 실내 값으로 보기 어려움")
    mn, mean, mx = last.surface_min_c, last.surface_mean_c, last.surface_max_c
    if ok(mx) and ok(amb):
        good = -10 <= mn and mx <= 100 and abs(mean - amb) <= 6
        rep.add("baseline", "열화상 값", PASS if good else WARN,
                f"최저 {mn:.1f}, 평균 {mean:.1f}, 최고 {mx:.1f} ℃ (주변과 평균 차 {mean - amb:+.1f} ℃)"
                + ("" if good else ". 평균이 주변과 6 ℃ 넘게 다름: 창, 조명, 히터를 보고 있지 않은지"))
    else:
        rep.add("baseline", "열화상 값", FAIL, "값 없음")
    v = last.smoke_v
    if ok(v):
        a0 = v / b.cfg.sensors.smoke_divider
        good = 0.02 <= v and a0 < 3.25
        rep.add("baseline", "MQ-2 연기 전압", PASS if good else FAIL,
                f"AO {v:.3f} V (A0 {a0:.3f} V)" + ("" if good else ". 0 V 근처면 전원, AO 선. A0 3.3 V 근처면 분압 저항"))
    else:
        rep.add("baseline", "MQ-2 연기 전압", FAIL, "값 없음 (ADS1115)")
    led = b.human.confirm("led_green", "녹색 LED 만 켜져 있고 부저는 조용합니까")
    rep.add("baseline", "LED: 정상 = 녹색", {True: PASS, False: FAIL, None: SKIP}[led])


def step_caution(b: Bench, rep: Report):
    b.human.do("hand_far", "손바닥을 열화상 정면 20~30 cm 앞에 대고 그대로 있으세요")
    got, sec, s = b.wait_for(lambda s: s.level >= LEVEL_CAUTION, 25)
    if not got:
        rep.add("caution", "손 -> 주의", FAIL, f"25 초 안에 안 오름 (최고 {f1(s.surface_max_c)}, 주변 {f1(s.ambient_temp_c)} ℃, "
                                             f"기준 주변 + {b.cfg.alarm.delta_c:.0f} ℃). 손을 조금 더 가까이")
        return
    rep.add("caution", "손 -> 주의 이상", PASS, f"{sec:.0f} 초, {NAMES[s.level]}, {s.reason}")
    if s.level == LEVEL_CAUTION:
        led = b.human.confirm("led_yellow", "황색 LED 가 켜졌습니까")
        rep.add("caution", "LED: 주의 = 황색", {True: PASS, False: FAIL, None: SKIP}[led])
    else:
        rep.add("caution", "LED: 주의 = 황색", SKIP, "바로 경고로 올라 황색을 못 봄 (손이 가까웠음)")


def step_warning(b: Bench, rep: Report):
    b.human.do("hand_near", "손바닥을 5~10 cm 까지 가까이 대고 그대로 있으세요 (화소 3 개 이상이 뜨거워지게)")
    got, sec, s = b.wait_for(lambda s: s.level >= LEVEL_WARNING, 25)
    if not got:
        rep.add("warning", "가까운 손 -> 경고", FAIL, f"25 초 안에 안 오름 (뜨거운 화소 {s.hot_pixels} 개, 3 개 이상 필요)")
        return
    rep.add("warning", "가까운 손 -> 경고 이상", PASS, f"{sec:.0f} 초, {NAMES[s.level]}, 뜨거운 화소 {s.hot_pixels} 개")
    if s.level == LEVEL_WARNING:
        b.run(3)
        led = b.human.confirm("led_red_blink", "적색 LED 가 깜빡이고 부저가 2 초마다 짧게 울립니까")
        rep.add("warning", "LED, 부저: 경고 = 적색 깜빡임, 부저 간헐", {True: PASS, False: FAIL, None: SKIP}[led])
    else:
        rep.add("warning", "LED, 부저: 경고", SKIP, "손 온도로 위험까지 감 (60 ℃ 이상을 봄)")


def step_clear(b: Bench, rep: Report):
    b.human.do("hand_away", "손을 치우세요")
    if b.last is not None and b.last.latched:
        rep.add("clear", "손을 치움 -> 정상", SKIP, "위험 래치가 걸려 있어 해제가 필요")
        b.reset()
        b.run(3)
        return
    got, sec, s = b.wait_for(lambda s: s.level == LEVEL_NORMAL, 45)
    rep.add("clear", "손을 치움 -> 정상", PASS if got else FAIL,
            f"{sec:.0f} 초 (내려갈 때는 {b.cfg.alarm.clear_s:.0f} 초 유지 필요)" if got else f"45 초 안에 안 내려옴: {s.reason}")
    if got:
        led = b.human.confirm("led_green2", "다시 녹색 LED 만 켜지고 부저는 조용합니까")
        rep.add("clear", "LED: 다시 녹색", {True: PASS, False: FAIL, None: SKIP}[led])


def step_hot(b: Bench, rep: Report):
    c = b.cfg.alarm
    if not b.human.do("hot_cup", f"끓인 물을 머그컵에 담아 열화상 10 cm 앞에 두세요 ({c.abs_limit_c:.0f} ℃ 넘게 보여야 함, 화상 주의)",
                      skippable=True):
        rep.add("hot", "뜨거운 물컵 -> 위험", SKIP, "사람이 건너뜀")
        return
    got, sec, s = b.wait_for(lambda s: s.level == LEVEL_DANGER and s.latched, 30)
    if not got:
        rep.add("hot", "뜨거운 물컵 -> 위험 래치", FAIL, f"30 초 안에 안 됨 (최고 {f1(s.surface_max_c)} ℃, 기준 {c.abs_limit_c:.0f} ℃)."
                                                    " 물이 식었거나 멀음")
        return
    rep.add("hot", "뜨거운 물컵 -> 위험 래치", PASS, f"{sec:.0f} 초, 최고 {f1(s.surface_max_c)} ℃")
    b.run(2)
    led = b.human.confirm("led_red", "적색 LED 가 계속 켜지고 부저가 계속 울립니까")
    rep.add("hot", "LED, 부저: 위험 = 적색, 부저 계속", {True: PASS, False: FAIL, None: SKIP}[led])
    b.reset()                                                     # 뜨거울 때 해제 요청: 무시되어야 함
    ss = b.run(3)
    rep.add("hot", "뜨거울 때 해제 요청은 무시", PASS if all(x.latched for x in ss) else FAIL,
            "" if all(x.latched for x in ss) else "뜨거운데 래치가 풀림")
    b.human.do("cup_away", "컵을 치우세요 (식을 때까지 기다립니다)")
    cool = c.abs_limit_c - c.hysteresis_c
    got, sec, s = b.wait_for(lambda s: ok(s.surface_max_c) and s.surface_max_c < cool and s.hot_pixels == 0, 90)
    if not got:
        rep.add("hot", "컵을 치움 -> 식음", FAIL, f"90 초 안에 안 식음 (최고 {f1(s.surface_max_c)} ℃). 시야에 다른 뜨거운 것이 있는지")
        return
    ss = b.run(12)                                               # clear_s 보다 길게: 래치라 안 내려와야 함
    rep.add("hot", "식은 뒤에도 래치 유지 (사람이 풀 때까지)", PASS if all(x.latched for x in ss) else FAIL)
    b.reset()
    got, sec, s = b.wait_for(lambda s: not s.latched and s.level == LEVEL_NORMAL, 20)
    rep.add("hot", "해제 요청 -> 정상", PASS if got else FAIL, f"{sec:.0f} 초" if got else s.reason)


def step_gas(b: Bench, rep: Report):
    c = b.cfg.alarm
    left = c.smoke_warmup_s - b.elapsed() + 5
    if left > 0:
        print(f"\n     MQ-2 예열이 끝나기를 {left:.0f} 초 기다립니다 (켠 뒤 {c.smoke_warmup_s:.0f} 초는 연기 판정을 안 함)")
        b.run(left)
    if b.last is not None and b.last.level != LEVEL_NORMAL:
        b.wait_for(lambda s: s.level == LEVEL_NORMAL, 30)
    base = b.last.smoke_baseline_v if b.last else float("nan")
    if not b.human.do("gas", "라이터를 불 붙이지 말고 MQ-2 10 cm 앞에서 가스만 1~2 초 누르세요 (환기, 불꽃 금지)",
                      skippable=True):
        rep.add("gas", "가스 -> 위험", SKIP, "사람이 건너뜀")
        return
    got, sec, s = b.wait_for(lambda s: s.smoke_detected or (s.level == LEVEL_DANGER and "연기" in s.reason), 30)
    if not got:
        rep.add("gas", "가스 -> 연기 위험", FAIL, f"30 초 안에 안 됨 (연기 {f1(s.smoke_v, 3)} V, 기준 {f1(base, 3)} V, "
                                             f"+{c.smoke_dv:.2f} V 필요). 더 가까이, 조금 더 길게")
        return
    rep.add("gas", "가스 -> 연기 위험", PASS, f"{sec:.0f} 초, 연기 {f1(s.smoke_v, 3)} V (기준 {f1(base, 3)} V)")
    print("     가스가 빠지기를 기다립니다 (최대 5 분, 부채질하면 빨라짐)")
    got, sec, s = b.wait_for(lambda s: ok(s.smoke_v) and ok(s.smoke_baseline_v)
                             and s.smoke_v - s.smoke_baseline_v < 0.5 * c.smoke_dv, 300)
    if not got:
        rep.add("gas", "가스가 빠짐", WARN, f"5 분 안에 기준 가까이 안 돌아옴 ({f1(s.smoke_v, 3)} V). 래치는 그대로 둠")
        return
    rep.add("gas", "가스가 빠짐", PASS, f"{sec:.0f} 초, 연기 {f1(s.smoke_v, 3)} V")
    b.run(3)
    b.reset()
    got, sec, s = b.wait_for(lambda s: not s.latched and s.level == LEVEL_NORMAL, 20)
    rep.add("gas", "해제 요청 -> 정상", PASS if got else FAIL, f"{sec:.0f} 초" if got else s.reason)


def step_logs(b: Bench, rep: Report):
    d = b.out / "logs"
    fire = sorted(d.glob("fire_*.csv"))
    thermal = sorted(d.glob("thermal_*.csv"))
    jl = sorted(d.glob("fire_*.jsonl"))
    rows = 0
    for p in fire:
        with open(p, encoding="utf-8", errors="replace") as fh:
            rows += max(0, sum(1 for _ in fh) - 1)
    good = fire and rows >= 0.9 * b.ticks
    rep.add("logs", "판정 기록 fire_*.csv", PASS if good else FAIL, f"{rows} 줄 / {b.ticks} 초")
    rep.add("logs", "열화상 기록 thermal_*.csv", PASS if thermal or not b.cfg.log.thermal else FAIL,
            ", ".join(p.name for p in thermal))
    kinds = set()
    for p in jl:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                with contextlib.suppress(ValueError):
                    kinds.add(json.loads(line).get("type"))
    rep.add("logs", "규격 기록 jsonl (fire_status, device_health)",
            PASS if {"fire_status", "device_health"} <= kinds else FAIL, ", ".join(sorted(k for k in kinds if k)))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("plot_log", Path(__file__).with_name("plot_log.py"))
        pl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pl)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = pl.main(["--dir", str(d), "--out", str(b.out / "plots")])
        pngs = sorted((b.out / "plots").glob("*.png"))
        tail = buf.getvalue().strip().splitlines()
        rep.add("logs", "그래프 PNG", PASS if code == 0 and pngs else WARN,
                ", ".join(p.name for p in pngs) or (tail[-1] if tail else "없음"))
    except Exception as e:                                           # noqa: BLE001
        rep.add("logs", "그래프 PNG", WARN, f"못 그림: {e}")


def write_report(b: Bench | None, rep: Report, out: Path, args, started: str) -> Path:
    lines = [f"# 화재 감지기 벤치 전체 시험 ({started} UTC)", "",
             f"- 설정: `{args.config}`{', 가짜 하드웨어' if args.fake else ''}",
             f"- 건너뛴 단계: {args.skip or '없음'}",
             f"- 시험 시간: {b.elapsed():.0f} 초" if b else "- 시작하지 못함", "",
             "| 단계 | 항목 | 결과 | 내용 |", "|---|---|---|---|"]
    for r in rep.rows:
        lines.append(f"| {r.step} | {r.name} | {r.result} | {str(r.detail).replace('|', '/')} |")
    n = {k: sum(1 for r in rep.rows if r.result == k) for k in (PASS, FAIL, WARN, SKIP)}
    lines += ["", f"**합계: 통과 {n[PASS]}, 실패 {n[FAIL]}, 주의 {n[WARN]}, 건너뜀 {n[SKIP]}**", "",
              f"- 기록: `{out / 'logs'}`", f"- 그래프: `{out / 'plots'}`"]
    if b and b.app_log:
        lines += ["", "## fire-detect 로그", "", "```"] + b.app_log[-60:] + ["```"]
    p = out / "report.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def main(argv=None, ask=input) -> int:
    ap = argparse.ArgumentParser(description="보조배터리 벤치 전체 기능 시험")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.battery.yaml"))
    ap.add_argument("--out")
    ap.add_argument("--skip", default="", help=f"쉼표로: {', '.join(STEPS)}")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args(argv)
    skip = {x.strip() for x in a.skip.split(",") if x.strip()}
    bad = skip - set(STEPS)
    if bad:
        print(f"모르는 단계: {sorted(bad)} (가능: {', '.join(STEPS)})")
        return 2
    started = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = Path(os.path.expanduser(a.out)) if a.out else Path(os.path.expanduser(f"~/fire_logs/bench_{started}"))
    out.mkdir(parents=True, exist_ok=True)
    cfg = load(a.config)
    rep = Report()
    print(f"설정: {a.config}{', 가짜 하드웨어' if a.fake else ''}\n결과 폴더: {out}\n"
          "어느 질문에서든 q 를 입력하면 그때까지의 결과로 보고서를 쓰고 끝냅니다.")
    try:
        b = Bench(cfg, out, a.fake, human_ask=ask)
    except Exception as e:                                           # noqa: BLE001
        print(f"시작하지 못함: {e}")
        rep.add("env", "시작", FAIL, str(e))
        write_report(None, rep, out, a, started)
        return 2
    plan = [("env", step_env), ("sensors", None), ("baseline", step_baseline), ("caution", step_caution),
            ("warning", step_warning), ("clear", step_clear), ("hot", step_hot), ("gas", step_gas)]
    try:
        for key, fn in plan:
            if key in skip:
                rep.add(key, f"{key} 단계", SKIP, "--skip")
                continue
            print(f"\n== {key} ==")
            if key == "sensors":
                if not step_sensors(b, rep):
                    print("열화상이 없으면 동작 시험을 할 수 없어 기록 확인으로 넘어갑니다.")
                    break
                continue
            fn(b, rep)
    except Quit:
        print("\n사람이 끝냄 (q)")
        rep.add("-", "중단", WARN, "q 로 끝냄")
    except KeyboardInterrupt:
        print("\nCtrl+C")
        rep.add("-", "중단", WARN, "Ctrl+C")
    finally:
        b.close()                                                    # LED, 부저 끄기
    if "logs" not in skip:
        print("\n== logs ==")
        step_logs(b, rep)
    p = write_report(b, rep, out, a, started)
    n_fail = sum(1 for r in rep.rows if r.result == FAIL)
    print(f"\n보고서: {p}\n실패 {n_fail} 건. 보고서 내용을 그대로 붙여 주면 함께 봅니다:  cat {p}")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
