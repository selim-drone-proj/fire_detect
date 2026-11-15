"""
simulate.py - 하드웨어 없이 화재 감지기를 돌려 보기 위한 가짜 장치와 시나리오

가짜 장치는 실제 I2C 레지스터 형식으로 응답하므로 드라이버 코드까지 그대로 시험된다.

시나리오 (fire-detect --simulate <이름>)
  overheat     120 초부터 한 화소가 데워지기 시작 -> 주의 -> 경고 -> 60 ℃ 위험 -> 270 초부터 연기
               330 초부터 (충전이 끊겨) 식음. 래치는 사람이 해제해야 풀림.
               접촉 프로브 1 (발열점 근처)과 적외선도 따라 오르지만 60 ℃ 에는 못 미친다
  normal       정상 충전만 (배터리 면이 주변보다 3 ℃ 따뜻함). 기준값 시험용
  sensor_loss  60~120 초 열화상 끊김 -> 10 초 뒤 감시 불가로 충전 차단 -> 복구
  hidden_heat  열화상에 안 보이는 뒷면 발열: 120 초부터 접촉 프로브 3 만 오름 -> 주의 -> 60 ℃ 위험(차단, 래치)
               260 초부터 식음

점 센서 (가짜): 프로브 1 상판(발열점 근처), 프로브 2 측면, 프로브 3 뒷면(열화상에 안 보임),
적외선은 측면을 가까이서 본다. 잡음은 별도 난수열이라 기존 센서 값은 예전과 똑같다.
"""
from __future__ import annotations

import math
import random

from .drivers.ds18b20 import crc8_maxim
from .drivers.i2c_bus import FakeBus, FakeDevice
from .drivers.mlx90614 import crc8_smbus
from .drivers.sensirion import pack_words

AMBIENT_C = 24.0
PACK = {(r, c) for r in range(2, 6) for c in range(1, 7)}       # 배터리가 보이는 화소
HOT = (3, 4)                                                      # 발열 시작점
NEIGHBORS = {(3, 3), (4, 4), (2, 4), (3, 5), (4, 3)}
SCENARIOS = ("overheat", "normal", "sensor_loss", "hidden_heat")
PROBE_SHARE = (0.5, 0.2, 0.0)                                     # 프로브별로 발열점 상승을 얼마나 따라가나
IR_SHARE = 0.4


class Scenario:
    def __init__(self, name: str = "overheat", seed: int = 1):
        if name not in SCENARIOS:
            raise ValueError(f"모르는 시나리오: {name}")
        self.name = name
        self.rng = random.Random(seed)
        self.rng_points = random.Random(seed + 1000)            # 점 센서 잡음 (기존 센서 난수열을 바꾸지 않게)
        self.t = 0.0

    def hotspot_rise(self) -> float:
        """발열점이 배터리 면보다 몇 ℃ 높은가"""
        if self.name != "overheat" or self.t < 120:
            return 0.0
        if self.t < 330:
            return 0.25 * (self.t - 120)                       # 초당 0.25 ℃
        peak = 0.25 * 210
        return peak * math.exp(-(self.t - 330) / 60.0)          # 충전 차단 뒤 식음

    def hidden_rise(self) -> float:
        """뒷면(프로브 3) 발열이 배터리 면보다 몇 ℃ 높은가 (hidden_heat 시나리오)"""
        if self.name != "hidden_heat" or self.t < 120:
            return 0.0
        if self.t < 260:
            return 0.25 * (self.t - 120)
        return 0.25 * 140 * math.exp(-(self.t - 260) / 60.0)

    def pixels(self) -> list[float] | None:
        if self.name == "sensor_loss" and 60 <= self.t < 120:
            return None
        rise = self.hotspot_rise()
        out = []
        for r in range(8):
            for c in range(8):
                p = AMBIENT_C + self.rng.gauss(0, 0.2)
                if (r, c) in PACK:
                    p += 3.0
                if (r, c) == HOT:
                    p += rise
                elif (r, c) in NEIGHBORS:
                    p += 0.45 * rise
                out.append(round(p * 4) / 4)                   # AMG8833 분해능 0.25 ℃
        return out

    def ambient(self) -> tuple[float, float]:
        return AMBIENT_C + 0.02 * self.hotspot_rise() + self.rng.gauss(0, 0.05), 45.0 + self.rng.gauss(0, 0.3)

    def probe_c(self, i: int) -> float:
        """접촉 프로브 i (0, 1, 2) ℃. DS18B20 분해능 1/16 ℃"""
        v = AMBIENT_C + 3.0 + PROBE_SHARE[i] * self.hotspot_rise() + self.rng_points.gauss(0, 0.05)
        if i == 2:
            v += self.hidden_rise()
        return round(v * 16) / 16

    def ir(self) -> tuple[float, float]:
        """적외선 (물체 ℃, 센서 자체 ℃)"""
        obj = AMBIENT_C + 2.5 + IR_SHARE * self.hotspot_rise() + self.rng_points.gauss(0, 0.1)
        return obj, AMBIENT_C + 1.0 + self.rng_points.gauss(0, 0.02)

    def smoke_v(self) -> float:
        v = 0.80 + self.rng.gauss(0, 0.005)
        if self.name == "overheat" and self.t >= 270:
            v += min(0.6, 0.02 * (self.t - 270)) * (math.exp(-(self.t - 330) / 90.0) if self.t > 330 else 1.0)
        return v


