"""
display.py - SSD1306 OLED 128x64 (0x3C) 상태 표시. 없으면 조용히 꺼진다.

    pip install luma.oled        (Pi 에서만)

왼쪽: 단계, 최고/주변 온도, 연기 전압, 충전 상태 (영문. 기본 글꼴에 한글이 없음)
오른쪽: 8x8 열화상. 뜨거운 화소는 꽉 찬 칸, 기준의 절반 이상은 점
"""
from __future__ import annotations

from .alarm import Status

LEVEL_EN = {0: "NORMAL", 1: "CAUTION", 2: "WARNING", 3: "DANGER"}


def text_lines(s: Status) -> list[str]:
    def t(v):
        return "--" if v != v else f"{v:.1f}"
    head = "FAULT" if s.fault else LEVEL_EN[s.level] + (" L" if s.latched else "")
    smoke = "--" if s.smoke_v != s.smoke_v else f"{s.smoke_v:.2f}V"
    return [head, f"MAX {t(s.surface_max_c)}C", f"AMB {t(s.ambient_temp_c)}C", f"SMK {smoke}",
            "CHG ON" if s.charge_allowed else "CHG OFF"]


class OledDisplay:
    def __init__(self, bus_no: int = 1, addr: int = 0x3C):
        from luma.core.interface.serial import i2c
        from luma.core.render import canvas
        from luma.oled.device import ssd1306
        self.canvas = canvas
        self.dev = ssd1306(i2c(port=bus_no, address=addr), width=128, height=64)

    def show(self, s: Status) -> None:
        with self.canvas(self.dev) as draw:
            for i, line in enumerate(text_lines(s)):
                draw.text((0, i * 12), line, fill="white")
            amb, d = s.ambient_temp_c, s.delta_c
            for i, p in enumerate(s.thermal_c):
                x, y = 64 + (i % 8) * 8, (i // 8) * 8
                if p != p or amb != amb:
                    continue
                if p > amb + d:
                    draw.rectangle((x, y, x + 6, y + 6), fill="white")
                elif p > amb + d / 2:
                    draw.rectangle((x + 2, y + 2, x + 4, y + 4), fill="white")

    def close(self) -> None:
        self.dev.cleanup()
