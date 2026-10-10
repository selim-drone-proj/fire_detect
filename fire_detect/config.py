"""
config.py - 설정 파일(YAML) 읽기. 파일에 없는 항목은 아래 기본값.
예시와 설명: config.example.yaml
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields

from .alarm import AlarmConfig


@dataclass
class SensorConfig:
    amg8833_address: int = 0x69
    sht31_address: int = 0x44
    ads1115_address: int = 0x48
    smoke_channel: int = 0          # ADS1115 A0
    smoke_divider: float = 1.5      # 10 kΩ / 20 kΩ 분압 -> AO = ADC 전압 x 1.5
    retry_s: float = 10.0            # 끊긴 센서 다시 연결 시도 간격 (열화상은 빨리 되찾아야 해서 짧게)


@dataclass
class PinConfig:
    """BCM GPIO 번호 (괄호는 40핀 헤더 번호). -1 이면 안 씀"""
    ssr: int = 17                   # (11) AC 충전 라인 SSR. 통전 = 충전 허용
    dc_relay: int = 27              # (13) DC 차단 릴레이. 통전 = DC 허용 (NO 접점에 결선)
    buzzer: int = 22                # (15) 능동 부저 (트랜지스터 또는 릴레이 경유)
    led_red: int = 5                # (29)
    led_yellow: int = 6             # (31)
    led_green: int = 13             # (33)
    reset_button: int = 26          # (37) 래치 해제 버튼, GND 로 누름. 2 초 길게
    relay_active_low: bool = True   # 흔한 4채널 릴레이 모듈은 IN 이 Low 일 때 붙는다
    ssr_active_low: bool = False    # SSR(XSSR-DA2440) 은 입력 + 에 전압이 걸리면 통전
    buzzer_active_low: bool = False


@dataclass
class LogConfig:
    dir: str = "~/fire_logs"
    jsonl_every_s: float = 10.0     # JSONL 은 10 초마다 + 단계, 충전 허용이 바뀔 때마다
    thermal: bool = True            # 화소 64 개 CSV (기준값 정하는 데 필요)
    keep_days: int = 60             # 이보다 오래된 로그 파일은 지운다. 0 이면 안 지움


@dataclass
class DisplayConfig:
    enabled: bool = True            # luma.oled 가 없거나 OLED 가 안 붙어 있으면 자동으로 끔
    address: int = 0x3C


@dataclass
class Config:
    device_id: str = "ess_01"
    i2c_bus: int = 1
    period_s: float = 1.0
    health_period_s: float = 10.0
    reset_file: str = "/run/fire-detect/reset"     # 이 파일이 생기면 래치 해제 요청 (fire-detect --reset)
    sensors: SensorConfig = field(default_factory=SensorConfig)
    alarm: AlarmConfig = field(default_factory=AlarmConfig)
    pins: PinConfig = field(default_factory=PinConfig)
    log: LogConfig = field(default_factory=LogConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


def _build(cls, data: dict | None, where: str):
    data = data or {}
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise KeyError(f"{where} 에 모르는 항목: {sorted(unknown)}")
    kw = {}
    for name, val in data.items():
        sub = {"sensors": SensorConfig, "alarm": AlarmConfig, "pins": PinConfig,
               "log": LogConfig, "display": DisplayConfig}.get(name) if cls is Config else None
        kw[name] = _build(sub, val, f"{where}.{name}") if sub else val
    return cls(**kw)


def load(path: str | None) -> Config:
    if not path:
        return Config()
    import yaml
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return _build(Config, yaml.safe_load(f) or {}, os.path.basename(path))
