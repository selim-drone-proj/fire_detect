"""화재 감지기 드라이버: 레지스터 형식 변환을 데이터시트 값으로 확인"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fire_detect.drivers import ads1115, amg8833  # noqa: E402
from fire_detect.drivers.i2c_bus import FakeBus  # noqa: E402
from fire_detect.drivers.sensirion import CrcError  # noqa: E402
from fire_detect.drivers.sht31 import SHT31  # noqa: E402
from fire_detect.simulate import FakeADS1115, FakeAMG8833, FakeSHT31, Scenario  # noqa: E402


def no_sleep(_):
    pass


def test_amg8833_pixel_format():
    # 데이터시트: 12비트 2의 보수, 0.25 ℃/LSB. 0x0FFF = -0.25 ℃, 0x0001 = +0.25 ℃, 0x01F4 = +125 ℃
    assert amg8833.pixel_c(0x01, 0x00) == 0.25
    assert amg8833.pixel_c(0xFF, 0x0F) == -0.25
    assert amg8833.pixel_c(0xF4, 0x01) == 125.0
    assert amg8833.pixel_c(0x64, 0x00) == 25.0


def test_amg8833_thermistor_sign_magnitude():
    # 데이터시트: 부호 + 크기 형식, 0.0625 ℃/LSB. 0x190 = +25 ℃, 0x801 = -0.0625 ℃
    assert amg8833.thermistor_c(0x90, 0x01) == 25.0
    assert amg8833.thermistor_c(0x01, 0x08) == -0.0625


def test_amg8833_reads_frame():
    scen = Scenario("normal")
    bus = FakeBus()
    bus.attach(0x69, FakeAMG8833(scen))
    cam = amg8833.AMG8833(bus, sleep=no_sleep)
    assert cam.begin() == "AMG8833"
    px = cam.read_pixels()
    assert len(px) == 64 and 23 < min(px) and max(px) < 29
    assert all(p * 4 == int(p * 4) for p in px)                  # 0.25 ℃ 단위


def test_sht31_conversion_and_crc():
    scen = Scenario("normal")
    bus = FakeBus()
    dev = bus.attach(0x44, FakeSHT31(scen))
    sht = SHT31(bus, sleep=no_sleep)
    assert sht.begin() == "SHT31"
    t, rh = sht.read()
    assert t == pytest.approx(24.0, abs=0.3) and rh == pytest.approx(45.0, abs=1.5)
    orig = dev.on_read
    dev.on_read = lambda n: bytes([orig(n)[0] ^ 1]) + orig(n)[1:]
    with pytest.raises(CrcError):
        sht.read()


def test_ads1115_config_word_and_volts():
    assert ads1115.config_word(0) == 0xC383        # A0-GND, ±4.096 V, 1 회, 128 SPS, 비교기 끔
    assert ads1115.config_word(3, 2.048) == 0xF583
    with pytest.raises(ValueError):
        ads1115.config_word(4)
    scen = Scenario("normal")
    bus = FakeBus()
    bus.attach(0x48, FakeADS1115(scen, divider=1.5))
    adc = ads1115.ADS1115(bus, sleep=no_sleep)
    assert adc.read_volts(0) * 1.5 == pytest.approx(0.80, abs=0.02)   # 분압 보정 후 MQ-2 AO 전압
    writes = [x for x in bus.log if x[0] == "w" and len(x[2]) == 3]
    assert writes[0][2] == bytes([0x01, 0xC3, 0x83])


def test_negative_adc_value():
    bus = FakeBus()

    class Dev(FakeADS1115):
        def on_read(self, n):
            return bytes([0x80, 0x00]) if self.reg == 0x01 else bytes([0xFF, 0xFE])
    bus.attach(0x48, Dev(Scenario("normal")))
    assert ads1115.ADS1115(bus, sleep=no_sleep).read_raw(0) == -2
