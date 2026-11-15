"""
outputs.py - 판정 결과를 LED, 부저, SSR, DC 릴레이로 내보낸다.

  단계        녹   황     적      부저                 AC SSR, DC 릴레이
  0 정상      켬   -      -       -                    통전 (충전 허용)
  1 주의      -    켬     -       -                    통전
  2 경고      -    -      점멸    0.2 초 / 2 초 간헐   통전 (cut_level 을 2 로 하면 차단)
  3 위험      -    -      켬      연속                 차단
  감시 불가   -    점멸   -       0.1 초 / 5 초        차단

안전 쪽 설계: SSR 과 릴레이는 "통전해야 충전" 이다. 시작할 때 모든 출력은 꺼진 값으로 열고,
켠 뒤 start_hold_s(10 초)는 판정이 차단을 유지한다. 끝날 때 close() 가 끈다.
프로세스가 죽으면: Pi 5 커널은 놓인 GPIO 출력을 그대로 두는 것이 기본(persist_gpio_outputs)이라
서비스 파일이 그 설정을 끄고(ExecStartPre), 끝난 뒤 fire-detect --safe-off 로 다시 끈다(ExecStopPost).
Pi 전원이 나가면 출력이 풀려 충전이 끊긴다.
"""
from __future__ import annotations

from .alarm import LEVEL_DANGER, LEVEL_WARNING, Status
from .config import PinConfig


def pattern(s: Status) -> dict:
    """Status -> 출력별 상태 ("on", "off", "blink", "beep", "chirp")"""
    p = dict(green="off", yellow="off", red="off", buzzer="off",
             ssr="on" if s.charge_allowed else "off", dc="on" if s.dc_allowed else "off")
    if s.fault:
        p.update(yellow="blink", buzzer="chirp")
    elif s.level >= LEVEL_DANGER:
        p.update(red="on", buzzer="on")
    elif s.level == LEVEL_WARNING:
        p.update(red="blink", buzzer="beep")
    elif s.level == 1:
        p.update(yellow="on")
    else:
        p.update(green="on")
    return p


class FakeOutputs:
    """하드웨어 없이 (PC, 시뮬레이션, 시험). 마지막 상태와 바뀐 기록만 남긴다"""

    def __init__(self):
        self.state: dict = {}
        self.history: list[dict] = []
        self._reset = False

    def apply(self, s: Status) -> None:
        p = pattern(s)
        if p != self.state:
            self.state = p
            self.history.append(dict(p))

    def press_reset(self) -> None:
        self._reset = True

    def reset_pressed(self) -> bool:
        r, self._reset = self._reset, False
        return r

    def close(self) -> None:
        self.state = dict(green="off", yellow="off", red="off", buzzer="off", ssr="off", dc="off")


class GpioOutputs:
    """Pi5: gpiozero (+ lgpio). sudo apt install python3-gpiozero python3-lgpio"""

    def __init__(self, pins: PinConfig):
        from gpiozero import LED, Button, Buzzer, OutputDevice

        def out(pin, cls=OutputDevice, active_low=False):
            return cls(pin, active_high=not active_low, initial_value=False) if pin >= 0 else None

        self.dev = dict(
            ssr=out(pins.ssr, active_low=pins.ssr_active_low),
            dc=out(pins.dc_relay, active_low=pins.relay_active_low),
            buzzer=out(pins.buzzer, Buzzer, pins.buzzer_active_low),
            red=out(pins.led_red, LED), yellow=out(pins.led_yellow, LED), green=out(pins.led_green, LED))
        self.state: dict = {}
        self._reset = False
        self.button = None
        if pins.reset_button >= 0:
            self.button = Button(pins.reset_button, pull_up=True, hold_time=2.0)
            self.button.when_held = self._on_hold

    def _on_hold(self):
        self._reset = True

    def reset_pressed(self) -> bool:
        r, self._reset = self._reset, False
        return r

    def apply(self, s: Status) -> None:
        p = pattern(s)
        for name, want in p.items():
            dev = self.dev.get(name)
            if dev is None or self.state.get(name) == want:
                continue
            if want == "on":
                dev.on()
            elif want == "off":
                dev.off()
            elif want == "blink":
                dev.blink(on_time=0.5, off_time=0.5)
            elif want == "beep":
                dev.beep(on_time=0.2, off_time=1.8) if hasattr(dev, "beep") else dev.blink(0.2, 1.8)
            elif want == "chirp":
                dev.beep(on_time=0.1, off_time=4.9) if hasattr(dev, "beep") else dev.blink(0.1, 4.9)
        self.state = p

    def close(self) -> None:
        for dev in self.dev.values():
            if dev is not None:
                dev.off()
                dev.close()
        if self.button is not None:
            self.button.close()
