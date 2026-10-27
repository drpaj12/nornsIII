"""Section 10.4 summaries of docs/plan/placers.md: per design and per family, from data/placers/main_<design>.json
with the fix-round records of data/placers/fix1_<design>.json (section 10.10) replacing the main records of the same (arm, seed, T).

Usage: python3 scripts/placers_summary.py [--seeds 4,5,6] [--out data/placers/main_summary.json]
       python3 scripts/placers_summary.py --rescan          # list every rejected ext record of the main_ files, no fix1 override
       python3 scripts/placers_summary.py --sensitivity     # reread controls of the 4 normalised designs, old (main_) against new (fix1_)
Per design and arm: median [min-max] over the chosen seeds (default 4-6, held out) of WL, W, CPD, WL x CPD, and placement seconds
(VPR AP or SA time; for the external arms also the nextpnr placer seconds). Legality drop rule (dated clarification in section 10.10):
an arm with fewer than 5 of the 6 seeds 1-6 legal (rc 0, routed, no reader warning) is dropped for that design when the held-out
seeds 4-6 are reported; the legal count is over seeds 1-6 whichever seeds are reported; for any other seed list only an arm with no
legal run is dropped. Per family: geometric mean over designs of (arm median / own-family reread median) and (arm median / own-family
VPR median) for WL, CPD and WL x CPD, with two percentile bootstraps (10000 resamples, seed 20261026, 95%): (a) over designs only
(the pre-registered figure) and (b) two-level, designs resampled, then within each drawn design the seeds of the arm and of the
reference resampled independently. Every mean is reported for all eligible designs and for the designs without the n=20 designs
(BLE slots per tile 20, section 10.8). Every printed block repeats the H0 caption.
Record assertion (section 10.10): every ext_* record that has a readback must have fallback_ref 0, const_verbatim 0, anchor_moved 0 and
pad_moved 0; otherwise the summary stops (exit 2) and lists the records, it does not average them.
"""
import argparse
import json
import math
import random
import statistics as st
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "placers"
DESIGNS = ["ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B",
           "sha", "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2"]
FAM = {"analytic": ["vpr_ap", "vpr_ap_reread", "ext_nextpnr_heap"], "annealing": ["vpr_sa", "vpr_sa_reread", "ext_nextpnr_sa"]}
VPRARM = {"analytic": "vpr_ap", "annealing": "vpr_sa"}
CTRL = {"analytic": "vpr_ap_reread", "annealing": "vpr_sa_reread"}
NORMALISED = ["diffeq1", "diffeq2", "or1200", "raygentop"]  # designs whose reread controls were re-run with the normalised file (10.10)
FAULTS = ("fallback_ref", "const_verbatim", "anchor_moved", "pad_moved")
CAPTION = ("H0: adders, multipliers and RAMs are fixed at the positions of the VPR analytic placer (vpr_ap, seed 1), as are the pads, in both "
           "external arms and for every seed. nextpnr therefore places only the LUT/flip-flop logic, around hard blocks and pads that VPR's "
           "analytic placer chose. The external arms inherit that part of VPR's solution; the annealing-family external arm inherits it from "
           "the analytic family. nextpnr has no timing model; both VPR families are timing-driven.")
ap = argparse.ArgumentParser()
ap.add_argument("--seeds", default="4,5,6")
ap.add_argument("--out")
ap.add_argument("--sa-temp", type=float, default=100.0)
ap.add_argument("--rescan", action="store_true")
ap.add_argument("--sensitivity", action="store_true")
ap.add_argument("--no-fix", action="store_true", help="ignore the fix1_ files (the main_ records only)")
a = ap.parse_args()
SEEDS = [int(s) for s in a.seeds.split(",")]


