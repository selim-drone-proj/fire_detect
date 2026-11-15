"""앱 전체: 가짜 센서 시나리오 -> 판정 -> 출력 -> 기록 -> 스키마 검증"""
import csv
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fire_detect import app as fa  # noqa: E402
from fire_detect.config import load  # noqa: E402

SCHEMA_DIR = Path(os.environ.get("ODOR_SCHEMAS", ROOT.parent / "moving-ver" / "interfaces" / "schemas"))


@pytest.fixture(scope="module")
def validate():
    tools = SCHEMA_DIR.parents[1] / "tools"
    if not (tools / "validate_jsonl.py").exists():
        pytest.skip("moving-ver 스키마가 옆에 없음 (ODOR_SCHEMAS 지정)")
    sys.path.insert(0, str(tools))
    import validate_jsonl
    return lambda rec: validate_jsonl.errors(rec, SCHEMA_DIR)


def simulate(tmp_path, scenario, duration, reset_at=None):
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    app, scen = fa.build(cfg, scenario, str(tmp_path), ros=False, log=lambda m: None)
    fa.run(app, scen, 1.0, duration, 0, reset_at)
    return app


START_HOLD = 10                                                # 켠 직후 충전 차단 (alarm.start_hold_s)


def transitions(tmp_path, skip=START_HOLD):
    """판정 CSV 에서 (줄, 단계, 래치, 충전 허용) 이 바뀌는 곳. 켠 직후 차단 구간은 건너뜀"""
    rows = list(csv.DictReader(open(next(tmp_path.glob("fire_*.csv")), encoding="utf-8")))
    assert all(r["charge_allowed"] == "0" for r in rows[:skip]) and rows[skip]["charge_allowed"] == "1"
    out, prev = [], None
    for i, r in enumerate(rows[skip:], start=skip):
        key = (int(r["level"]), r["latched"] == "1", r["charge_allowed"] == "1")
        if key != prev:
            out.append((i, *key))
            prev = key
    return out


def test_overheat_scenario(tmp_path, validate):
    app = simulate(tmp_path, "overheat", 600, reset_at=560)
    tr = transitions(tmp_path)
    levels = [x[1] for x in tr]
    assert levels == [0, 1, 2, 3, 0], tr
    t_danger = next(x for x in tr if x[1] == 3)
    assert 250 <= t_danger[0] <= 260 and t_danger[2] and not t_danger[3]          # 60 ℃ 도달 직후 차단
    assert tr[-1][0] == 560 and tr[-1][3]                                        # 해제 버튼 뒤 충전 재개
    # 출력: 위험 단계에서 적색 상시 + 부저 연속 + SSR 차단
    danger_out = next(h for h in app.outputs.history if h["red"] == "on")
    assert dict(red="on", buzzer="on", ssr="off", dc="off").items() <= danger_out.items()
    assert app.outputs.history[0]["ssr"] == "off" and app.outputs.history[1]["ssr"] == "on"   # 켠 직후 차단 뒤 허용
    assert app.outputs.state["ssr"] == "off"                                     # 종료하면 안전 쪽(차단)
    recs = [json.loads(x) for x in next(tmp_path.glob("fire_*.jsonl")).read_text().splitlines()]
    assert {r["type"] for r in recs} == {"fire_status", "device_health"}
    for r in recs:
        assert validate(r) == [], r
    danger = next(r for r in recs if r["type"] == "fire_status" and r["level"] == 3)
    assert danger["flags"] & 2048 and danger["latched"] and danger["charge_allowed"] is False
    assert len(danger["thermal_c"]) == 64


