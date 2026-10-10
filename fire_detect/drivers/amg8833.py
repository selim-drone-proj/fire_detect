"""
amg8833.py - Panasonic Grid-EYE AMG8833 8x8 열화상 I2C 드라이버 (주소 0x69, AD_SELECT=VDD / 0x68)

레지스터
  0x00 PCTL   0x00 = 정상 동작
  0x01 RST    0x3F = 초기 리셋
  0x02 FPSC   0x00 = 10 fps, 0x01 = 1 fps
  0x03 INTC   0x00 = 인터럽트 끔
  0x0E,0x0F   서미스터(보드 온도) 12비트 "부호 + 크기" 형식, 0.0625 ℃/LSB
  0x80~0xFF   화소 64 개 x 2 B (하위 먼저), 12비트 2의 보수, 0.25 ℃/LSB

화소 순서는 0x80 부터 행 우선. 0 번이 어느 모서리인지는 카메라를 단 방향에 따라 다르다.
정확도는 ±2.5 ℃ 라서 절대값보다 "주변보다 몇 도 높은가" 로 판정한다 (alarm.py).
"""
from __future__ import annotations

import time

from .i2c_bus import I2CBus

ADDR = 0x69
REG_PCTL, REG_RST, REG_FPSC, REG_INTC, REG_TTHL, REG_PIXEL = 0x00, 0x01, 0x02, 0x03, 0x0E, 0x80


def pixel_c(lo: int, hi: int) -> float:
    raw = ((hi & 0x0F) << 8) | lo
    if raw & 0x800:
        raw -= 0x1000
    return raw * 0.25


def thermistor_c(lo: int, hi: int) -> float:
    raw = ((hi & 0x0F) << 8) | lo
    mag = raw & 0x7FF
    return -mag * 0.0625 if raw & 0x800 else mag * 0.0625


class AMG8833:
    def __init__(self, bus: I2CBus, addr: int = ADDR, sleep=time.sleep):
        self.bus = bus
        self.addr = addr
        self.sleep = sleep

    def begin(self) -> str:
        self.bus.write(self.addr, bytes([REG_PCTL, 0x00]))
        self.bus.write(self.addr, bytes([REG_RST, 0x3F]))
        self.sleep(0.05)
        self.bus.write(self.addr, bytes([REG_INTC, 0x00]))
        self.bus.write(self.addr, bytes([REG_FPSC, 0x00]))      # 10 fps (1 초에 한 번 읽어도 최신 프레임)
        self.sleep(0.12)
        t = self.read_thermistor_c()
        if not -20.0 < t < 80.0:
            raise IOError(f"AMG8833 보드 온도가 이상함: {t} ℃")
        return "AMG8833"

    def read_thermistor_c(self) -> float:
        lo, hi = self.bus.write_read(self.addr, bytes([REG_TTHL]), 2)
        return thermistor_c(lo, hi)

    def read_pixels(self) -> list[float]:
        raw = self.bus.write_read(self.addr, bytes([REG_PIXEL]), 128)
        if len(raw) != 128:
            raise IOError(f"AMG8833 화소 길이 {len(raw)}")
        px = [pixel_c(raw[2 * i], raw[2 * i + 1]) for i in range(64)]
        if all(p == 0.0 for p in px):
            raise IOError("AMG8833 화소가 모두 0 (리셋 직후이거나 배선 불량)")
        return px