def load(use_fix, only_arms=None):
    """runs[(design, arm, seed)] = record; n20 = set of designs with 20 BLE slots; source[(d, arm, seed)] = 'main' | 'fix1'."""
    runs, src, n20, conv = {}, {}, set(), {}
    for d in DESIGNS:
        for tag in ("main", "fix1") if use_fix else ("main",):
            p = DATA / f"{tag}_{d}.json"
            if not p.exists():
                continue
            j = json.loads(p.read_text())
            if tag == "main":
                conv[d] = j.get("converter", {})
                if j.get("ble_per_tile") == 20:
                    n20.add(d)
            fixed = {(r["arm"], r["seed"]) for r in j["runs"]} if tag == "fix1" else set()
            if tag == "fix1":
                for k in [k for k in runs if k[0] == d and (k[1], k[2]) in fixed]:
                    runs.pop(k)
            for r in j["runs"]:
                if only_arms and r["arm"] not in only_arms:
                    continue
                if r["arm"] == "ext_nextpnr_sa" and r.get("starttemp") != a.sa_temp:
                    continue
                runs[(d, r["arm"], r["seed"])] = r
                src[(d, r["arm"], r["seed"])] = tag
    return runs, src, n20


def faults(runs):
    bad = []
    for (d, arm, s), r in sorted(runs.items()):
        rb = r.get("readback")
        if arm.startswith("ext_") and rb and any(rb.get(k) for k in FAULTS):
            bad.append((d, arm, s, {k: rb[k] for k in FAULTS if rb.get(k)}))
    return bad


def place_s(r):
    return r.get("ap_s") if r.get("ap_s") is not None else r.get("sa_place_s")


def ext_s(r):
    n = r.get("nextpnr")
    return None if not n else (n.get("heap_s") or n.get("init_s") or 0) + (n.get("sa_s") or 0)


def legal(r):
    return bool(r and r.get("rc") == 0 and r.get("routed_ok") and not r.get("reader_warnings"))


MET = (("wl", lambda r: r["wl"]), ("W", lambda r: r["W"]), ("cpd", lambda r: r["cpd_ns"]),
       ("wlcpd", lambda r: r["wl"] * r["cpd_ns"]), ("place_s", place_s))


def summarise(runs):
    summary = {}
    for d in DESIGNS:
        for fam, arms in FAM.items():
            for arm in arms:
                allr = [runs.get((d, arm, s)) for s in range(1, 7)]
                ok_all = [r for r in allr if legal(r)]
                ok = [runs[(d, arm, s)] for s in SEEDS if legal(runs.get((d, arm, s)))]
                if (len(ok_all) < 5 and a.seeds == "4,5,6") or not ok:
                    summary[(d, arm)] = {"dropped": True, "legal_of_6": len(ok_all), "errors": sorted({r.get("error", "") for r in allr if r and r.get("error")})}
                    continue
                m = {"n": len(ok), "legal_of_6": len(ok_all), "vals": {}}
                for k, f in MET:
                    xs = [f(r) for r in ok if f(r) is not None]
                    m[k] = {"med": st.median(xs), "min": min(xs), "max": max(xs)} if xs else None
                    m["vals"][k] = xs
                xs = [ext_s(r) for r in ok if ext_s(r) is not None]
                m["ext_s"] = {"med": st.median(xs), "min": min(xs), "max": max(xs)} if xs else None
                summary[(d, arm)] = m
    return summary


def cell(m, k, fmt):
    if not m or m.get("dropped") or not m.get(k):
        return "-"
    return fmt.format(m[k]["med"]) + " [" + fmt.format(m[k]["min"]) + "-" + fmt.format(m[k]["max"]) + "]"


def pct(bs):
    bs = sorted(bs)
    return bs[249], bs[9749]


