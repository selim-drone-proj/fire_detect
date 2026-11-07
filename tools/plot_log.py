"""
plot_log.py - fire-detect 기록(fire_*.csv, thermal_*.csv)을 그래프 PNG 와 요약으로 만든다.

    python3 tools/plot_log.py                          # ~/fire_logs 의 가장 새 날짜
    python3 tools/plot_log.py --day 20261031           # 그 날짜 (UTC)
    python3 tools/plot_log.py --last 30                # 마지막 30 분만
    python3 tools/plot_log.py --dir /tmp/sim --out /tmp/plots
      --dir DIR   기록 폴더 (기본 ~/fire_logs)
      --out DIR   PNG 를 둘 곳 (기본: 기록 폴더 아래 plots/)

만드는 것
  fire_<날짜>.png         시간에 따른 온도(주변, 열화상 최고, 평균, 프로브, 적외선), 습도, 연기 전압(기준선 포함), 판정 단계,
                          그리고 Pi 5 입력 전압 (보조배터리, jsonl 의 device_health.supply_v 가 있을 때)
  thermal_<날짜>.png      열화상 8x8: 가장 뜨거웠던 순간, 기간 평균, 화소별 최고
  그리고 터미널에 요약 (기간, 범위, 단계별 시간, 센서 빈 값 비율)

필요: matplotlib (sudo apt install python3-matplotlib, venv 는 --system-site-packages 로 만들었으면 그대로 보임)
그래프 글자는 영어로 둔다 (Ubuntu Server 에 한글 글꼴이 없어도 깨지지 않게). 시간축은 보드의 현지 시각.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path


def num(s):
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def day_files(d: Path, prefix: str, day: str) -> list[Path]:
    """그날 파일 (열이 바뀌어 옮겨진 fire_YYYYmmdd_N.csv 포함), 오래된 것부터"""
    rotated = sorted(d.glob(f"{prefix}_{day}_*.csv"), key=lambda p: int(p.stem.rsplit("_", 1)[1]))
    main = d / f"{prefix}_{day}.csv"
    return rotated + ([main] if main.exists() else [])


def read_rows(paths: list[Path], t_from: float | None) -> list[dict]:
    rows = []
    for p in paths:
        with open(p, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                t = num(r.get("time_unix"))
                if t is None or (t_from is not None and t < t_from):
                    continue
                r["_t"] = t
                rows.append(r)
    rows.sort(key=lambda r: r["_t"])
    return rows


def read_supply(d: Path, day: str, t_from: float | None) -> list[tuple[float, float]]:
    """fire_<날짜>.jsonl 의 device_health.supply_v (Pi 5 USB-C 입력 전압, 10 초마다). 없으면 빈 목록"""
    out = []
    p = d / f"fire_{day}.jsonl"
    if not p.exists():
        return out
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            v = r.get("supply_v") if r.get("type") == "device_health" else None
            if v is None:
                continue
            t = datetime.fromisoformat(r["stamp"].replace("Z", "+00:00")).timestamp()
            if t_from is None or t >= t_from:
                out.append((t, float(v)))
    return out


def col(rows, name):
    return [num(r.get(name)) for r in rows]


def rng(xs):
    v = [x for x in xs if x is not None]
    return (min(v), max(v)) if v else (None, None)


def summarize(rows: list[dict], thermal_n: int) -> str:
    t0, t1 = rows[0]["_t"], rows[-1]["_t"]
    lines = [f"기간: {datetime.fromtimestamp(t0):%Y-%m-%d %H:%M:%S} ~ {datetime.fromtimestamp(t1):%H:%M:%S} "
             f"({(t1 - t0) / 60:.1f} 분, {len(rows)} 줄, 열화상 {thermal_n} 줄)"]
    for name, label, unit in (("ambient_c", "주변 온도", "℃"), ("rh_pct", "습도", "%"), ("max_c", "열화상 최고", "℃"),
                              ("mean_c", "열화상 평균", "℃"), ("smoke_v", "연기 출력", "V")):
        xs = col(rows, name)
        lo, hi = rng(xs)
        empty = sum(1 for x in xs if x is None) / len(xs) * 100
        nd = 3 if unit == "V" else 1
        lines.append(f"  {label:<8} " + (f"{lo:.{nd}f} ~ {hi:.{nd}f} {unit}" if lo is not None else "값 없음")
                     + (f"  (빈 값 {empty:.0f} %)" if empty else ""))
    for k in [k for k in rows[0] if k.startswith("probe") and k.endswith("_c")] + (["ir_c"] if "ir_c" in rows[0] else []):
        lo, hi = rng(col(rows, k))
        lines.append(f"  {k:<8} " + (f"{lo:.1f} ~ {hi:.1f} ℃" if lo is not None else "값 없음"))
    rise = [m - a for m, a in zip(col(rows, "max_c"), col(rows, "ambient_c")) if m is not None and a is not None]
    if rise:
        lines.append(f"  열화상 최고 - 주변: 최대 {max(rise):.1f} ℃ (판정 기준 delta_c {rows[-1].get('delta_c', '?')} ℃)")
    sm = [(v - b) for v, b in zip(col(rows, "smoke_v"), col(rows, "smoke_baseline_v")) if v is not None and b is not None]
    if sm:
        lines.append(f"  연기 - 기준: 최대 {max(sm):+.3f} V (판정 기준 +0.30 V, 켠 뒤 3 분은 예열)")
    counts = {}
    for r in rows:
        counts[r.get("level", "?")] = counts.get(r.get("level", "?"), 0) + 1
    names = {"0": "정상", "1": "주의", "2": "경고", "3": "위험"}
    lines.append("  단계별: " + ", ".join(f"{names.get(k, k)} {v} 초" for k, v in sorted(counts.items())))
    faults = sum(1 for r in rows if r.get("fault") == "1")
    if faults:
        lines.append(f"  감시 불가(열화상 끊김 등): {faults} 초")
    return "\n".join(lines)


def plot_status(rows: list[dict], path: Path, title: str, supply=None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    t = [datetime.fromtimestamp(r["_t"]) for r in rows]
    n = 5 if supply else 4
    fig, ax = plt.subplots(n, 1, figsize=(12, 10 + 1.6 * (n - 4)), sharex=True,
                           gridspec_kw=dict(height_ratios=[3, 1.2, 1.5, 1, 1.2][:n]))
    a = ax[0]
    a.plot(t, col(rows, "max_c"), lw=1.2, color="#d62728", label="thermal max")
    a.plot(t, col(rows, "mean_c"), lw=1.0, color="#ff7f0e", label="thermal mean")
    a.plot(t, col(rows, "ambient_c"), lw=1.2, color="#1f77b4", label="ambient (SHT31)")
    thr = [(x + d) if x is not None and d is not None else None
           for x, d in zip(col(rows, "ambient_c"), col(rows, "delta_c"))]
    a.plot(t, thr, lw=0.8, ls="--", color="#7f7f7f", label="ambient + delta_c (hot pixel)")
    for i, k in enumerate(k for k in rows[0] if k.startswith("probe") and k.endswith("_c")):
        a.plot(t, col(rows, k), lw=0.9, label=k.replace("_c", ""), color=["#2ca02c", "#9467bd", "#8c564b"][i % 3])
    if "ir_c" in rows[0]:
        a.plot(t, col(rows, "ir_c"), lw=0.9, color="#e377c2", label="IR (MLX90614)")
    a.set_ylabel("temperature (C)")
    a.legend(loc="upper left", fontsize=8, ncol=3)
    a.grid(alpha=0.3)
    a.set_title(title)

    ax[1].plot(t, col(rows, "rh_pct"), lw=1.0, color="#17becf")
    ax[1].set_ylabel("RH (%)")
    ax[1].grid(alpha=0.3)

    ax[2].plot(t, col(rows, "smoke_v"), lw=1.0, color="#555555", label="MQ-2 output")
    base = col(rows, "smoke_baseline_v")
    ax[2].plot(t, base, lw=0.8, ls="--", color="#1f77b4", label="baseline")
    ax[2].plot(t, [b + 0.30 if b is not None else None for b in base], lw=0.8, ls=":", color="#d62728",
               label="baseline + 0.30 V (smoke)")
    ax[2].set_ylabel("MQ-2 (V)")
    ax[2].legend(loc="upper left", fontsize=8, ncol=3)
    ax[2].grid(alpha=0.3)

    ax[3].step(t, col(rows, "level"), where="post", color="#d62728", lw=1.2)
    ax[3].set_yticks([0, 1, 2, 3], ["normal", "caution", "warning", "danger"])
    ax[3].set_ylim(-0.3, 3.3)
    ax[3].grid(alpha=0.3)
    if supply:
        ax[4].plot([datetime.fromtimestamp(t) for t, _ in supply], [v for _, v in supply], lw=1.0, color="#2ca02c")
        ax[4].axhline(4.75, ls=":", color="#d62728", lw=0.8)
        ax[4].set_ylabel("Pi 5 input (V)")
        ax[4].grid(alpha=0.3)
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax[-1].set_xlabel("time (board local)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_thermal(trows: list[dict], path: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frames = []
    for r in trows:
        px = [num(r.get(f"p{i:02d}")) for i in range(64)]
        if all(v is not None for v in px):
            frames.append((r["_t"], px))
    if not frames:
        raise ValueError("빈 칸 없는 열화상 줄이 없음")
    hot_t, hot = max(frames, key=lambda f: max(f[1]))
    mean = [sum(f[1][i] for f in frames) / len(frames) for i in range(64)]
    peak = [max(f[1][i] for f in frames) for i in range(64)]
    grids = [(f"hottest frame {datetime.fromtimestamp(hot_t):%H:%M:%S}", hot), ("mean", mean), ("per-pixel max", peak)]
    vmin = min(min(g) for _, g in grids)
    vmax = max(max(g) for _, g in grids)
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.6))
    for a, (name, g) in zip(ax, grids):
        m = [g[y * 8:(y + 1) * 8] for y in range(8)]
        im = a.imshow(m, cmap="inferno", vmin=vmin, vmax=vmax)
        for y in range(8):
            for x in range(8):
                v = m[y][x]
                a.text(x, y, f"{v:.0f}", ha="center", va="center", fontsize=7,
                       color="black" if v > vmin + 0.6 * (vmax - vmin) else "white")
        a.set_title(name, fontsize=10)
        a.set_xticks(range(8))
        a.set_yticks(range(8))
    fig.colorbar(im, ax=ax, shrink=0.8, label="C")
    fig.suptitle(f"{title}  ({len(frames)} frames, p00 = top left)")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fire-detect 기록 그래프")
    ap.add_argument("--dir", default="~/fire_logs")
    ap.add_argument("--day", help="YYYYmmdd (UTC). 없으면 가장 새 날짜")
    ap.add_argument("--last", type=float, help="마지막 N 분만")
    ap.add_argument("--out", help="PNG 폴더 (기본 <dir>/plots)")
    a = ap.parse_args(argv)
    d = Path(os.path.expanduser(a.dir))
    days = sorted({p.stem.split("_")[1] for p in d.glob("fire_*.csv") if p.stem.split("_")[1].isdigit()})
    if not days:
        print(f"{d} 에 fire_*.csv 기록이 없습니다.")
        return 1
    day = a.day or days[-1]
    rows = read_rows(day_files(d, "fire", day), None)
    if not rows:
        print(f"{day} 기록이 비어 있습니다.")
        return 1
    t_from = rows[-1]["_t"] - a.last * 60 if a.last else None
    if t_from is not None:
        rows = [r for r in rows if r["_t"] >= t_from]
    trows = read_rows(day_files(d, "thermal", day), t_from)
    out = Path(os.path.expanduser(a.out)) if a.out else d / "plots"
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"_last{a.last:g}m" if a.last else ""
    supply = read_supply(d, day, t_from)
    print(summarize(rows, len(trows)))
    if supply:
        vs = [v for _, v in supply]
        print(f"  Pi 5 입력 전압 {min(vs):.2f} ~ {max(vs):.2f} V (4.75 V 아래로 자주 내려가면 보조배터리나 케이블이 약함)")
    title = f"{rows[0].get('device_id', '')} {day} (UTC day)"
    try:
        p1 = out / f"fire_{day}{suffix}.png"
        plot_status(rows, p1, title, supply)
        print(f"그래프: {p1}")
        if trows:
            p2 = out / f"thermal_{day}{suffix}.png"
            plot_thermal(trows, p2, title)
            print(f"열화상: {p2}")
    except ImportError:
        print("matplotlib 이 없어 그래프는 건너뜀: sudo apt install python3-matplotlib")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
