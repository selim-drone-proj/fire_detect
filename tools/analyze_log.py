"""
analyze_log.py - 정상 충전 기록으로 판정 기준값(delta_c, abs_limit_c, smoke_dv) 정하기

    python3 tools/analyze_log.py ~/fire_logs/fire_2026101*.csv

파워뱅크를 평소처럼 여러 번 충전하면서 며칠 기록한 뒤 돌린다. 화재 실험 기록은 넣지 말 것.
출력: 정상일 때 (최고 화소 - 주변), (접촉 프로브 최고 - 주변), (적외선 - 주변), 연기 상승폭의 분포와 제안값,
그리고 그동안 난 경보(= 오경보 후보). 프로브, 적외선 열이 없는 예전 기록이면 그 부분은 건너뛴다.
제안값은 출발점일 뿐이다. 설정에 넣은 뒤 다시 며칠 돌려 오경보가 없는지 확인할 것.
"""
from __future__ import annotations

import csv
import math
import sys


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def num(s: str):
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def analyze(paths: list[str]) -> dict:
    rise, smoke, maxc, alarms = [], [], [], []
    p_rise, p_max, ir_rise, ir_max = [], [], [], []
    n = 0
    t_first = t_last = None
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                n += 1
                t = num(r["time_unix"])
                t_first = t if t_first is None else min(t_first, t)
                t_last = t if t_last is None else max(t_last, t)
                m, a = num(r["max_c"]), num(r["ambient_c"])
                if m is not None and a is not None:
                    rise.append(m - a)
                    maxc.append(m)
                probes = [num(v) for k, v in r.items() if k and k.startswith("probe") and k.endswith("_c")]
                probes = [x for x in probes if x is not None]
                if probes and a is not None:
                    p_rise.append(max(probes) - a)
                    p_max.append(max(probes))
                ir = num(r.get("ir_c"))
                if ir is not None and a is not None:
                    ir_rise.append(ir - a)
                    ir_max.append(ir)
                v, b = num(r["smoke_v"]), num(r["smoke_baseline_v"])
                if v is not None and b is not None and not int(r["flags"] or 0) & 1:     # 예열 중 제외
                    smoke.append(v - b)
                if r["level"] not in ("0", ""):
                    alarms.append((r["time_iso"], r["level"], r["reason"]))
    return dict(n=n, hours=((t_last or 0) - (t_first or 0)) / 3600.0, rise=rise, smoke=smoke, maxc=maxc,
                alarms=alarms, p_rise=p_rise, p_max=p_max, ir_rise=ir_rise, ir_max=ir_max)


def delta_for(rise: list[float]):
    return max(5.0, math.ceil(pct(rise, 99.9) + 3.0)) if rise else None


def limit_for(maxc: list[float]):
    return min(70.0, max(60.0, math.ceil(max(maxc) + 15.0))) if maxc else None


def suggest(a: dict) -> dict:
    s999 = pct(a["smoke"], 99.9)
    return dict(
        delta_c=delta_for(a["rise"]),
        abs_limit_c=limit_for(a["maxc"]),
        smoke_dv=max(0.2, round(2.0 * s999, 2)) if a["smoke"] else None,
        probe_delta_c=delta_for(a.get("p_rise", [])),
        probe_abs_limit_c=limit_for(a.get("p_max", [])),
        ir_delta_c=delta_for(a.get("ir_rise", [])),
        ir_abs_limit_c=limit_for(a.get("ir_max", [])),
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    a = analyze(argv)
    s = suggest(a)
    print(f"기록 {a['n']} 줄, 약 {a['hours']:.1f} 시간")
    if a["hours"] < 24:
        print("  주의: 하루 이상, 충전 여러 번을 담은 기록이 좋다")
    print("\n최고 화소 - 주변 온도 (℃)")
    for p in (50, 90, 99, 99.9, 100):
        print(f"  p{p:<5} {pct(a['rise'], p):6.2f}")
    print(f"  최고 화소 최댓값 {max(a['maxc']) if a['maxc'] else float('nan'):.2f} ℃")
    for key, mx, title in (("p_rise", "p_max", "접촉 프로브 최고 - 주변 온도 (℃)"), ("ir_rise", "ir_max", "적외선 - 주변 온도 (℃)")):
        if a[key]:
            print(f"\n{title}")
            for p in (50, 90, 99, 99.9, 100):
                print(f"  p{p:<5} {pct(a[key], p):6.2f}")
            print(f"  최댓값 {max(a[mx]):.2f} ℃")
    print("\n연기 상승폭 smoke_v - 기준 (V)")
    for p in (50, 99, 99.9, 100):
        print(f"  p{p:<5} {pct(a['smoke'], p):6.3f}")
    print("\n제안값 (config.yaml 의 alarm:)")
    print(f"  delta_c: {s['delta_c']}        # 정상 p99.9 + 3 ℃, 최소 5")
    print(f"  abs_limit_c: {s['abs_limit_c']}    # 정상 최댓값 + 15 ℃, 60~70 사이")
    print(f"  smoke_dv: {s['smoke_dv']}       # 정상 p99.9 의 2 배, 최소 0.2 V")
    if s["probe_delta_c"] is not None:
        print(f"  probe_delta_c: {s['probe_delta_c']}   # 접촉 프로브. 같은 규칙")
        print(f"  probe_abs_limit_c: {s['probe_abs_limit_c']}")
    if s["ir_delta_c"] is not None:
        print(f"  ir_delta_c: {s['ir_delta_c']}      # 적외선. 같은 규칙")
        print(f"  ir_abs_limit_c: {s['ir_abs_limit_c']}")
    if a["alarms"]:
        print(f"\n이 기록 중 경보 {len(a['alarms'])} 건 (정상 충전이었다면 오경보):")
        for t, lv, why in a["alarms"][:20]:
            print(f"  {t} 단계 {lv} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
