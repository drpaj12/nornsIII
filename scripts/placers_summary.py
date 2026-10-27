"""Section 10.4 summaries of docs/plan/placers.md: per design and per family, from data/placers/main_<design>.json.

Usage: python3 scripts/placers_summary.py [--seeds 4,5,6] [--out data/placers/main_summary.json]
Per design and arm: median [min-max] over the chosen seeds (default 4-6, held out) of WL, W, CPD, WL x CPD, and placement seconds
(VPR AP or SA time; for the external arms also the nextpnr placer seconds). An arm with fewer than 5 of 6 legal seeds is dropped for
that design (Section 5 rule 4) and listed. Per family: geometric mean over designs of (arm median / own-family reread median) and
(arm median / own-family VPR median) for WL, CPD and WL x CPD, with a percentile bootstrap over designs (10000 resamples, seed 20261026,
95%). The 2x rule is evaluated per design on the medians and per run. Every printed block repeats the H0 caption.
"""
import argparse
import json
import math
import random
import statistics as st
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "placers"
DESIGNS = ["ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B",
           "sha", "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2"]
FAM = {"analytic": ["vpr_ap", "vpr_ap_reread", "ext_nextpnr_heap"], "annealing": ["vpr_sa", "vpr_sa_reread", "ext_nextpnr_sa"]}
VPRARM = {"analytic": "vpr_ap", "annealing": "vpr_sa"}
CTRL = {"analytic": "vpr_ap_reread", "annealing": "vpr_sa_reread"}
CAPTION = ("H0: adders, multipliers and RAMs are fixed at the positions of the VPR analytic placer (vpr_ap, seed 1), as are the pads, in both "
           "external arms and for every seed. nextpnr therefore places only the LUT/flip-flop logic, around hard blocks and pads that VPR's "
           "analytic placer chose. The external arms inherit that part of VPR's solution; the annealing-family external arm inherits it from "
           "the analytic family. nextpnr has no timing model; both VPR families are timing-driven.")
ap = argparse.ArgumentParser()
ap.add_argument("--seeds", default="4,5,6")
ap.add_argument("--out")
ap.add_argument("--sa-temp", type=float, default=100.0)
a = ap.parse_args()
SEEDS = [int(s) for s in a.seeds.split(",")]

runs = {}
conv = {}
for d in DESIGNS:
    p = DATA / f"main_{d}.json"
    if not p.exists():
        continue
    j = json.loads(p.read_text())
    conv[d] = j.get("converter", {})
    for r in j["runs"]:
        T = r.get("starttemp")
        if r["arm"] == "ext_nextpnr_sa" and T != a.sa_temp:
            continue
        runs[(d, r["arm"], r["seed"])] = r


def place_s(r):
    v = r.get("ap_s") if r.get("ap_s") is not None else r.get("sa_place_s")
    return v


def ext_s(r):
    n = r.get("nextpnr")
    if not n:
        return None
    return (n.get("heap_s") or n.get("init_s") or 0) + (n.get("sa_s") or 0)


def med(xs):
    return st.median(xs)


summary = {}
for d in DESIGNS:
    for fam, arms in FAM.items():
        for arm in arms:
            allr = [runs.get((d, arm, s)) for s in range(1, 7)]
            ok_all = [r for r in allr if r and r.get("rc") == 0 and r.get("routed_ok") and not r.get("reader_warnings")]
            held = [runs.get((d, arm, s)) for s in SEEDS]
            ok = [r for r in held if r and r.get("rc") == 0 and r.get("routed_ok") and not r.get("reader_warnings")]
            if len(ok_all) < 5 and a.seeds == "4,5,6" or not ok:
                summary[(d, arm)] = {"dropped": True, "legal_of_6": len(ok_all), "errors": sorted({r.get("error", "") for r in allr if r and r.get("error")})}
                continue
            m = {"n": len(ok), "legal_of_6": len(ok_all)}
            for k, f in (("wl", lambda r: r["wl"]), ("W", lambda r: r["W"]), ("cpd", lambda r: r["cpd_ns"]),
                         ("wlcpd", lambda r: r["wl"] * r["cpd_ns"]), ("place_s", place_s)):
                xs = [f(r) for r in ok if f(r) is not None]
                m[k] = {"med": med(xs), "min": min(xs), "max": max(xs)} if xs else None
            xs = [ext_s(r) for r in ok if ext_s(r) is not None]
            m["ext_s"] = {"med": med(xs), "min": min(xs), "max": max(xs)} if xs else None
            summary[(d, arm)] = m


