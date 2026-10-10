"""
mlx90614.py - Melexis MLX90614 적외선 온도계 (GY-906 모듈) SMBus 드라이버 (주소 0x5A)

  RAM 0x06  Ta     센서 자체 온도 (기록만)
  RAM 0x07  Tobj1  물체 온도 = 화각 안의 평균
  읽기: 명령 1 B 를 쓰고 repeated start 로 3 B (하위, 상위, PEC)
  T = raw x 0.02 K - 273.15 ℃.  상위 비트(bit15)가 1 이면 센서가 오류값을 보낸 것
  PEC: CRC-8 (다항식 0x07, 초기값 0) 을 [주소<<1, 명령, (주소<<1)|1, 하위, 상위] 에 대해 계산. 틀리면 CrcError

주의
  - SMBus 최대 100 kHz. /boot/firmware/config.txt 의 i2c_arm_baudrate 를 올리지 말 것 (기본 100000)
  - 방사율은 공장값(1.0) 그대로 쓴다. EEPROM 은 쓰지 않는다 (잘못 쓰면 보정값이 망가짐).
    광택 있는 면은 낮게 읽히므로 재는 자리에 무광 테이프(마스킹 테이프)를 붙여 둔다.
  - GY-906-BAA 는 화각이 약 90° 라 멀리 두면 배경까지 평균한다. 감시할 면에서 3~5 cm 에 둔다.
"""
from __future__ import annotations

from .i2c_bus import I2CBus
from .sensirion import CrcError

ADDR = 0x5A
RAM_TA, RAM_TOBJ1 = 0x06, 0x07


def crc8_smbus(data: bytes) -> int:
    """SMBus PEC: 다항식 0x07, 초기값 0, 반사 없음. 확인값 crc8_smbus(b"123456789") == 0xF4"""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def raw_to_c(raw: int) -> float:
    return raw * 0.02 - 273.15


class MLX90614:
    def __init__(self, bus: I2CBus, addr: int = ADDR):
        self.bus = bus
        self.addr = addr

    def read_word(self, cmd: int) -> int:
        lo, hi, pec = self.bus.write_read(self.addr, bytes([cmd]), 3)
        want = crc8_smbus(bytes([self.addr << 1, cmd, (self.addr << 1) | 1, lo, hi]))
        if pec != want:
            raise CrcError(f"MLX90614 PEC 불일치 (명령 0x{cmd:02x}: {lo:02x} {hi:02x} pec {pec:02x}, 계산 {want:02x})")
        word = (hi << 8) | lo
        if word & 0x8000:
            raise IOError(f"MLX90614 오류값 (명령 0x{cmd:02x}: 0x{word:04x})")
        return word

    def read_ambient_c(self) -> float:
        return raw_to_c(self.read_word(RAM_TA))

    def read_object_c(self) -> float:
        return raw_to_c(self.read_word(RAM_TOBJ1))

    def begin(self) -> str:
        ta = self.read_ambient_c()
        if not -40.0 < ta < 125.0:
            raise IOError(f"MLX90614 센서 온도가 이상함: {ta:.2f} ℃")
        self.read()
        return "MLX90614"

    def read(self) -> tuple[float, float]:
        """-> (물체 ℃, 센서 자체 ℃)"""
        obj = self.read_object_c()
        if not -70.0 <= obj <= 380.0:                    # 데이터시트 측정 범위 밖이면 버림
            raise IOError(f"MLX90614 물체 온도가 범위 밖: {obj:.2f} ℃")
        return obj, self.read_ambient_c()
