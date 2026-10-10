"""
sht31.py - Sensirion SHT31 온습도 I2C 드라이버 (주소 0x44, ADDR 핀 High 면 0x45)

  0x2400  1 회 측정, 높은 반복성, clock stretching 끔. 15 ms 뒤 6 B (T, CRC, RH, CRC)
  0x30A2  소프트 리셋
  0x3066  내장 히터 끔
  T = -45 + 175 * raw / 65535 ℃,  RH = 100 * raw / 65535 %
"""
from __future__ import annotations

import time

from .i2c_bus import I2CBus
from .sensirion import unpack_words

ADDR = 0x44


class SHT31:
    def __init__(self, bus: I2CBus, addr: int = ADDR, sleep=time.sleep):
        self.bus = bus
        self.addr = addr
        self.sleep = sleep

    def _cmd(self, cmd: int) -> None:
        self.bus.write(self.addr, bytes([cmd >> 8, cmd & 0xFF]))

    def begin(self) -> str:
        self._cmd(0x30A2)
        self.sleep(0.002)
        self._cmd(0x3066)
        self.read()
        return "SHT31"

    def read(self) -> tuple[float, float]:
        """-> (온도 ℃, 상대습도 %)"""
        self._cmd(0x2400)
        self.sleep(0.016)
        t_raw, rh_raw = unpack_words(self.bus.read(self.addr, 6))
        return -45.0 + 175.0 * t_raw / 65535.0, min(100.0, 100.0 * rh_raw / 65535.0)
