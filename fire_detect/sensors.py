"""
sensors.py - 센서를 한 번 읽어 alarm.Frame 을 만든다.

  주 센서   AMG8833 열화상 (못 읽으면 sensor_loss_cut_s 뒤 감시 불가로 충전 차단)
  보조      SHT31 주변 온습도, ADS1115+MQ-2 연기,
            DS18B20 접촉 프로브 여러 개 (1-Wire), MLX90614 적외선 온도계 (I2C)
            보조 센서가 실패하면 flags 와 DEGRADED 로 알리고 충전은 끊지 않는다.

센서 하나가 실패해도 나머지는 계속 읽는다. 실패한 값은 None 이고 alarm 이 flags 로 표시한다.
한 번 실패는 그냥 넘기고, 3 번 연속 실패하면 끊긴 것으로 보고 retry_s 마다 다시 begin().
DS18B20 은 프로브 일부만 못 읽어도 그 프로브는 None, 마스크 비트는 꺼진다 (DEGRADED).

DeviceHealth.sensor_ok_mask (ess_01)
  bit0 AMG8833   bit1 SHT31   bit2 ADS1115(MQ-2)   bit3 DS18B20 (설정한 프로브 모두)   bit4 MLX90614
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .alarm import Frame

OK_AMG8833, OK_SHT31, OK_ADS1115, OK_DS18B20, OK_MLX90614 = 1, 2, 4, 8, 16
FAILS_BEFORE_LOST = 3
SENSOR_ERRORS = (OSError, IOError, ValueError)


@dataclass
class Slot:
    name: str
    bit: int
    sensor: object
    ok: bool = False
    partial: bool = False          # 여러 개 중 일부만 읽힘 (DS18B20)
    fails: int = 0
    next_retry: float = 0.0
    last_error: str = ""


class SensorHub:
    def __init__(self, amg=None, sht=None, adc=None, smoke_channel: int = 0, smoke_divider: float = 1.5,
                 retry_s: float = 30.0, clock=time.monotonic, log=lambda m: None, probes=None, ir=None):
        sensors = (("AMG8833", OK_AMG8833, amg), ("SHT31", OK_SHT31, sht), ("ADS1115", OK_ADS1115, adc),
                   ("DS18B20", OK_DS18B20, probes), ("MLX90614", OK_MLX90614, ir))
        self.slots = {n: Slot(n, b, s) for n, b, s in sensors if s is not None}
        self.smoke_channel = smoke_channel
        self.smoke_divider = smoke_divider
        self.retry_s = retry_s
        self.clock = clock
        self.log = log
        self.error_count = 0
        self.last_error = ""
        self.started = False
        self._probe_problem = ""

    @property
    def sensor_ok_mask(self) -> int:
        return sum(s.bit for s in self.slots.values() if s.ok and not s.partial)

    def _fail(self, slot: Slot, err: Exception, during: str):
        self.error_count += 1
        slot.fails += 1
        slot.last_error = self.last_error = f"{slot.name} {during}: {err}"
        if slot.ok and slot.fails >= FAILS_BEFORE_LOST:
            slot.ok = False
            self.log(f"{slot.name} 끊김으로 판단 ({slot.fails} 회 연속 실패)")
        if not slot.ok:
            slot.next_retry = self.clock() + self.retry_s

    def _begin(self, slot: Slot) -> None:
        try:
            info = slot.sensor.begin()
        except SENSOR_ERRORS as e:
            self._fail(slot, e, "연결")
            return
        slot.ok, slot.fails = True, 0
        self.log(f"{slot.name} 연결됨 ({info})")

    def begin(self) -> int:
        for slot in self.slots.values():
            self._begin(slot)
        self.started = True
        return self.sensor_ok_mask

    def _read(self, name: str, fn):
        slot = self.slots.get(name)
        if slot is None:
            return None
        if not slot.ok:
            if self.clock() >= slot.next_retry:
                self._begin(slot)
            if not slot.ok:
                return None
        try:
            v = fn(slot.sensor)
        except SENSOR_ERRORS as e:
            self._fail(slot, e, "읽기")
            return None
        slot.fails = 0
        return v

    def _read_probes(self) -> list | None:
        slot = self.slots.get("DS18B20")
        if slot is None:
            return None
        vals = self._read("DS18B20", lambda s: s.read())
        out = list(vals) if vals is not None else [None] * slot.sensor.count
        slot.partial = any(v is None for v in out)
        waiting = vals is not None and all(v is None for v in out)      # 막 시작해 첫 값을 기다리는 중
        if slot.partial and vals is not None and not waiting:
            why = slot.sensor.problem(out)
            if why != self._probe_problem:                  # 바뀔 때만 (매 초 덮어써서 다른 센서 오류를 가리지 않게)
                self._probe_problem = why
                slot.last_error = self.last_error = f"DS18B20 {why}"
                self.log(f"DS18B20 일부 못 읽음: {why}")
        elif not slot.partial and self._probe_problem:
            self._probe_problem = ""
            self.log("DS18B20 모두 다시 읽힘")
        return out

    def read(self, t: float | None = None) -> Frame:
        if not self.started:
            self.begin()
        pixels = self._read("AMG8833", lambda s: s.read_pixels())
        th = self._read("SHT31", lambda s: s.read())
        v = self._read("ADS1115", lambda s: s.read_volts(self.smoke_channel))
        probes = self._read_probes()
        ir = self._read("MLX90614", lambda s: s.read())
        return Frame(t=self.clock() if t is None else t, pixels=pixels,
                     ambient_c=th[0] if th else None, rh_pct=th[1] if th else None,
                     smoke_v=v * self.smoke_divider if v is not None else None,
                     probes_c=probes, has_ir="MLX90614" in self.slots,
                     ir_object_c=ir[0] if ir else None, ir_ambient_c=ir[1] if ir else None)

    def close(self) -> None:
        for slot in self.slots.values():
            close = getattr(slot.sensor, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:                            # noqa: BLE001  끄다가 난 오류로 종료를 멈추지 않음
                    pass
