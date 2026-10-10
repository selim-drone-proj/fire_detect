"""
logger.py - 기록 파일 (하루 한 파일, 날짜는 UTC)

  fire_YYYYmmdd.csv      1 초마다 판정 결과 한 줄 (사람이 보기, 엑셀)
  thermal_YYYYmmdd.csv   1 초마다 화소 64 개 (정상 충전 패턴을 보고 기준값 정할 때)
  fire_YYYYmmdd.jsonl    규격 v0.2 기록: fire_status (10 초마다 + 바뀔 때), device_health (10 초마다)

값이 없으면 CSV 는 빈 칸, JSON 은 null.
"""
from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path

from .alarm import Status
from .odor_json import iso_utc, record

STATUS_COLUMNS = [
    "time_unix", "time_iso", "device_id", "level", "latched", "ambient_c", "rh_pct", "max_c", "mean_c", "min_c",
    "hot_pixels", "hotspot", "delta_c", "abs_limit_c", "smoke_v", "smoke_baseline_v", "smoke",
    "charge_allowed", "dc_allowed", "buzzer", "flags", "fault", "reason",
]
THERMAL_COLUMNS = ["time_unix", "time_iso"] + [f"p{i:02d}" for i in range(64)]


def f(v, nd: int) -> str:
    return "" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.{nd}f}"


class FireLogger:
    def __init__(self, out_dir: str | Path, device_id: str, jsonl_every_s: float = 10.0,
                 thermal: bool = True, keep_days: int = 60):
        self.dir = Path(os.path.expanduser(str(out_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.device_id = device_id
        self.jsonl_every_s = jsonl_every_s
        self.thermal = thermal
        self.keep_days = keep_days
        self.files: dict[str, tuple] = {}
        self.day = None
        self.last_jsonl = -1e18
        self.last_key = None

    def _open(self, name: str, header: list[str] | None):
        if name not in self.files:
            path = self.dir / name
            new = not path.exists() or path.stat().st_size == 0
            fh = open(path, "a", newline="", encoding="utf-8")
            w = csv.writer(fh, lineterminator="\n") if header else None
            if new and header:
                w.writerow(header)
            self.files[name] = (fh, w)
        return self.files[name]

    def _roll(self, stamp: float):
        day = time.strftime("%Y%m%d", time.gmtime(stamp))
        if day != self.day:
            self.close()
            self.day = day
            self.cleanup(stamp)
        return day

    def write_status(self, stamp: float, s: Status) -> dict | None:
        """판정 한 건 기록. JSONL 에 쓴 경우 그 기록을 돌려준다"""
        day = self._roll(stamp)
        fh, w = self._open(f"fire_{day}.csv", STATUS_COLUMNS)
        w.writerow([f"{stamp:.3f}", iso_utc(stamp), self.device_id, s.level, int(s.latched),
                    f(s.ambient_temp_c, 2), f(s.ambient_rh_pct, 1), f(s.surface_max_c, 2), f(s.surface_mean_c, 2),
                    f(s.surface_min_c, 2), s.hot_pixels, s.hotspot_index, f(s.delta_c, 1), f(s.abs_limit_c, 1),
                    f(s.smoke_v, 3), f(s.smoke_baseline_v, 3), int(s.smoke_detected), int(s.charge_allowed),
                    int(s.dc_allowed), int(s.buzzer_on), s.flags, int(s.fault), s.reason])
        fh.flush()
        if self.thermal and s.surface_max_c == s.surface_max_c:          # NaN 이 아니면
            fh2, w2 = self._open(f"thermal_{day}.csv", THERMAL_COLUMNS)
            w2.writerow([f"{stamp:.3f}", iso_utc(stamp)] + [f(p, 2) for p in s.thermal_c])
            fh2.flush()
        key = (s.level, s.latched, s.charge_allowed, s.fault, s.smoke_detected)
        if key != self.last_key or stamp - self.last_jsonl >= self.jsonl_every_s:
            self.last_key, self.last_jsonl = key, stamp
            rec = record("fire_status", stamp, self.device_id, **s.fields())
            self.write_record(stamp, rec)
            return rec
        return None

    def write_record(self, stamp: float, rec: dict) -> None:
        day = self._roll(stamp)
        fh, _ = self._open(f"fire_{day}.jsonl", None)
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()

    def cleanup(self, now: float) -> list[str]:
        if self.keep_days <= 0:
            return []
        limit = time.strftime("%Y%m%d", time.gmtime(now - self.keep_days * 86400))
        removed = []
        for p in self.dir.glob("*_????????.*"):
            stem_day = p.stem.rsplit("_", 1)[-1]
            if stem_day.isdigit() and len(stem_day) == 8 and stem_day < limit:
                p.unlink()
                removed.append(p.name)
        return removed

    def close(self):
        for fh, _ in self.files.values():
            fh.close()
        self.files.clear()
