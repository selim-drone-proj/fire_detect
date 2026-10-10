"""
i2c_bus.py - I2C 버스 한 겹 감싸기 (공통 파일: moving-ver odor_drone, fire_detect 에 같은 내용)

센서 드라이버는 이 파일의 세 함수(write, read, write_read)만 쓴다.
  - 실제 장비(Pi5): SMBus2Bus(1)  -> /dev/i2c-1 (40핀 헤더 3번 SDA, 5번 SCL)
  - 테스트, PC:      FakeBus()     -> 가짜 장치(FakeDevice)를 주소에 붙여서 흉내

pimoroni bme680 라이브러리는 smbus 식 함수(read_byte_data 등)를 부르므로
그것도 같은 세 함수로 바꿔서 제공한다. 그래서 TCA9548A 채널 전환이 모든 센서에 똑같이 적용된다.
"""
from __future__ import annotations


class I2CBus:
    """드라이버가 기대하는 최소 기능. 실제 구현은 SMBus2Bus, FakeBus"""

    def write(self, addr: int, data: bytes) -> None:
        raise NotImplementedError

    def read(self, addr: int, n: int) -> bytes:
        raise NotImplementedError

    def write_read(self, addr: int, data: bytes, n: int) -> bytes:
        """data 를 쓰고 STOP 없이(repeated start) n 바이트 읽기 = 레지스터 읽기"""
        raise NotImplementedError

    # ---- smbus 호환 (pimoroni bme680 이 부른다) ----
    def read_byte_data(self, addr: int, reg: int) -> int:
        return self.write_read(addr, bytes([reg]), 1)[0]

    def write_byte_data(self, addr: int, reg: int, value: int) -> None:
        self.write(addr, bytes([reg, value & 0xFF]))

    def read_i2c_block_data(self, addr: int, reg: int, n: int) -> list[int]:
        return list(self.write_read(addr, bytes([reg]), n))

    def write_i2c_block_data(self, addr: int, reg: int, data) -> None:
        self.write(addr, bytes([reg]) + bytes(data))

    def close(self) -> None:
        pass


class SMBus2Bus(I2CBus):
    """Pi 의 /dev/i2c-N. smbus2 의 i2c_rdwr 로 한 번에 보내므로 길이 제한(32 B)이 없다."""

    def __init__(self, bus_no: int = 1):
        from smbus2 import SMBus, i2c_msg  # Pi 에서만 필요
        self._msg = i2c_msg
        self.bus = SMBus(bus_no)
        self.bus_no = bus_no

    def write(self, addr, data):
        self.bus.i2c_rdwr(self._msg.write(addr, list(data)))

    def read(self, addr, n):
        r = self._msg.read(addr, n)
        self.bus.i2c_rdwr(r)
        return bytes(list(r))

    def write_read(self, addr, data, n):
        w = self._msg.write(addr, list(data))
        r = self._msg.read(addr, n)
        self.bus.i2c_rdwr(w, r)
        return bytes(list(r))

    def close(self):
        self.bus.close()


# ------------------------------------------------------------------ 테스트용
class FakeDevice:
    """FakeBus 에 붙이는 가짜 I2C 장치. 필요한 것만 덮어쓴다."""

    def on_write(self, data: bytes) -> None:
        pass

    def on_read(self, n: int) -> bytes:
        return bytes(n)


class FakeBus(I2CBus):
    """주소 -> FakeDevice. 없는 주소에 접근하면 실제 버스처럼 OSError(NACK)."""

    def __init__(self):
        self.devices: dict[int, FakeDevice] = {}
        self.log: list[tuple[str, int, bytes]] = []

    def attach(self, addr: int, dev: FakeDevice) -> FakeDevice:
        self.devices[addr] = dev
        return dev

    def _dev(self, addr: int) -> FakeDevice:
        dev = self.devices.get(addr)
        if dev is None:
            raise OSError(121, f"Remote I/O error (0x{addr:02x} 응답 없음)")
        return dev

    def write(self, addr, data):
        data = bytes(data)
        self.log.append(("w", addr, data))
        self._dev(addr).on_write(data)

    def read(self, addr, n):
        out = bytes(self._dev(addr).on_read(n))
        self.log.append(("r", addr, out))
        return out

    def write_read(self, addr, data, n):
        self.write(addr, data)
        return self.read(addr, n)
