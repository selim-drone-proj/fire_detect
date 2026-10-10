"""
alarm.py - 과열, 연기 판정 (하드웨어와 무관한 순수 로직. tests/test_alarm.py 로 검증)

입력 (1 초마다 Frame 하나)
  pixels     AMG8833 화소 64 개 ℃ (못 읽었으면 None)
  ambient_c  SHT31 주변 온도 ℃ (못 읽었으면 None -> 화소 최저값으로 대신)
  smoke_v    MQ-2 출력 전압 V (못 읽었으면 None)

단계 (odor_msgs/FireStatus.msg 와 같은 값)
  0 정상   뜨거운 화소 없음                         녹색
  1 주의   뜨거운 화소 1~2 개 (국부 발열)           황색
  2 경고   뜨거운 화소 warning_pixels(3) 개 이상    적색 점멸, 부저 간헐
  3 위험   연기 감지, 또는 어느 화소든 abs_limit_c  적색 상시, 부저 연속, 충전 차단
  뜨거운 화소 = (화소 온도 > 주변 온도 + delta_c)

오경보와 깜빡임을 막는 장치
  - 올라갈 때: 조건이 confirm_s(2 초) 동안 계속되어야 함 (한 프레임 잡음 무시)
  - 내려갈 때: hysteresis_c 만큼 더 식은 상태가 clear_s(10 초) 동안 계속되어야 함
  - 위험(3) 은 래치: 조건이 사라져도 사람이 해제(버튼, reset 파일)할 때까지 유지
  - 연기 기준 전압은 정상 단계에서만 천천히 학습 (불이 났을 때 기준이 따라 올라가지 않게)

안전 쪽 동작: 열화상을 sensor_loss_cut_s(10 초) 넘게 못 읽으면 감시 불가로 보고 충전을 끊는다.

기준값(delta_c 8 ℃, abs_limit_c 60 ℃, smoke_dv 0.3 V)은 임시값이다.
정상 충전 로그를 며칠 모은 뒤 tools/analyze_log.py 로 다시 정할 것.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

NAN = float("nan")

LEVEL_NORMAL, LEVEL_CAUTION, LEVEL_WARNING, LEVEL_DANGER = 0, 1, 2, 3
LEVEL_NAMES = {0: "정상", 1: "주의", 2: "경고", 3: "위험"}

# FireStatus.msg 상수와 같은 값
FLAG_SMOKE_WARMUP = 1
FLAG_AMG_INVALID = 2
FLAG_SHT_INVALID = 4
FLAG_ADC_INVALID = 8
FLAG_TIME_UNSYNCED = 64
FLAG_SIMULATED = 2048


@dataclass
class AlarmConfig:
    delta_c: float = 8.0               # 뜨거운 화소 기준: 주변 + delta_c
    hysteresis_c: float = 1.5          # 내려갈 때 추가로 식어야 하는 폭
    warning_pixels: int = 3            # 이 개수 이상이면 경고
    abs_limit_c: float = 60.0          # 어느 화소든 이 온도 이상이면 위험
    smoke_dv: float = 0.30             # 연기: 기준 전압보다 이만큼 오르면
    smoke_warmup_s: float = 180.0      # MQ-2 예열. 이 동안 연기 판정 끔
    smoke_tau_s: float = 600.0         # 기준 전압 학습 시정수 (정상 단계에서만)
    confirm_s: float = 2.0             # 올라갈 때 조건 유지 시간
    clear_s: float = 10.0              # 내려갈 때 조건 해소 유지 시간
    latch_danger: bool = True          # 위험 단계 래치
    cut_level: int = LEVEL_DANGER      # 이 단계 이상이면 충전 차단
    sensor_loss_cut_s: float = 10.0    # 열화상 끊김이 이만큼 계속되면 충전 차단

    @classmethod
    def from_dict(cls, d: dict | None) -> "AlarmConfig":
        d = d or {}
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise KeyError(f"alarm 설정에 모르는 항목: {sorted(unknown)}")
        return cls(**d)


@dataclass
class Frame:
    t: float                              # 단조 시계 초 (time.monotonic)
    pixels: list[float] | None
    ambient_c: float | None = None
    rh_pct: float | None = None
    smoke_v: float | None = None


@dataclass
class Status:
    """FireStatus 한 건 (header 제외) + 출력 제어용 값"""
    level: int = LEVEL_NORMAL
    latched: bool = False
    ambient_temp_c: float = NAN
    ambient_rh_pct: float = NAN
    surface_max_c: float = NAN
    surface_mean_c: float = NAN
    surface_min_c: float = NAN
    hot_pixels: int = 0
    hotspot_index: int = 255
    delta_c: float = NAN
    abs_limit_c: float = NAN
    smoke_v: float = NAN
    smoke_baseline_v: float = NAN
    smoke_detected: bool = False
    charge_allowed: bool = True
    dc_allowed: bool = True
    buzzer_on: bool = False
    flags: int = 0
    thermal_c: list[float] = field(default_factory=lambda: [NAN] * 64)
    # ---- 메시지에는 없는 것 ----
    fault: bool = False                   # 감시 불가 (열화상 끊김)
    reason: str = ""                      # 사람이 읽는 판정 이유

    MSG_FIELDS = ("level", "latched", "ambient_temp_c", "ambient_rh_pct", "surface_max_c", "surface_mean_c",
                  "surface_min_c", "hot_pixels", "hotspot_index", "delta_c", "abs_limit_c", "smoke_v",
                  "smoke_baseline_v", "smoke_detected", "charge_allowed", "dc_allowed", "buzzer_on", "flags",
                  "thermal_c")

    def fields(self) -> dict:
        return {k: getattr(self, k) for k in self.MSG_FIELDS}


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


class AlarmEngine:
    def __init__(self, cfg: AlarmConfig | None = None):
        self.cfg = cfg or AlarmConfig()
        self.level = LEVEL_NORMAL
        self.latched = False
        self.started_at: float | None = None
        self.last_t: float | None = None
        self.above_since: float | None = None     # 즉시 단계 > 현재 단계 가 시작된 시각
        self.below_since: float | None = None     # 유지 단계 < 현재 단계 가 시작된 시각
        self.smoke_since: float | None = None
        self.baseline: float | None = None
        self.last_pixels_at: float | None = None
        self.reset_requested = False

    def request_reset(self) -> None:
        """래치 해제 요청. 다음 update 에서 조건이 사라졌으면 해제, 아직이면 무시"""
        self.reset_requested = True

    # ------------------------------------------------------------------
    def update(self, fr: Frame) -> Status:
        c = self.cfg
        if self.started_at is None:
            self.started_at = fr.t
            self.last_pixels_at = fr.t
        dt = 0.0 if self.last_t is None else max(0.0, fr.t - self.last_t)
        self.last_t = fr.t
        s = Status(delta_c=c.delta_c, abs_limit_c=c.abs_limit_c)
        why = []

        # ---- 열화상 ----
        px = fr.pixels if fr.pixels is not None and len(fr.pixels) == 64 else None
        if px is None:
            s.flags |= FLAG_AMG_INVALID
        else:
            self.last_pixels_at = fr.t
            s.thermal_c = list(px)
            s.surface_max_c = max(px)
            s.surface_min_c = min(px)
            s.surface_mean_c = sum(px) / 64.0
            s.hotspot_index = px.index(s.surface_max_c)

        # ---- 주변 온도 (없으면 화소 최저값) ----
        if _ok(fr.ambient_c):
            s.ambient_temp_c = fr.ambient_c
        else:
            s.flags |= FLAG_SHT_INVALID
            s.ambient_temp_c = s.surface_min_c
        if _ok(fr.rh_pct):
            s.ambient_rh_pct = fr.rh_pct

        n_hot = n_warm = 0
        if px is not None and _ok(s.ambient_temp_c):
            n_hot = sum(p > s.ambient_temp_c + c.delta_c for p in px)
            n_warm = sum(p > s.ambient_temp_c + c.delta_c - c.hysteresis_c for p in px)
        s.hot_pixels = n_hot

        # ---- 연기 ----
        warming = fr.t - self.started_at < c.smoke_warmup_s
        smoke_now = smoke_hold = False
        if not _ok(fr.smoke_v):
            s.flags |= FLAG_ADC_INVALID
        else:
            v = fr.smoke_v
            s.smoke_v = v
            if self.baseline is None:
                self.baseline = v
            if warming:
                s.flags |= FLAG_SMOKE_WARMUP
                self.baseline += (v - self.baseline) * min(1.0, dt / 10.0)      # 예열 중엔 빨리 따라감
            else:
                rise = v - self.baseline
                smoke_now = rise >= c.smoke_dv
                smoke_hold = rise >= 0.7 * c.smoke_dv
                if self.level == LEVEL_NORMAL and not smoke_hold:
                    self.baseline += (v - self.baseline) * min(1.0, dt / c.smoke_tau_s)
            s.smoke_baseline_v = self.baseline
        if smoke_now:
            self.smoke_since = fr.t if self.smoke_since is None else self.smoke_since
        else:
            self.smoke_since = None
        s.smoke_detected = smoke_now and fr.t - self.smoke_since >= c.confirm_s

        # ---- 즉시 단계 / 유지 단계 ----
        hot_abs = px is not None and s.surface_max_c >= c.abs_limit_c
        warm_abs = px is not None and s.surface_max_c >= c.abs_limit_c - c.hysteresis_c
        if hot_abs or smoke_now:
            instant = LEVEL_DANGER
            why.append(f"최고 {s.surface_max_c:.1f}℃ >= {c.abs_limit_c:.0f}℃" if hot_abs else
                       f"연기 +{s.smoke_v - self.baseline:.2f} V")
        elif n_hot >= c.warning_pixels:
            instant = LEVEL_WARNING
        elif n_hot >= 1:
            instant = LEVEL_CAUTION
        else:
            instant = LEVEL_NORMAL
        if n_hot:
            why.append(f"뜨거운 화소 {n_hot}개 (주변+{c.delta_c:.0f}℃ 초과)")
        if warm_abs or smoke_hold:
            hold = LEVEL_DANGER
        elif n_warm >= c.warning_pixels:
            hold = LEVEL_WARNING
        elif n_warm >= 1:
            hold = LEVEL_CAUTION
        else:
            hold = LEVEL_NORMAL
        if px is None:                        # 열화상이 없으면 열 조건으로는 오르내리지 않는다
            instant = LEVEL_DANGER if smoke_now else min(instant, self.level)
            hold = max(hold, self.level)

        # ---- 단계 전이 ----
        if instant > self.level:
            self.above_since = fr.t if self.above_since is None else self.above_since
            if fr.t - self.above_since >= c.confirm_s:
                self.level = instant
                self.above_since = None
        else:
            self.above_since = None

        if self.level == LEVEL_DANGER and c.latch_danger:
            self.latched = True
        if self.reset_requested:
            self.reset_requested = False
            if self.latched and hold < LEVEL_DANGER:
                self.latched = False
                self.level = hold
                why.append("수동 해제")
            elif self.latched:
                why.append("해제 요청 무시: 위험 조건이 아직 있음")

        if hold < self.level and not self.latched:
            self.below_since = fr.t if self.below_since is None else self.below_since
            if fr.t - self.below_since >= c.clear_s:
                self.level = hold
                self.below_since = None
        else:
            self.below_since = None

        # ---- 출력 ----
        s.fault = fr.t - self.last_pixels_at >= c.sensor_loss_cut_s
        if s.fault:
            why.append(f"열화상 {fr.t - self.last_pixels_at:.0f}초 끊김: 감시 불가로 충전 차단")
        s.level = self.level
        s.latched = self.latched
        cut = self.level >= c.cut_level or s.fault
        s.charge_allowed = s.dc_allowed = not cut
        s.buzzer_on = self.level >= LEVEL_WARNING
        s.reason = "; ".join(why)
        return s
