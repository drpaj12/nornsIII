"""Section 10.2 of docs/plan/placers.md: SA start-temperature selection table and the held-out report.

Usage: python3 scripts/placers_temp_table.py sel  TAG DESIGN [DESIGN ...]      # seeds 1-3: Q(T) and max WL ratio per T
       python3 scripts/placers_temp_table.py held TAG DESIGN [...] --temps 1,30 # seeds 4-6: median and min-max per design and arm
Reads data/placers/<TAG>_<design>.json. Q(T) = geometric mean over (design, seed) pairs of (WL x CPD ext_nextpnr_sa at T) /
(WL x CPD vpr_sa_reread, same design and seed). Ties (under 1%) go to the smaller T.
"""
import json
import math
import statistics as st
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "placers"
mode, tag = sys.argv[1], sys.argv[2]
rest = sys.argv[3:]
temps_arg = None
if "--temps" in rest:
    i = rest.index("--temps")
    temps_arg = [float(t) for t in rest[i + 1].split(",")]
    rest = rest[:i] + rest[i + 2:]
designs = rest
D = {d: json.loads((DATA / f"{tag}_{d}.json").read_text()) for d in designs}


def idx(d):
    return {(r["arm"], r["seed"], r.get("starttemp")): r for r in D[d]["runs"]}


def wlcpd(r):
    return r["wl"] * r["cpd_ns"]


if mode == "sel":
    temps = sorted({r["starttemp"] for d in designs for r in D[d]["runs"] if r["arm"] == "ext_nextpnr_sa"})
    res = {}
    for T in temps:
        qs, wls, rows = [], [], []
        for d in designs:
            ix = idx(d)
            for s in (1, 2, 3):
                e, c = ix.get(("ext_nextpnr_sa", s, T)), ix.get(("vpr_sa_reread", s, None))
                if not (e and c and e.get("routed_ok") and c.get("routed_ok")):
                    rows.append((d, s, None, None))
                    continue
                qs.append(wlcpd(e) / wlcpd(c))
                wls.append(e["wl"] / c["wl"])
                rows.append((d, s, e["wl"] / c["wl"], wlcpd(e) / wlcpd(c)))
        n_bad = sum(1 for r in rows if r[2] is None)
        Q = math.exp(sum(math.log(q) for q in qs) / len(qs)) if qs else float("nan")
        res[T] = (Q, max(wls) if wls else float("nan"), n_bad, rows)
    print(f"{'T':>6} {'Q(T)':>8} {'max WL ratio':>13} {'missing/illegal':>16}  per-pair WL ratio (design seed)")
    for T in temps:
        Q, mx, nb, rows = res[T]
        print(f"{T:6g} {Q:8.3f} {mx:13.2f} {nb:16d}  " + " ".join(f"{r[0][3:8]}{r[1]}:{r[2]:.2f}" if r[2] else f"{r[0][3:8]}{r[1]}:NA" for r in rows))
    best = min(temps, key=lambda T: (res[T][0], T))
    for T in sorted(temps):  # tie rule: smallest T within 1% of the minimum
        if res[T][0] <= res[best][0] * 1.01:
            best = T
            break
    print(f"\nchoice (smallest Q, ties under 1% to the smaller T): T = {best:g}; max WL ratio there {res[best][1]:.2f}; "
          f"2x rule {'met' if res[best][1] <= 2.0 and res[best][2] == 0 else 'NOT met'}")
else:
    temps = temps_arg
    print("seeds 4-6: median [min-max] over the 3 seeds")
    print(f"{'design':18s} {'arm':22s} {'WL':>20s} {'W':>14s} {'CPD ns':>20s} {'WLxCPD':>22s}  routed")
    for d in designs:
        ix = idx(d)
        for arm, T in [("vpr_sa", None), ("vpr_sa_reread", None)] + [("ext_nextpnr_sa", t) for t in temps]:
            rs = [ix.get((arm, s, T)) for s in (4, 5, 6)]
            ok = [r for r in rs if r and r.get("routed_ok")]
            if not ok:
                print(f"{d:18s} {arm + (f' T={T:g}' if T else ''):22s} no legal runs")
                continue
            def cell(vals, fmt="{:.0f}"):
                return f"{fmt.format(st.median(vals))} [{fmt.format(min(vals))}-{fmt.format(max(vals))}]"
            print(f"{d:18s} {arm + (f' T={T:g}' if T else ''):22s} {cell([r['wl'] for r in ok]):>20s} {cell([r['W'] for r in ok]):>14s} "
                  f"{cell([r['cpd_ns'] for r in ok], '{:.3f}'):>20s} {cell([wlcpd(r) for r in ok]):>22s}  {len(ok)}/3")