def family_means(summary, n20, rng):
    """{fam: {pair: {subset: {metric: {...}}}}}; subsets 'all' and 'no_n20'."""
    out = {}
    for fam, arms in FAM.items():
        for arm in arms:
            for ref in (CTRL[fam], VPRARM[fam]):
                if arm == ref:
                    continue
                for subset in ("all", "no_n20"):
                    res = {}
                    for k in ("wl", "cpd", "wlcpd"):
                        rat = []
                        for d in DESIGNS:
                            if subset == "no_n20" and d in n20:
                                continue
                            x, y = summary.get((d, arm)), summary.get((d, ref))
                            if x and y and not x.get("dropped") and not y.get("dropped") and x.get(k) and y.get(k):
                                rat.append((d, x[k]["med"] / y[k]["med"], x["vals"][k], y["vals"][k]))
                        if not rat:
                            continue
                        logs = [math.log(v) for _, v, _, _ in rat]
                        g = math.exp(sum(logs) / len(logs))
                        lo1, hi1 = pct(math.exp(sum(rng.choice(logs) for _ in logs) / len(logs)) for _ in range(10000))
                        b2 = []
                        for _ in range(10000):
                            ls = []
                            for _d, _v, xv, yv in (rng.choice(rat) for _ in rat):
                                ls.append(math.log(st.median(rng.choice(xv) for _ in xv) / st.median(rng.choice(yv) for _ in yv)))
                            b2.append(math.exp(sum(ls) / len(ls)))
                        lo2, hi2 = pct(b2)
                        res[k] = {"n_designs": len(rat), "gmean": g, "lo": lo1, "hi": hi1, "lo2": lo2, "hi2": hi2,
                                  "over_2x": [d for d, v, _, _ in rat if k == "wl" and v > 2.0]}
                    if res:
                        out.setdefault(fam, {}).setdefault(f"{arm}_vs_{ref}", {})[subset] = res
    return out


def print_family(fm, title):
    for fam in FAM:
        print(f"== family {fam}: {title}")
        for pair, subs in fm.get(fam, {}).items():
            for subset, label in (("all", "all eligible designs"), ("no_n20", "without the n=20 designs (blob_merge, stereovision0)")):
                res = subs.get(subset)
                if not res:
                    continue
                print(f"  {pair.replace('_vs_', ' / '):38s} [{label}]")
                for k, v in res.items():
                    print(f"      {k:6s} {v['gmean']:.3f}  design-bootstrap [{v['lo']:.3f}, {v['hi']:.3f}] (pre-registered)  "
                          f"two-level [{v['lo2']:.3f}, {v['hi2']:.3f}]  n={v['n_designs']}"
                          + (f"  WL>2x on {','.join(v['over_2x'])}" if v["over_2x"] else ""))
        print()


if a.rescan:
    runs, _, _ = load(False)
    bad = faults(runs)
    print(f"rescan of data/placers/main_*.json: {sum(1 for k in runs if k[1].startswith('ext_'))} ext records, {len(bad)} rejected")
    for d, arm, s, f in bad:
        print(f"  REJECT {d:16s} {arm:17s} seed {s}  rc {runs[(d, arm, s)].get('rc')}  {f}")
    sys.exit(0)

runs, src, n20 = load(not a.no_fix)
bad = faults(runs)
if bad:
    print(f"ASSERTION FAILED: {len(bad)} ext record(s) with a stale or faulty readback (fallback_ref/const_verbatim/anchor_moved/pad_moved must be 0):", file=sys.stderr)
    for d, arm, s, f in bad:
        print(f"  {d} {arm} seed {s}: {f}", file=sys.stderr)
    sys.exit(2)