def cell(m, k, fmt):
    if not m or m.get("dropped") or not m.get(k):
        return "-"
    return fmt.format(m[k]["med"]) + " [" + fmt.format(m[k]["min"]) + "-" + fmt.format(m[k]["max"]) + "]"


print(f"Seeds {a.seeds}: median [min-max]. ext_nextpnr_sa = --starttemp {a.sa_temp:g}.\n{CAPTION}\n")
for fam, arms in FAM.items():
    print(f"== family {fam}")
    print(f"{'design':17s} {'arm':17s} {'WL':>22s} {'W':>14s} {'CPD ns':>20s} {'WLxCPD':>24s} {'VPR place s':>16s} {'nextpnr s':>18s} legal")
    for d in DESIGNS:
        for arm in arms:
            m = summary.get((d, arm))
            if m is None:
                continue
            if m.get("dropped"):
                print(f"{d:17s} {arm:17s} DROPPED legal {m['legal_of_6']}/6 {m['errors'][:1]}")
                continue
            print(f"{d:17s} {arm:17s} {cell(m, 'wl', '{:.0f}'):>22s} {cell(m, 'W', '{:.0f}'):>14s} {cell(m, 'cpd', '{:.2f}'):>20s} "
                  f"{cell(m, 'wlcpd', '{:.0f}'):>24s} {cell(m, 'place_s', '{:.2f}'):>16s} {cell(m, 'ext_s', '{:.2f}'):>18s} {m['legal_of_6']}/6")
    print()

rng = random.Random(20261026)
out = {"seeds": SEEDS, "sa_temp": a.sa_temp, "caption": CAPTION, "families": {}, "designs": {}}
for (d, arm), m in summary.items():
    out["designs"].setdefault(d, {})[arm] = m
for fam, arms in FAM.items():
    print(f"== family {fam}: geometric mean over designs of arm median / reference median (95% percentile bootstrap over designs)")
    for arm in arms:
        for ref_name, ref in (("own-family reread", CTRL[fam]), ("own-family VPR", VPRARM[fam])):
            if arm == ref:
                continue
            if ref_name == "own-family VPR" and arm == CTRL[fam]:
                pass
            res = {}
            for k in ("wl", "cpd", "wlcpd"):
                rat = []
                for d in DESIGNS:
                    x, y = summary.get((d, arm)), summary.get((d, ref))
                    if x and y and not x.get("dropped") and not y.get("dropped") and x.get(k) and y.get(k):
                        rat.append((d, x[k]["med"] / y[k]["med"]))
                if not rat:
                    continue
                logs = [math.log(v) for _, v in rat]
                g = math.exp(sum(logs) / len(logs))
                bs = sorted(math.exp(sum(rng.choice(logs) for _ in logs) / len(logs)) for _ in range(10000))
                res[k] = {"n_designs": len(rat), "gmean": g, "lo": bs[249], "hi": bs[9749],
                          "over_2x": [d for d, v in rat if k == "wl" and v > 2.0]}
            if res:
                out["families"].setdefault(fam, {})[f"{arm}_vs_{ref}"] = res
                print(f"  {arm:17s} / {ref:14s}: " + "; ".join(
                    f"{k} {v['gmean']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}] n={v['n_designs']}" for k, v in res.items())
                    + ("; WL>2x on " + ",".join(res['wl']['over_2x']) if res.get("wl") and res["wl"]["over_2x"] else ""))
    print()
# 2x rule per run
fires = []
for (d, arm, s), r in sorted(runs.items()):
    for fam in FAM:
        if arm in ("ext_nextpnr_heap", "ext_nextpnr_sa") and arm in FAM[fam]:
            c = runs.get((d, CTRL[fam], s))
            if c and r.get("wl") and c.get("wl") and r["wl"] / c["wl"] > 2.0:
                fires.append((d, arm, s, round(r["wl"] / c["wl"], 2)))
out["two_x_runs"] = fires
print("2x rule (per run, all seeds): ", fires if fires else "no run over 2x")
if a.out:
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
