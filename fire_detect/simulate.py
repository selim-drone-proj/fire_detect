"""
simulate.py - 하드웨어 없이 화재 감지기를 돌려 보기 위한 가짜 장치와 시나리오

가짜 장치는 실제 I2C 레지스터 형식으로 응답하므로 드라이버 코드까지 그대로 시험된다.

시나리오 (fire-detect --simulate <이름>)
  overheat     120 초부터 한 화소가 데워지기 시작 -> 주의 -> 경고 -> 60 ℃ 위험 -> 270 초부터 연기
               330 초부터 (충전이 끊겨) 식음. 래치는 사람이 해제해야 풀림
  normal       정상 충전만 (배터리 면이 주변보다 3 ℃ 따뜻함). 기준값 시험용
  sensor_loss  60~120 초 열화상 끊김 -> 10 초 뒤 감시 불가로 충전 차단 -> 복구
"""
from __future__ import annotations

import math
import random

from .drivers.i2c_bus import FakeBus, FakeDevice
from .drivers.sensirion import pack_words

AMBIENT_C = 24.0
PACK = {(r, c) for r in range(2, 6) for c in range(1, 7)}       # 배터리가 보이는 화소
HOT = (3, 4)                                                      # 발열 시작점
NEIGHBORS = {(3, 3), (4, 4), (2, 4), (3, 5), (4, 3)}


class Scenario:
    def __init__(self, name: str = "overheat", seed: int = 1):
        if name not in ("overheat", "normal", "sensor_loss"):
            raise ValueError(f"모르는 시나리오: {name}")
        self.name = name
        self.rng = random.Random(seed)
        self.t = 0.0

    def hotspot_rise(self) -> float:
        """발열점이 배터리 면보다 몇 ℃ 높은가"""
        if self.name != "overheat" or self.t < 120:
            return 0.0
        if self.t < 330:
            return 0.25 * (self.t - 120)                       # 초당 0.25 ℃
        peak = 0.25 * 210
        return peak * math.exp(-(self.t - 330) / 60.0)          # 충전 차단 뒤 식음

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


def make_bus(scen: Scenario, amg=0x69, sht=0x44, ads=0x48, divider=1.5) -> FakeBus:
    bus = FakeBus()
    bus.attach(amg, FakeAMG8833(scen))
    bus.attach(sht, FakeSHT31(scen))
    bus.attach(ads, FakeADS1115(scen, divider))
    return bus