# ------------------------------------------------------------------ 가짜 장치 (레지스터 수준)
class FakeAMG8833(FakeDevice):
    def __init__(self, scen: Scenario):
        self.scen = scen
        self.reg = 0

    def on_write(self, data):
        self.reg = data[0]

    def on_read(self, n):
        if self.reg == 0x0E:                                   # 서미스터 25 ℃ = 400 x 0.0625
            return bytes([400 & 0xFF, 400 >> 8])[:n]
        if self.reg == 0x80:
            px = self.scen.pixels()
            if px is None:
                raise OSError(121, "Remote I/O error")
            out = bytearray()
            for p in px:
                raw = int(round(p / 0.25)) & 0xFFF
                out += bytes([raw & 0xFF, raw >> 8])
            return bytes(out[:n])
        return bytes(n)


class FakeSHT31(FakeDevice):
    def __init__(self, scen: Scenario):
        self.scen = scen

    def on_read(self, n):
        t, rh = self.scen.ambient()
        return pack_words(int((t + 45.0) / 175.0 * 65535), int(rh / 100.0 * 65535))[:n]


class FakeADS1115(FakeDevice):
    def __init__(self, scen: Scenario, divider: float = 1.5, fs: float = 4.096):
        self.scen = scen
        self.divider = divider
        self.fs = fs
        self.reg = 0

    def on_write(self, data):
        self.reg = data[0]

    def on_read(self, n):
        if self.reg == 0x01:
            return bytes([0x80, 0x00])[:n]                     # OS=1: 변환 끝
        raw = int(round(self.scen.smoke_v() / self.divider / self.fs * 32768)) & 0xFFFF
        return bytes([raw >> 8, raw & 0xFF])[:n]


class FakeMLX90614(FakeDevice):
    """명령(RAM 주소)을 받고 3 B (하위, 상위, PEC) 로 답한다"""

    def __init__(self, scen: Scenario, addr: int = 0x5A):
        self.scen = scen
        self.addr = addr
        self.cmd = 0

    def on_write(self, data):
        self.cmd = data[0]

    def on_read(self, n):
        obj, amb = self.scen.ir()
        t = obj if self.cmd == 0x07 else amb if self.cmd == 0x06 else -273.15
        raw = int(round((t + 273.15) / 0.02)) & 0x7FFF
        lo, hi = raw & 0xFF, raw >> 8
        pec = crc8_smbus(bytes([self.addr << 1, self.cmd, (self.addr << 1) | 1, lo, hi]))
        return bytes([lo, hi, pec])[:n]


def w1_slave_text(c: float) -> str:
    """℃ -> 커널 w1_therm 이 보여 주는 w1_slave 두 줄 (CRC 포함)"""
    signed = int(round(c * 16))                                # 12 비트, 1/16 ℃
    raw = signed & 0xFFFF
    pad = bytes([raw & 0xFF, raw >> 8, 0x4B, 0x46, 0x7F, 0xFF, 0x0C, 0x10])
    data = pad + bytes([crc8_maxim(pad)])
    hexes = " ".join(f"{b:02x}" for b in data)
    milli = int(signed * 1000 / 16)                            # 커널처럼 0 쪽으로 버림
    return f"{hexes} : crc={data[8]:02x} YES\n{hexes} t={milli}\n"


class FakeW1:
    """가짜 1-Wire 버스 (W1Sysfs 와 같은 함수). 프로브 3 개"""
    IDS = ("28-00000a000001", "28-00000a000002", "28-00000a000003")

    def __init__(self, scen: Scenario, ids=IDS):
        self.scen = scen
        self.present = list(ids)

    def ids(self) -> list[str]:
        return sorted(self.present)

    def read_slave(self, rom_id: str) -> str:
        if rom_id not in self.present:
            raise FileNotFoundError(f"/sys/bus/w1/devices/{rom_id}/w1_slave")
        return w1_slave_text(self.scen.probe_c(self.IDS.index(rom_id)))


def make_bus(scen: Scenario, amg=0x69, sht=0x44, ads=0x48, divider=1.5, mlx=0x5A) -> FakeBus:
    bus = FakeBus()
    bus.attach(amg, FakeAMG8833(scen))
    bus.attach(sht, FakeSHT31(scen))
    bus.attach(ads, FakeADS1115(scen, divider))
    if mlx is not None and mlx >= 0:
        bus.attach(mlx, FakeMLX90614(scen, mlx))
    return bus