def test_sensor_loss_scenario(tmp_path, validate):
    simulate(tmp_path, "sensor_loss", 200)
    rows = list(csv.DictReader(open(next(tmp_path.glob("fire_*.csv")), encoding="utf-8")))
    cut = [i for i, r in enumerate(rows) if r["charge_allowed"] == "0" and i >= START_HOLD]
    # 60 초부터 끊김 -> 마지막으로 읽은 59 초 + 10 초 = 69 초에 차단, 120 초에 복구되면 바로 허용
    assert cut[0] == 69 and cut[-1] == 119 and rows[-1]["charge_allowed"] == "1"
    health = [json.loads(x) for x in next(tmp_path.glob("fire_*.jsonl")).read_text().splitlines()
              if '"device_health"' in x]
    assert any(h["state"] == fa.STATE_ERROR for h in health)
    for h in health:
        assert validate(h) == []


def test_reset_cli_writes_request(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(f"reset_file: {tmp_path / 'r' / 'reset'}\n", encoding="utf-8")
    assert fa.main(["--config", str(p), "--reset"]) == 0
    assert (tmp_path / "r" / "reset").exists()


def test_example_config_loads():
    cfg = load(str(ROOT / "config.example.yaml"))
    assert cfg.device_id == "ess_01" and cfg.sensors.amg8833_address == 0x69 and cfg.alarm.delta_c > 0


def test_logger_cleanup_keeps_recent(tmp_path):
    from fire_detect.logger import FireLogger
    for d in ("20260101", "20261001", "20261009"):
        (tmp_path / f"fire_{d}.csv").write_text("x")
    lg = FireLogger(tmp_path, "ess_01", keep_days=30)
    removed = lg.cleanup(1791590400.0)                       # 2026-10-09
    assert removed == ["fire_20260101.csv"]


def test_systemd_notify(tmp_path, monkeypatch):
    import socket
    sock_path = str(tmp_path / "notify.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(sock_path)
    srv.settimeout(1.0)
    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    simulate(tmp_path, "normal", 3)
    got = []
    try:
        while True:
            got.append(srv.recv(64).decode())
    except socket.timeout:
        pass
    srv.close()
    assert got[0] == "READY=1" and got.count("WATCHDOG=1") == 3 and got[-1] == "STOPPING=1"


def test_hidden_heat_scenario_contact_probe_cuts(tmp_path, validate):
    """열화상에 안 보이는 뒷면 발열을 접촉 프로브가 잡아 충전을 끊는다"""
    app = simulate(tmp_path, "hidden_heat", 600, reset_at=560)
    tr = transitions(tmp_path)
    assert [x[1] for x in tr] == [0, 1, 3, 0], tr
    t_danger = next(x for x in tr if x[1] == 3)
    assert 250 <= t_danger[0] <= 260 and t_danger[2] and not t_danger[3]
    assert tr[-1][0] == 560 and tr[-1][3]
    rows = list(csv.DictReader(open(next(tmp_path.glob("fire_*.csv")), encoding="utf-8")))
    danger = rows[t_danger[0]]
    assert float(danger["max_c"]) < 40 and float(danger["probe3_c"]) >= 60            # 열화상은 평온, 프로브 3 이 잡음
    assert "프로브3" in danger["reason"]
    assert app.outputs.state["ssr"] == "off"
    for r in [json.loads(x) for x in next(tmp_path.glob("fire_*.jsonl")).read_text().splitlines()]:
        assert validate(r) == [], r


def test_csv_has_point_sensor_columns_and_rotates_on_change(tmp_path):
    from fire_detect.alarm import Status
    from fire_detect.logger import FireLogger
    stamp = 1791590400.0                                       # 2026-10-10 00:00 UTC
    old = FireLogger(tmp_path, "ess_01")                       # 예전 형식 (점 센서 열 없음)
    old.write_status(stamp, Status())
    old.close()
    lg = FireLogger(tmp_path, "ess_01", probe_count=3, ir=True)
    lg.write_status(stamp + 1, Status(probe_c=[25.0, float("nan"), 26.5], ir_object_c=27.25))
    lg.close()
    assert (tmp_path / "fire_20261010_1.csv").exists()         # 예전 파일은 옆으로
    rows = list(csv.DictReader(open(tmp_path / "fire_20261010.csv", encoding="utf-8")))
    assert len(rows) == 1 and rows[0]["probe1_c"] == "25.00" and rows[0]["probe2_c"] == "" \
        and rows[0]["ir_c"] == "27.25" and list(rows[0])[-1] == "reason"
    removed = FireLogger(tmp_path, "ess_01", keep_days=1).cleanup(stamp + 5 * 86400)
    assert sorted(removed) == ["fire_20261010.csv", "fire_20261010.jsonl", "fire_20261010_1.csv"]


def test_missing_probe_is_degraded_not_cut(tmp_path):
    from fire_detect.simulate import FakeW1
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    cfg.sensors.ds18b20_ids = list(FakeW1.IDS)                 # 위치를 고정해 둔 설정
    app, scen = fa.build(cfg, "normal", str(tmp_path), ros=False, log=lambda m: None)
    w1 = app.hub.slots["DS18B20"].sensor.w1
    w1.present.remove(w1.IDS[1])                               # 프로브 2 를 뺌
    fa.run(app, scen, 1.0, 200, 0, None)
    health = [json.loads(x) for x in next(tmp_path.glob("fire_*.jsonl")).read_text().splitlines()
              if '"device_health"' in x]
    last = health[-1]
    assert last["state"] == fa.STATE_DEGRADED and not last["sensor_ok_mask"] & 8 and last["sensor_ok_mask"] & 1
    assert "프로브2 안 보임" in last["message"]
    rows = list(csv.DictReader(open(next(tmp_path.glob("fire_*.csv")), encoding="utf-8")))
    assert all(r["charge_allowed"] == "1" for r in rows[START_HOLD:]) and int(rows[-1]["flags"]) & 16


def test_logger_survives_corrupted_file_and_cleans_only_its_own(tmp_path):
    from fire_detect.alarm import Status
    from fire_detect.logger import FireLogger
    stamp = 1791590400.0                                       # 2026-10-10 UTC
    (tmp_path / "fire_20261010.csv").write_bytes(b"time_unix,\xed\x95")          # 정전으로 잘린 글자
    (tmp_path / "notes_20250101.md").write_text("keep")
    lg = FireLogger(tmp_path, "ess_01", probe_count=3, ir=True)
    lg.write_status(stamp, Status())                           # 예외 없이
    lg.close()
    assert (tmp_path / "fire_20261010_1.csv").exists()
    assert lg.cleanup(stamp + 100 * 86400) and (tmp_path / "notes_20250101.md").exists()


def test_logging_failure_does_not_stop_the_safety_loop(tmp_path):
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    msgs = []
    app, scen = fa.build(cfg, "hidden_heat", str(tmp_path), ros=False, log=msgs.append)

    def full(*a):
        raise OSError(28, "No space left on device")
    app.logger.write_status = app.logger.write_record = full
    fa.run(app, scen, 1.0, 300, 0, None)
    assert app.last.level == 3 and not app.last.charge_allowed            # 기록이 안 돼도 판정, 차단은 계속
    assert sum("기록 오류" in m for m in msgs) == 1


def test_close_stops_probe_reader_thread():
    from fire_detect.drivers.ds18b20 import ProbeGroup
    from fire_detect.sensors import SensorHub
    from fire_detect.simulate import FakeW1, Scenario
    g = ProbeGroup(FakeW1(Scenario("normal")), threaded=True, period_s=0.01)
    hub = SensorHub(probes=g)
    hub.begin()
    assert g._thread.is_alive()
    hub.close()
    assert not g._thread.is_alive()


# ------------------------------------------------------------------ 안전 쪽 동작 (래치 유지, 비상 끄기, 서비스 파일)
def test_danger_latch_survives_restart(tmp_path):
    latch = tmp_path / "latched"
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    app, scen = fa.build(cfg, "overheat", str(tmp_path), ros=False, log=lambda m: None, latch_file=str(latch))
    fa.run(app, scen, 1.0, 300, 0, None)                         # 254 초에 위험 래치
    assert app.last.latched and latch.exists() and "60" in json.loads(latch.read_text())["reason"]
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    app2, scen2 = fa.build(cfg, "normal", str(tmp_path), ros=False, log=lambda m: None,
                           latch_file=str(latch))               # 다시 시작 (식은 상태)
    s = app2.step()
    assert s.level == 3 and s.latched and not s.charge_allowed and "재시작 전" in s.reason
    Path(cfg.reset_file).touch()                                 # 원인 확인 뒤 해제
    s = app2.step()
    assert not s.latched and not latch.exists()
    app2.close()


def test_safe_off_closes_outputs_and_refuses_unknown_config(tmp_path):
    made = []

    class Fake:
        def __init__(self, pins):
            self.pins, self.closed = pins, False
            made.append(self)

        def close(self):
            self.closed = True
    good = tmp_path / "good.yaml"
    good.write_text("pins:\n  ssr: 17\n", encoding="utf-8")
    assert fa.safe_off(str(good), log=lambda m: None, make_outputs=Fake) == 0
    assert made[-1].closed and made[-1].pins.ssr == 17
    if not os.path.exists(fa.DEFAULT_CONFIG):
        assert fa.safe_off(None, log=lambda m: None, make_outputs=Fake) == 1 and len(made) == 1   # 설정 없으면 안 건드림
    bad = tmp_path / "bad.yaml"
    bad.write_text("pins:\n  sssr: 17\n", encoding="utf-8")         # 오타
    assert fa.safe_off(str(bad), log=lambda m: None, make_outputs=Fake) == 1 and len(made) == 1   # 핀을 안 건드림


def test_service_file_keeps_failsafe_lines():
    unit = (ROOT / "systemd" / "fire-detect.service").read_text(encoding="utf-8")
    lines = [x.strip() for x in unit.splitlines() if not x.strip().startswith("#")]
    assert "WatchdogSec=10" in lines and "Restart=always" in lines and "StateDirectory=fire-detect" in lines
    assert "WatchdogSignal=SIGKILL" in lines and "Environment=GPIOZERO_PIN_FACTORY=lgpio" in lines
    assert "Environment=LG_WD=/var/lib/fire-detect" in lines and "WorkingDirectory=/var/lib/fire-detect" in lines
    assert not any("%" in x for x in lines if x.startswith("Exec"))     # % 는 systemd 지정자
    assert any(x.startswith("ExecStopPost=") and "--safe-off" in x for x in lines)
    assert any(x.startswith("ExecStartPre=") and "persist_gpio_outputs" in x and "echo N" in x and "$" not in x
               for x in lines)                                    # $ 는 systemd 가 먼저 바꿔 버림


def test_simulation_does_not_carry_latch_between_runs(tmp_path):
    simulate(tmp_path, "overheat", 300)                         # 래치가 걸린 채 끝남
    assert not (tmp_path / "latched").exists()                  # 시뮬레이션은 래치 파일을 남기지 않음
    app = simulate(tmp_path, "normal", 20)
    assert app.last.level == 0 and not app.last.latched


def test_unopened_gpio_is_reported_as_error(tmp_path):
    cfg = load(None)
    app, scen = fa.build(cfg, "normal", str(tmp_path), ros=False, log=lambda m: None)
    app.gpio_ok = False                                          # 실제 장비에서 GPIO 를 못 연 경우
    h = app.health(0.0)
    assert h["state"] == fa.STATE_ERROR and "GPIO" in h["message"]


def test_latch_file_unreadable_counts_as_latched(tmp_path, monkeypatch):
    cfg = load(None)
    cfg.reset_file = str(tmp_path / "reset.request")
    app, scen = fa.build(cfg, "normal", str(tmp_path), ros=False, log=lambda m: None, latch_file=str(tmp_path / "l"))

    def deny(self):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(Path, "exists", deny)
    app2 = fa.FireApp(app.cfg, app.hub, app.outputs, None, clock=lambda: scen.t, log=lambda m: None)
    assert app2.engine.latched                                   # 알 수 없으면 걸린 것으로 (안전 쪽)