if a.sensitivity:
    main_only, _, _ = load(False)
    new = runs
    # old = the new data with only the reread controls of the four normalised designs taken from the main_ records (the raw-file runs),
    # so that the family rows differ by the reread change alone (the stereovision1 heap correction is in both)
    old = {k: (main_only[k] if (k[0] in NORMALISED and k[1] in CTRL.values() and k in main_only) else v) for k, v in new.items()}
    same = sum(1 for k, v in new.items() if k[0] in NORMALISED and k[1] in ("vpr_ap", "vpr_sa") and k in main_only and v.get("wl") == main_only[k].get("wl") and v.get("cpd_ns") == main_only[k].get("cpd_ns"))
    tot = sum(1 for k in new if k[0] in NORMALISED and k[1] in ("vpr_ap", "vpr_sa") and k in main_only)
    print(f"Determinism check: {same} of {tot} re-run vpr_ap/vpr_sa records of the four designs equal the main_ record in WL and CPD.")
    print("Reread controls of the four normalised designs, held-out seeds 4-6 median: old (raw file, main_) -> new (normalised file, fix1_)")
    print(f"{'design':10s} {'arm':14s} {'WL old':>9s} {'WL new':>9s} {'CPD old':>8s} {'CPD new':>8s} {'WLxCPD old':>11s} {'WLxCPD new':>11s}")
    for d in NORMALISED:
        for arm in ("vpr_ap_reread", "vpr_sa_reread"):
            row = []
            for rr in (old, new):
                xs = [rr[(d, arm, s)] for s in SEEDS if legal(rr.get((d, arm, s)))]
                row.append((st.median(r["wl"] for r in xs), st.median(r["cpd_ns"] for r in xs), st.median(r["wl"] * r["cpd_ns"] for r in xs)) if xs else (float("nan"),) * 3)
            print(f"{d:10s} {arm:14s} {row[0][0]:9.0f} {row[1][0]:9.0f} {row[0][1]:8.3f} {row[1][1]:8.3f} {row[0][2]:11.0f} {row[1][2]:11.0f}")
    rng = random.Random(20261026)
    s_old, s_new = summarise(old), summarise(new)
    fo, fn = family_means(s_old, n20, random.Random(20261026)), family_means(s_new, n20, random.Random(20261026))
    print("\nFamily means vs the reread control, old reread -> new reread (gmean; all eligible designs; design bootstrap):")
    for fam in FAM:
        for pair, subs in fn.get(fam, {}).items():
            if not pair.endswith("_vs_" + CTRL[fam]):
                continue
            for k in ("wl", "cpd", "wlcpd"):
                o, n = fo[fam][pair]["all"].get(k), subs["all"].get(k)
                if o and n:
                    print(f"  {pair.replace('_vs_', ' / '):38s} {k:6s} {o['gmean']:.3f} [{o['lo']:.3f}, {o['hi']:.3f}] n={o['n_designs']} -> {n['gmean']:.3f} [{n['lo']:.3f}, {n['hi']:.3f}] n={n['n_designs']}")
    sys.exit(0)

summary = summarise(runs)
print(f"Seeds {a.seeds}: median [min-max]. ext_nextpnr_sa = --starttemp {a.sa_temp:g}. Designs with n=20 BLE slots: {sorted(n20)}.\n{CAPTION}\n")
for fam, arms in FAM.items():
    print(f"== family {fam}")
    print(f"{'design':17s} {'arm':17s} {'WL':>22s} {'W':>14s} {'CPD ns':>20s} {'WLxCPD':>24s} {'VPR place s':>16s} {'nextpnr s':>18s} legal")
    for d in DESIGNS:
        for arm in arms:
            m = summary.get((d, arm))
            if m is None:
                continue
            tag = " n=20" if d in n20 and arm.startswith("ext_") else ""
            if m.get("dropped"):
                print(f"{d:17s} {arm:17s} DROPPED legal {m['legal_of_6']}/6 {m['errors'][:1]}")
                continue
            print(f"{d:17s} {arm:17s} {cell(m, 'wl', '{:.0f}'):>22s} {cell(m, 'W', '{:.0f}'):>14s} {cell(m, 'cpd', '{:.2f}'):>20s} "
                  f"{cell(m, 'wlcpd', '{:.0f}'):>24s} {cell(m, 'place_s', '{:.2f}'):>16s} {cell(m, 'ext_s', '{:.2f}'):>18s} {m['legal_of_6']}/6{tag}")
    print()

fm = family_means(summary, n20, random.Random(20261026))
out = {"seeds": SEEDS, "sa_temp": a.sa_temp, "caption": CAPTION, "n20_designs": sorted(n20), "families": fm, "designs": {}}
for (d, arm), m in summary.items():
    out["designs"].setdefault(d, {})[arm] = {k: v for k, v in m.items() if k != "vals"}
print_family(fm, "geometric mean over designs of arm median / reference median (95% percentile bootstrap, 10000 resamples)")
fires = []
for (d, arm, s), r in sorted(runs.items()):
    for fam in FAM:
        if arm in ("ext_nextpnr_heap", "ext_nextpnr_sa") and arm in FAM[fam]:
            c = runs.get((d, CTRL[fam], s))
            if legal(r) and legal(c) and r["wl"] / c["wl"] > 2.0:
                fires.append((d, arm, s, round(r["wl"] / c["wl"], 2)))
out["two_x_runs"] = fires
print("2x rule (per run, all seeds): ", fires if fires else "no run over 2x")
if a.out:
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
