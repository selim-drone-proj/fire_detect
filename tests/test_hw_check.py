"""tools/hw_check.py 를 가짜 하드웨어로 시험한다."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hw_check", ROOT / "tools" / "hw_check.py")
hw = importlib.util.module_from_spec(spec)
sys.modules["hw_check"] = hw
spec.loader.exec_module(hw)

NO_SLEEP = lambda s: None  # noqa: E731


def test_i2c_and_sensors_pass_on_fake(capsys):
    assert hw.main(["all", "--fake", "--n", "3"], sleep=NO_SLEEP) == 0
    out = capsys.readouterr().out
    assert "AMG8833 열화상" in out and "SHT31" in out and "MQ-2" in out
    assert "실패" not in out.split("결과:")[0].replace("실패가 있음", "")


def test_missing_sensor_fails(capsys):
    cfg = hw.load(None)
    bus = hw.open_bus(cfg, fake=True)
    bus.devices.pop(cfg.sensors.sht31_address)            # SHT31 을 뺀 버스
    assert hw.check_i2c(cfg, bus) is False
    assert hw.check_sensors(cfg, bus, 2, sleep=NO_SLEEP) is False


def test_outputs_need_ac_confirmation():
    log = []
    answers = iter(["아니요"])
    ok = hw.check_outputs(hw.load(None), fake=True, assume_yes=False, ask=lambda q: next(answers),
                          sleep=NO_SLEEP, log=log)
    assert ok is False and log == []                       # 확인이 없으면 아무것도 켜지 않음


def test_outputs_each_once_and_all_off():
    log = []
    answers = iter(["AC 분리", ""] + ["y"] * 6)
    ok = hw.check_outputs(hw.load(None), fake=True, assume_yes=False, ask=lambda q: next(answers),
                          sleep=NO_SLEEP, log=log)
    assert ok is True
    turned_on = [n for n, s in log if s == "on"]
    assert turned_on == ["green", "yellow", "red", "buzzer", "dc", "ssr"]   # 위험이 적은 것부터, 한 번씩
    assert turned_on[-1] == "ssr"
    last = {}
    for n, s in log:
        last[n] = s
    assert all(v == "off" for v in last.values())           # 끝나면 모두 꺼짐


def test_outputs_off_even_after_error():
    log = []

    def ask(q):
        if "녹색" in q:
            raise KeyboardInterrupt
        return "AC 분리" if "입력" in q else ""

    with pytest.raises(KeyboardInterrupt):
        hw.check_outputs(hw.load(None), fake=True, assume_yes=False, ask=ask, sleep=NO_SLEEP, log=log)
    assert ("green", "off") in log                         # 중간에 끊겨도 끔


def test_yes_requires_fake():
    assert hw.main(["outputs", "--yes"]) == 2
