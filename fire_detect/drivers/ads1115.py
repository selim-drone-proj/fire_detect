"""
ads1115.py - TI ADS1115 16비트 ADC (주소 0x48, ADDR=GND). MQ-2 연기 센서 아날로그 출력 읽기

Pi 에서는 ADS1115 를 3.3 V 로 켠다 (입력이 VDD + 0.3 V 를 넘으면 안 됨).
MQ-2 모듈 AO 는 5 V 까지 나오므로 10 kΩ / 20 kΩ 분압으로 2/3 로 낮춰 A0 에 넣는다.
소프트웨어에서 divider = 1.5 를 곱해 실제 AO 전압으로 되돌린다.

한 번 변환 (single-shot):
  설정 레지스터 0x01 <- OS=1 | MUX(AINx-GND) | PGA ±4.096 V | MODE=1 | 128 SPS | 비교기 끔
  8 ms 뒤 변환 레지스터 0x00 (16비트 2의 보수) 읽기, 1 LSB = 4.096 / 32768 V = 125 µV
"""
from __future__ import annotations

import time

from .i2c_bus import I2CBus

ADDR = 0x48
PGA = {6.144: 0b000, 4.096: 0b001, 2.048: 0b010, 1.024: 0b011, 0.512: 0b100, 0.256: 0b101}


def config_word(channel: int, fs: float = 4.096) -> int:
    """단일 입력 AINchannel - GND, 1 회 변환, 128 SPS, 비교기 끔"""
    if not 0 <= channel <= 3:
        raise ValueError("ADS1115 채널은 0~3")
    mux = 0b100 + channel
    return (1 << 15) | (mux << 12) | (PGA[fs] << 9) | (1 << 8) | (0b100 << 5) | 0b11


class ADS1115:
    def __init__(self, bus: I2CBus, addr: int = ADDR, fs: float = 4.096, sleep=time.sleep):
        self.bus = bus
        self.addr = addr
        self.fs = fs
        self.sleep = sleep

    def begin(self) -> str:
        self.read_volts(0)
        return "ADS1115"

    def read_raw(self, channel: int) -> int:
        cfg = config_word(channel, self.fs)
        self.bus.write(self.addr, bytes([0x01, cfg >> 8, cfg & 0xFF]))
        self.sleep(0.009)
        for _ in range(5):                       # 변환 끝(OS 비트 1)까지 조금 더 기다린다
            hi, lo = self.bus.write_read(self.addr, b"\x01", 2)
            if hi & 0x80:
                break
            self.sleep(0.002)
        else:
            raise IOError("ADS1115 변환 시간 초과")
        hi, lo = self.bus.write_read(self.addr, b"\x00", 2)
        raw = (hi << 8) | lo
        return raw - 0x10000 if raw & 0x8000 else raw

    def read_volts(self, channel: int) -> float:
        return self.read_raw(channel) * self.fs / 32768.0
