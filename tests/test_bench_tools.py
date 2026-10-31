"""보조배터리 벤치 구성 (config.battery.yaml) 과 기록 보기 도구 (tools/live_view.py, tools/plot_log.py)"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from fire_detect.app import main as fire_main
from fire_detect.config import load

ROOT = Path(__file__).resolve().parents[1]
BATTERY = str(ROOT / "config.battery.yaml")


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_battery_config_has_no_outputs_and_three_sensors():
    cfg = load(BATTERY)
    p = cfg.pins
    assert [p.ssr, p.dc_relay, p.buzzer, p.led_red, p.led_yellow, p.led_green, p.reset_button] == [-1] * 7
    assert cfg.sensors.mlx90614_address == -1 and cfg.sensors.ds18b20_count == 0
    assert cfg.latch_file == ""
    assert not cfg.display.enabled


@pytest.fixture(scope="module")
def sim_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim")
    fire_main(["--config", BATTERY, "--simulate", "overheat", "--speed", "0", "--duration", "400",
               "--out", str(d), "--quiet"])
    return d


def test_battery_config_runs_and_logs(sim_dir):
    assert list(sim_dir.glob("fire_*.csv")) and list(sim_dir.glob("thermal_*.csv"))
    assert not list(sim_dir.glob("probe*"))


def test_live_view_once(sim_dir, capsys):
    lv = tool("live_view")
    assert lv.main(["--dir", str(sim_dir), "--once", "--grid"]) == 0
    out = capsys.readouterr().out
    assert "주변" in out and "열화상 최고" in out and "*" in out
    assert len([ln for ln in out.splitlines() if ln.count(".") >= 8]) == 8   # 8x8 줄


def test_live_view_empty_dir(tmp_path, capsys):
    assert tool("live_view").main(["--dir", str(tmp_path), "--once"]) == 1


def test_plot_log(sim_dir, tmp_path, capsys):
    pytest.importorskip("matplotlib")
    pl = tool("plot_log")
    assert pl.main(["--dir", str(sim_dir), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "단계별" in out and "위험" in out
    assert len(list(tmp_path.glob("fire_*.png"))) == 1 and len(list(tmp_path.glob("thermal_*.png"))) == 1
    assert pl.main(["--dir", str(sim_dir), "--out", str(tmp_path), "--last", "1"]) == 0
    assert list(tmp_path.glob("*_last1m.png"))


def test_hw_check_outputs_skips_without_pins(capsys):
    hw = tool("hw_check")
    asked = []
    assert hw.main(["outputs", "--fake", "--config", BATTERY], ask=lambda q: asked.append(q) or "") == 0
    assert not asked and "건너뜁니다" in capsys.readouterr().out


def test_mq2_check_fake_run(tmp_path, capsys):
    mq = tool("mq2_check")
    assert mq.main(["--fake", "--minutes", "4", "--speed", "0", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "채널 한 번씩" in out and "예열 중" in out and "안정" in out
    rows = list(csv.DictReader(open(next(tmp_path.glob("mq2_*.csv")), encoding="utf-8")))
    assert len(rows) == 240 and abs(float(rows[-1]["ao_v"]) - 0.80) < 0.05


def test_mq2_check_diagnose_and_status():
    mq = tool("mq2_check")
    assert "분압" in mq.diagnose(3.30, 4.95)
    assert "전원" in mq.diagnose(0.0, 0.0)
    assert mq.diagnose(0.53, 0.80) == ""
    assert mq.status(10, 2.0, None, None) == "예열 중"
    assert mq.status(300, 1.2, 0.8, 0.0) == "올라감"
    assert mq.status(300, 0.8, 0.8, -20.0) == "내려가는 중"
    assert mq.status(300, 0.8, 0.8, 2.0) == "안정"
    assert abs(mq.slope_mv_per_min([(0, 1.0), (60, 1.01)]) - 10.0) < 1e-6
