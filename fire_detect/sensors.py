"""
sensors.py - 센서 3종(AMG8833, SHT31, ADS1115+MQ-2)을 한 번 읽어 alarm.Frame 을 만든다.

센서 하나가 실패해도 나머지는 계속 읽는다. 실패한 값은 None 이고 alarm 이 flags 로 표시한다.
한 번 실패는 그냥 넘기고, 3 번 연속 실패하면 끊긴 것으로 보고 retry_s(30 초)마다 다시 begin().

DeviceHealth.sensor_ok_mask (ess_01)
  bit0 AMG8833   bit1 SHT31   bit2 ADS1115(MQ-2)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .alarm import Frame

OK_AMG8833, OK_SHT31, OK_ADS1115 = 1, 2, 4
FAILS_BEFORE_LOST = 3
SENSOR_ERRORS = (OSError, IOError, ValueError)


@dataclass
class Slot:
    name: str
    bit: int
    sensor: object
    ok: bool = False
    fails: int = 0
    next_retry: float = 0.0
    last_error: str = ""


class SensorHub:
    def __init__(self, amg=None, sht=None, adc=None, smoke_channel: int = 0, smoke_divider: float = 1.5,
                 retry_s: float = 30.0, clock=time.monotonic, log=lambda m: None):
        self.slots = {n: Slot(n, b, s) for n, b, s in (("AMG8833", OK_AMG8833, amg), ("SHT31", OK_SHT31, sht),
                                                      ("ADS1115", OK_ADS1115, adc)) if s is not None}
        self.smoke_channel = smoke_channel
        self.smoke_divider = smoke_divider
        self.retry_s = retry_s
        self.clock = clock
        self.log = log
        self.error_count = 0
        self.last_error = ""
        self.started = False

    @property
    def sensor_ok_mask(self) -> int:
        return sum(s.bit for s in self.slots.values() if s.ok)

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

    def read(self, t: float | None = None) -> Frame:
        if not self.started:
            self.begin()
        pixels = self._read("AMG8833", lambda s: s.read_pixels())
        th = self._read("SHT31", lambda s: s.read())
        v = self._read("ADS1115", lambda s: s.read_volts(self.smoke_channel))
        return Frame(t=self.clock() if t is None else t, pixels=pixels,
                     ambient_c=th[0] if th else None, rh_pct=th[1] if th else None,
                     smoke_v=v * self.smoke_divider if v is not None else None)
