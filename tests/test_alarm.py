"""판정 로직: 단계, 히스테리시스, 래치, 연기 기준선, 센서 끊김"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fire_detect import alarm as al  # noqa: E402
from fire_detect.alarm import AlarmConfig, AlarmEngine, Frame  # noqa: E402

AMB = 24.0


def frame(t, hot=(), temp=None, ambient=AMB, smoke=0.80, pixels=True):
    """hot 에 적은 화소만 temp ℃, 나머지는 주변 + 1 ℃"""
    if not pixels:
        return Frame(t, None, ambient, 45.0, smoke)
    px = [AMB + 1.0] * 64
    for i in hot:
        px[i] = temp
    return Frame(t, px, ambient, 45.0, smoke)


def run(eng, frames):
    return [eng.update(f) for f in frames]


def cfg(**kw):
    base = dict(smoke_warmup_s=0.0, confirm_s=2.0, clear_s=10.0)
    base.update(kw)
    return AlarmConfig(**base)


def test_constants_match_msg_file():
    msgspec_dir = ROOT.parent / "moving-ver" / "tools"
    if not msgspec_dir.exists():
        pytest.skip("moving-ver 가 옆에 없음")
    sys.path.insert(0, str(msgspec_dir))
    import msgspec
    m = msgspec.load_all()["FireStatus"]
    for c in m.consts:
        assert getattr(al, c.name) == c.value, c.name
    names = [f.name for f in m.fields if f.name != "header"]
    assert list(al.Status.MSG_FIELDS) == names


def test_normal_stays_normal():
    eng = AlarmEngine(cfg())
    s = run(eng, [frame(t) for t in range(30)])[-1]
    assert s.level == 0 and s.charge_allowed and not s.buzzer_on and s.hot_pixels == 0
    assert s.hotspot_index in range(64) and s.surface_max_c == AMB + 1


def test_single_noisy_frame_is_ignored():
    eng = AlarmEngine(cfg())
    run(eng, [frame(t) for t in range(5)])
    s = eng.update(frame(5, hot=[10], temp=AMB + 12))           # 한 프레임만 튐
    s = eng.update(frame(6))
    assert s.level == 0


def test_levels_rise_after_confirm_time():
    eng = AlarmEngine(cfg())
    run(eng, [frame(t) for t in range(5)])
    ss = run(eng, [frame(t, hot=[27], temp=AMB + 10) for t in range(5, 9)])
    assert [s.level for s in ss] == [0, 0, 1, 1]               # 5 초부터 조건, 7 초에 2 초 지남
    assert ss[-1].hot_pixels == 1 and ss[-1].hotspot_index == 27
    ss = run(eng, [frame(t, hot=[26, 27, 28], temp=AMB + 10) for t in range(9, 12)])
    assert ss[-1].level == 2 and ss[-1].buzzer_on and ss[-1].charge_allowed


def test_abs_limit_is_danger_latched_and_cuts():
    eng = AlarmEngine(cfg())
    ss = run(eng, [frame(t, hot=[0], temp=61.0) for t in range(4)])
    s = ss[-1]
    assert s.level == 3 and s.latched and not s.charge_allowed and not s.dc_allowed
    # 식어도 래치 유지
    ss = run(eng, [frame(t) for t in range(4, 40)])
    assert ss[-1].level == 3 and ss[-1].latched and not ss[-1].charge_allowed


def test_reset_only_when_condition_cleared():
    eng = AlarmEngine(cfg())
    run(eng, [frame(t, hot=[0], temp=61.0) for t in range(4)])
    eng.request_reset()
    s = eng.update(frame(4, hot=[0], temp=61.0))                # 아직 뜨거움 -> 무시
    assert s.latched and "무시" in s.reason
    eng.request_reset()
    s = eng.update(frame(5))
    assert not s.latched and s.level == 0 and s.charge_allowed


def test_hysteresis_and_clear_time():
    eng = AlarmEngine(cfg())
    run(eng, [frame(t, hot=[5], temp=AMB + 10) for t in range(4)])
    assert eng.level == 1
    # 기준(주변+8) 바로 아래, 히스테리시스(1.5) 안쪽 -> 유지
    ss = run(eng, [frame(t, hot=[5], temp=AMB + 7.0) for t in range(4, 30)])
    assert ss[-1].level == 1
    # 충분히 식음 -> clear_s(10 초) 뒤 정상
    ss = run(eng, [frame(t, hot=[5], temp=AMB + 5.0) for t in range(30, 45)])
    assert [s.level for s in ss].index(0) == 10


def test_smoke_detection_and_baseline():
    eng = AlarmEngine(cfg(smoke_warmup_s=60.0))
    ss = run(eng, [frame(t, smoke=0.50 + 0.005 * t) for t in range(60)])     # 예열 중 천천히 변함
    assert all(s.flags & al.FLAG_SMOKE_WARMUP for s in ss) and ss[-1].level == 0
    assert ss[-1].smoke_baseline_v == pytest.approx(0.795, abs=0.06)
    ss = run(eng, [frame(t, smoke=0.80) for t in range(60, 120)])
    base = ss[-1].smoke_baseline_v
    ss = run(eng, [frame(t, smoke=base + 0.35) for t in range(120, 124)])
    assert ss[-1].smoke_detected and ss[-1].level == 3 and not ss[-1].charge_allowed
    assert ss[-1].smoke_baseline_v == pytest.approx(base, abs=1e-6)          # 경보 중엔 기준 고정


def test_ambient_falls_back_to_min_pixel():
    eng = AlarmEngine(cfg())
    s = eng.update(Frame(0.0, [30.0] * 63 + [20.0], None, None, 0.8))
    assert s.flags & al.FLAG_SHT_INVALID and s.ambient_temp_c == 20.0
    assert s.hot_pixels == 63


def test_sensor_loss_cuts_charging_after_timeout():
    eng = AlarmEngine(cfg(sensor_loss_cut_s=10.0))
    run(eng, [frame(t) for t in range(5)])
    ss = run(eng, [frame(t, pixels=False) for t in range(5, 20)])
    assert all(s.flags & al.FLAG_AMG_INVALID for s in ss)
    assert ss[4].charge_allowed and not ss[-1].charge_allowed and ss[-1].fault
    assert ss[-1].hotspot_index == 255 and math.isnan(ss[-1].surface_max_c)
    s = eng.update(frame(20))
    assert s.charge_allowed and not s.fault


def test_missing_adc_does_not_alarm():
    eng = AlarmEngine(cfg())
    ss = run(eng, [Frame(t, [AMB] * 64, AMB, 45.0, None) for t in range(10)])
    assert ss[-1].flags & al.FLAG_ADC_INVALID and ss[-1].level == 0


def test_config_rejects_typos():
    with pytest.raises(KeyError):
        AlarmConfig.from_dict({"delta": 5})


# ------------------------------------------------------------------ 점 센서 (접촉 프로브, 적외선)
def pframe(t, probes=(AMB + 3,) * 3, ir=AMB + 2.5, has_ir=True, pixels=True, smoke=0.80, hot=(), temp=None):
    """점 센서를 붙인 Frame (열화상은 frame() 과 같음)"""
    f = frame(t, hot=hot, temp=temp, pixels=pixels, smoke=smoke)
    f.probes_c = list(probes) if probes is not None else None
    f.ir_object_c, f.ir_ambient_c, f.has_ir = ir, AMB + 1, has_ir
    return f


def test_point_sensors_normal_and_recorded():
    eng = AlarmEngine(cfg())
    s = run(eng, [pframe(t) for t in range(5)])[-1]
    assert s.level == 0 and s.flags == 0 and s.probe_c == [AMB + 3] * 3 and s.ir_object_c == AMB + 2.5
    assert "probe_c" not in al.Status.MSG_FIELDS                  # 규격 v0.2 FireStatus 는 그대로


def test_hot_probe_is_caution_only():
    eng = AlarmEngine(cfg())
    ss = run(eng, [pframe(t, probes=(AMB + 3, AMB + 15, AMB + 15)) for t in range(10)])
    assert ss[-1].level == 1 and ss[-1].charge_allowed and "프로브2" in ss[-1].reason   # 점 센서만으로는 경고 안 됨


def test_probe_at_limit_is_danger_even_without_thermal_camera():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t) for t in range(3)])
    ss = run(eng, [pframe(t, probes=(AMB + 3, AMB + 3, 61.0), pixels=False) for t in range(3, 7)])
    s = ss[-1]
    assert s.level == 3 and s.latched and not s.charge_allowed and "프로브3 61.0℃ >= 60℃" in s.reason


def test_ir_uses_its_own_limits():
    eng = AlarmEngine(cfg(ir_abs_limit_c=50.0, ir_delta_c=20.0))
    ss = run(eng, [pframe(t, ir=AMB + 15) for t in range(5)])
    assert ss[-1].level == 0                                      # 주변 + 15 < ir_delta_c 20
    ss = run(eng, [pframe(t, ir=51.0) for t in range(5, 9)])
    assert ss[-1].level == 3 and "적외선 51.0℃ >= 50℃" in ss[-1].reason


def test_probe_delta_separate_from_pixels():
    hot = (AMB + 10, AMB + 3, AMB + 3)
    assert run(AlarmEngine(cfg()), [pframe(t, probes=hot) for t in range(5)])[-1].level == 1
    assert run(AlarmEngine(cfg(probe_delta_c=12.0)), [pframe(t, probes=hot) for t in range(5)])[-1].level == 0


def test_lost_point_sensor_flags_but_does_not_cut():
    eng = AlarmEngine(cfg())
    ss = run(eng, [pframe(t, probes=(AMB + 3, None, AMB + 3), ir=None) for t in range(30)])
    s = ss[-1]
    assert s.flags & al.FLAG_PROBE_INVALID and s.flags & al.FLAG_IR_INVALID
    assert s.level == 0 and s.charge_allowed and not s.fault and math.isnan(s.probe_c[1])


def test_unused_point_sensors_set_no_flags():
    s = AlarmEngine(cfg()).update(pframe(0, probes=None, ir=None, has_ir=False))
    assert s.flags == 0 and s.probe_c == [] and math.isnan(s.ir_object_c)


def test_probe_lost_while_hot_keeps_level_and_latch():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t, probes=(AMB + 3, AMB + 3, 62.0)) for t in range(4)])
    assert eng.level == 3 and eng.latched
    # 프로브 3 이 뜨거운 채로 끊김 -> 해제 요청을 무시
    eng.request_reset()
    s = eng.update(pframe(4, probes=(AMB + 3, AMB + 3, None)))
    assert s.latched and "무시" in s.reason and "프로브3 끊김" in s.reason
    # 다시 읽히고 식었으면 풀림
    eng.request_reset()
    s = eng.update(pframe(5, probes=(AMB + 3, AMB + 3, AMB + 3)))
    assert not s.latched and s.level == 0 and s.charge_allowed


def test_probe_lost_while_warm_does_not_drop_caution():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t, probes=(AMB + 10, AMB + 3, AMB + 3)) for t in range(4)])
    assert eng.level == 1
    ss = run(eng, [pframe(t, probes=(None, AMB + 3, AMB + 3)) for t in range(4, 40)])
    assert ss[-1].level == 1                                      # 데워진 채 끊김: 내려가지 않음
    ss = run(eng, [pframe(t, probes=(AMB + 3,) * 3) for t in range(40, 55)])
    assert ss[-1].level == 0                                      # 다시 읽히고 식으면 clear_s 뒤 정상


def test_probe_lost_while_cool_does_not_block_clearing():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t) for t in range(3)])
    lost = dict(probes=(None, None, None), ir=None)
    run(eng, [pframe(t, hot=[9], temp=AMB + 10, **lost) for t in range(3, 8)])
    assert eng.level == 1                                         # 열화상 때문에 주의
    ss = run(eng, [pframe(t, **lost) for t in range(8, 25)])
    assert ss[-1].level == 0                                      # 식어 있을 때 끊긴 프로브는 내려가는 것을 막지 않음


def test_lost_probe_hold_is_frozen_not_rejudged_with_new_ambient():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t, probes=(28.0, AMB + 3, AMB + 3)) for t in range(3)])       # 28 ℃: 주변 24 기준 안 뜨거움
    cold = dict(probes=(None, 21.0, 21.0), ir=21.0)
    run(eng, [pframe(t, **cold) for t in range(3, 5)])                               # 프로브 1 끊김
    ss = [eng.update(Frame(t, [19.0] * 63 + [30.0], 18.0, 45.0, 0.8, probes_c=[None, 21.0, 21.0],
                           ir_object_c=21.0, has_ir=True)) for t in range(5, 12)]    # 밤: 주변 18, 화소 하나 뜨거움
    assert ss[-1].level == 1
    ss = [eng.update(Frame(t, [19.0] * 64, 18.0, 45.0, 0.8, probes_c=[None, 21.0, 21.0], ir_object_c=21.0,
                           has_ir=True)) for t in range(12, 30)]
    assert ss[-1].level == 0 and "끊김" not in ss[-1].reason                         # 옛 28 ℃ 가 이제 와서 뜨겁다고 붙잡지 않음


def test_ir_lost_while_warm_keeps_caution():
    eng = AlarmEngine(cfg())
    run(eng, [pframe(t, ir=AMB + 12) for t in range(4)])
    assert eng.level == 1
    ss = run(eng, [pframe(t, ir=None) for t in range(4, 30)])
    assert ss[-1].level == 1 and ss[-1].flags & al.FLAG_IR_INVALID and "적외선 끊김" in ss[-1].reason


def test_point_limits_work_without_any_ambient():
    eng = AlarmEngine(cfg())
    f = [Frame(t, None, None, None, 0.8, probes_c=[AMB + 10, AMB, AMB]) for t in range(4)]
    ss = run(eng, f)
    assert ss[-1].level == 0                                     # 주변을 모르면 '뜨거움' 은 판단 안 함
    ss = run(eng, [Frame(t, None, None, None, 0.8, probes_c=[61.0, AMB, AMB]) for t in range(4, 8)])
    assert ss[-1].level == 3 and not ss[-1].charge_allowed       # 한계는 주변 없이도


def test_last_raw_probe_sample_holds_danger_when_probe_burns_off():
    """두 값 중 낮은 값(58)만 판정에 들어간 채 프로브가 끊겨도, 마지막 날값(66)으로 위험을 붙잡는다"""
    eng = AlarmEngine(cfg())

    def f(t, probe, raw, cam=AMB + 1):
        fr = frame(t, hot=[0], temp=cam)
        fr.probes_c, fr.probes_raw_c = [probe, AMB + 3], [raw, AMB + 3]
        return fr
    run(eng, [f(t, 58.0, 66.0) for t in range(4)])
    assert eng.level == 1                                         # 판정 값 58: 주의
    run(eng, [f(t, None, 66.0, cam=61.0) for t in range(4, 8)])   # 프로브 끊김 + 열화상이 위험 래치
    assert eng.latched
    eng.request_reset()
    s = eng.update(f(8, None, 66.0))                              # 열화상은 식었지만
    assert s.latched and "프로브1 끊김 (끊기기 전 66.0℃)" in s.reason   # 날값 66 ℃ 로 붙잡음 -> 해제 거부
