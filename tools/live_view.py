"""
live_view.py - fire-detect 가 쓰고 있는 기록을 따라 읽어 터미널에 값을 보여 준다 (센서는 건드리지 않음).

    python3 tools/live_view.py                  # ~/fire_logs 의 오늘 기록, 새 줄마다 한 줄
    python3 tools/live_view.py --grid           # + 열화상 8x8 화소 (화면을 지우고 다시 그림)
    python3 tools/live_view.py --dir /tmp/sim --once   # 마지막 줄만 보여 주고 끝냄
      --dir DIR   기록 폴더 (기본 ~/fire_logs)

fire-detect 가 I2C 를 잡고 있어도 이 도구는 파일만 읽으므로 같이 돌려도 된다.
날짜는 UTC 기준으로 바뀌므로 매번 가장 새 파일을 다시 찾는다. Ctrl+C 로 끝낸다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

LEVEL = {"0": "정상", "1": "주의", "2": "경고", "3": "위험"}


def newest(d: Path, prefix: str) -> Path | None:
    files = sorted(p for p in d.glob(f"{prefix}_*.csv") if p.stem[len(prefix) + 1:].isdigit())
    return files[-1] if files else None


def last_row(path: Path) -> dict | None:
    """파일 끝에서 마지막 완전한 줄 하나 (큰 파일도 끝만 읽음)"""
    with open(path, "rb") as fh:
        header = fh.readline().decode("utf-8", "replace").strip()
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 8192))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if line and line != header and not line.startswith("time_unix"):
            row = next(csv.reader([line]))
            cols = next(csv.reader([header]))
            if len(row) == len(cols):
                return dict(zip(cols, row))
    return None


def num(s, nd=1, unit=""):
    try:
        return f"{float(s):.{nd}f}{unit}"
    except (TypeError, ValueError):
        return "--"


def line_of(r: dict) -> str:
    t = datetime.fromtimestamp(float(r["time_unix"])).strftime("%H:%M:%S")
    lvl = LEVEL.get(r.get("level", ""), "?") + (" 래치" if r.get("latched") == "1" else "")
    extra = ""
    probes = [k for k in r if k.startswith("probe") and k.endswith("_c")]
    if probes:
        extra += " 프로브 " + "/".join(num(r[k]) for k in probes)
    if "ir_c" in r:
        extra += f" 적외선 {num(r['ir_c'])}"
    reason = r.get("reason", "")
    return (f"{t} [{lvl}] 주변 {num(r['ambient_c'], 1, '℃')} {num(r['rh_pct'], 0, '%')} "
            f"열화상 최고 {num(r['max_c'], 1, '℃')} 평균 {num(r['mean_c'], 1)} 뜨거운 화소 {r.get('hot_pixels', '-')} "
            f"연기 {num(r['smoke_v'], 3, 'V')} (기준 {num(r['smoke_baseline_v'], 3)}){extra}"
            + (f"  {reason}" if reason else ""))


def grid_of(r: dict | None, ambient: str | None, delta: str | None) -> str:
    if r is None:
        return "(열화상 기록 없음: 설정 log.thermal 이 false 이거나 아직 첫 줄 전)"
    try:
        hot = float(ambient) + float(delta)
    except (TypeError, ValueError):
        hot = None
    out = []
    for y in range(8):
        cells = []
        for x in range(8):
            v = r.get(f"p{y * 8 + x:02d}", "")
            try:
                fv = float(v)
                mark = "*" if hot is not None and fv > hot else " "
                cells.append(f"{fv:5.1f}{mark}")
            except ValueError:
                cells.append("   -- ")
        out.append(" ".join(cells))
    out.append("(* = 주변 + delta_c 초과, 화소 순서는 센서 기준 p00 왼쪽 위)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fire-detect 기록 실시간 보기")
    ap.add_argument("--dir", default="~/fire_logs")
    ap.add_argument("--grid", action="store_true", help="열화상 8x8 도 보여 줌")
    ap.add_argument("--once", action="store_true", help="마지막 값만 보여 주고 끝냄")
    a = ap.parse_args(argv)
    d = Path(os.path.expanduser(a.dir))
    last_t = None
    waited = False
    try:
        while True:
            f = newest(d, "fire")
            r = last_row(f) if f else None
            if r is None:
                if a.once:
                    print(f"{d} 에 fire_*.csv 기록이 없습니다. fire-detect 가 돌고 있는지 확인하세요.")
                    return 1
                if not waited:
                    print(f"{d} 에 기록이 생기기를 기다리는 중... (fire-detect 가 돌고 있는지 확인)")
                    waited = True
            elif r["time_unix"] != last_t:
                last_t = r["time_unix"]
                if a.grid:
                    tf = newest(d, "thermal")
                    g = grid_of(last_row(tf) if tf else None, r.get("ambient_c"), r.get("delta_c"))
                    if not a.once:
                        print("\033[2J\033[H", end="")
                    print(line_of(r))
                    print(g)
                else:
                    print(line_of(r), flush=True)
            if a.once:
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
