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


# ------------------------------------------------------------------ MLX90614 (적외선)
from fire_detect.drivers import ds18b20, mlx90614  # noqa: E402
from fire_detect.drivers.i2c_bus import FakeDevice  # noqa: E402
from fire_detect.simulate import FakeMLX90614, FakeW1, w1_slave_text  # noqa: E402


def test_mlx90614_pec_matches_datasheet_example():
    assert mlx90614.crc8_smbus(b"123456789") == 0xF4                       # CRC-8/SMBUS 확인값
    # 데이터시트 예: 주소 0x5A, Tobj1(0x07) = 0x3AD2 -> PEC 0x30, 301.16 K = 28.01 ℃
    assert mlx90614.crc8_smbus(bytes([0xB4, 0x07, 0xB5, 0xD2, 0x3A])) == 0x30
    assert mlx90614.raw_to_c(0x3AD2) == pytest.approx(28.01, abs=1e-9)


def _mlx_with(answer: bytes):
    bus = FakeBus()

    class Dev(FakeDevice):
        def on_read(self, n):
            return answer[:n]
    bus.attach(0x5A, Dev())
    return mlx90614.MLX90614(bus)


def test_mlx90614_read_checks_pec_and_error_flag():
    assert _mlx_with(bytes([0xD2, 0x3A, 0x30])).read_object_c() == pytest.approx(28.01)
    with pytest.raises(CrcError):
        _mlx_with(bytes([0xD2, 0x3A, 0x31])).read_object_c()                # PEC 한 비트 틀림
    err = bytes([0xFF, 0xFF, mlx90614.crc8_smbus(bytes([0xB4, 0x07, 0xB5, 0xFF, 0xFF]))])
    with pytest.raises(IOError):
        _mlx_with(err).read_object_c()                                      # bit15 = 센서 오류값


def test_mlx90614_reads_fake_device():
    scen = Scenario("normal")
    bus = FakeBus()
    bus.attach(0x5A, FakeMLX90614(scen))
    ir = mlx90614.MLX90614(bus)
    assert ir.begin() == "MLX90614"
    obj, die = ir.read()
    assert obj == pytest.approx(26.5, abs=0.5) and die == pytest.approx(25.0, abs=0.2)
    assert bus.log[-2] == ("w", 0x5A, b"\x06") and len(bus.log[-1][2]) == 3     # repeated start 로 3 B


# ------------------------------------------------------------------ DS18B20 (접촉 프로브)
SAMPLE = "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"


def test_ds18b20_parse_w1_slave():
    assert ds18b20.crc8_maxim(b"123456789") == 0xA1                         # CRC-8/MAXIM 확인값
    assert ds18b20.parse_w1_slave(SAMPLE) == 23.125
    assert ds18b20.parse_w1_slave(w1_slave_text(-10.125)) == -10.125         # 영하 (2의 보수)
    for bad in (SAMPLE.replace("YES", "NO"),                                 # 커널이 CRC 실패라고 함
                SAMPLE.replace("72 01 4b", "73 01 4b", 1),                   # 바이트가 깨졌는데 YES
                "00 00 00 00 00 00 00 00 00 : crc=00 YES\n00 00 00 00 00 00 00 00 00 t=0\n",   # DQ 가 GND
                "", "garbage\n"):
        with pytest.raises(IOError):
            ds18b20.parse_w1_slave(bad)


class ScriptedW1:
    """프로브별로 정해 둔 값을 차례로 돌려주는 가짜 1-Wire (None = 읽기 오류)"""

    def __init__(self, values: dict):
        self.values = {k: list(v) for k, v in values.items()}

    def ids(self):
        return sorted(self.values)

    def read_slave(self, rid):
        if rid not in self.values:
            raise FileNotFoundError(rid)
        seq = self.values[rid]
        v = seq.pop(0) if len(seq) > 1 else seq[0]
        if v is None:
            raise OSError(5, "Input/output error")
        return w1_slave_text(v)


A, B, C = "28-0000000000a1", "28-0000000000b2", "28-0000000000c3"


def test_ds18b20_power_on_85_is_rejected_unless_already_hot():
    g = ds18b20.ProbeGroup(ScriptedW1({A: [85.0, 30.0, 85.0, 80.0, 85.0]}), count=1)
    g.begin()
    with pytest.raises(IOError):
        g.read()                                  # 처음부터 85 ℃ = 초기값 -> 실패 (하나뿐이라 전체 실패)
    assert g.read() == [30.0]
    with pytest.raises(IOError):
        g.read()                                  # 30 ℃ 다음 85 ℃ -> 초기값
    assert g.read() == [80.0]
    assert g.read() == [85.0]                     # 80 ℃ 다음 85 ℃ 는 진짜로 받아들임


def test_ds18b20_discovery_count_and_partial():
    g = ds18b20.ProbeGroup(ScriptedW1({A: [25.0], B: [26.0]}), count=3)
    info = g.begin()
    assert "2/3" in info and "모자람" in info
    assert g.read() == [25.0, 26.0, None]
    assert "프로브3 안 보임" in g.problem([25.0, 26.0, None])
    w1 = ScriptedW1({A: [25.0], B: [26.0], C: [27.0]})
    g = ds18b20.ProbeGroup(w1, ids=[C, A], count=3)          # ID 를 적으면 그 순서, 개수는 ID 수
    assert g.count == 2 and g.begin() and g.read() == [27.0, 25.0]
    del w1.values[C]
    assert g.read() == [None, 25.0] and C in g.errors        # 사라진 프로브만 None
    with pytest.raises(IOError):
        ds18b20.ProbeGroup(ScriptedW1({A: [25.0]}), ids=[B]).begin()      # 적은 ID 가 하나도 없음
    with pytest.raises(IOError):
        ds18b20.ProbeGroup(ScriptedW1({}), count=3).begin()               # 버스에 아무것도 없음
    with pytest.raises(ValueError):
        ds18b20.ProbeGroup(ScriptedW1({}), ids=["28-xyz"])                 # ID 오타


def test_ds18b20_threaded_reader_keeps_latest_and_expires():
    import time as _t
    w1 = ScriptedW1({A: [25.0], B: [26.0]})
    g = ds18b20.ProbeGroup(w1, count=2, threaded=True, period_s=0.01, max_age_s=0.3)
    g.begin()
    try:
        assert g.read() in ([None, None], [25.0, None], [None, 26.0], [25.0, 26.0])   # 막 시작: 실패로 안 셈
        deadline = _t.monotonic() + 3.0
        while g.read() != [25.0, 26.0] and _t.monotonic() < deadline:
            _t.sleep(0.01)
        assert g.read() == [25.0, 26.0]
        w1.values[B] = [None]                                 # 프로브 2 가 계속 실패 -> max_age 뒤 None
        deadline = _t.monotonic() + 3.0
        while g.read()[1] is not None and _t.monotonic() < deadline:
            _t.sleep(0.02)
        assert g.read() == [25.0, None] and B in g.errors
    finally:
        g.close()
    assert not g._thread.is_alive()


def test_fake_w1_matches_kernel_format():
    scen = Scenario("normal")
    w1 = FakeW1(scen)
    assert w1.ids() == list(FakeW1.IDS)
    v = ds18b20.parse_w1_slave(w1.read_slave(FakeW1.IDS[0]))
    assert v == pytest.approx(27.0, abs=0.3) and v * 16 == int(v * 16)    # 1/16 ℃ 단위
