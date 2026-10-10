"""
system_info.py - Pi 상태 읽기 (DeviceHealth 용). 공통 파일: odor_drone, fire_detect. 실패하면 NaN, 예외 없음

  uptime_s()      /proc/uptime
  cpu_temp_c()    /sys/class/thermal/thermal_zone0/temp
  supply_v()      Pi5 전원 입력 전압 (vcgencmd pmic_read_adc EXT5V_V). Pi4 이하는 NaN
  clock_synced()  시스템 시각이 NTP 등으로 맞춰졌는가 (timedatectl 의 "System clock synchronized" 와 같은 판정)
"""
from __future__ import annotations

import ctypes
import ctypes.util
import re
import subprocess

NAN = float("nan")


def uptime_s() -> int:
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def cpu_temp_c() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return NAN


def supply_v() -> float:
    try:
        out = subprocess.run(["vcgencmd", "pmic_read_adc", "EXT5V_V"], capture_output=True,
                             text=True, timeout=1.0).stdout
        m = re.search(r"=\s*([0-9.]+)V", out)
        return float(m.group(1)) if m else NAN
    except (OSError, subprocess.SubprocessError, ValueError):
        return NAN


_TIME_ERROR = 5   # adjtimex() 반환값: 시계가 동기화되지 않음 (STA_UNSYNC)


def clock_synced() -> bool:
    """커널 NTP 상태로 판정. systemd-timesyncd, chrony 모두 동기화되면 STA_UNSYNC 를 내린다.
    판정할 수 없으면 False (= 믿지 않음)."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        buf = ctypes.create_string_buffer(512)          # struct timex 보다 넉넉하게. modes = 0 -> 읽기만
        state = libc.adjtimex(buf)
        return 0 <= state != _TIME_ERROR
    except (OSError, AttributeError):
        return False
