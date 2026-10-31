"""Q-N5 statistics (docs/plan/q-n5-schabas-spare.md): per-run measures, ratios arm/stock per channel-width setting, CAD-style table
(geomean % win, W/L/T), VTR vs MCNC, bootstrap, Holm, verdicts, mechanism numbers. Reuses refresh_stats.py (same measures and bootstrap).

  python3 q5_stats.py --root OUT_ROOT --out OUT.json [--mimir-src DIR]

Run dirs: ROOT/vpr/q5<a|b>-<stock|s2|s4>/<design>/vpr_sa.s<seed>. Reads only; writes OUT.json.
"""
import argparse, gzip, json, math, random, re, sys
from pathlib import Path

import refresh_stats as rs

SETTINGS = ("a", "b")
ARMS = ("stock", "s2", "s4")
NONSTOCK = ("s2", "s4")
METRICS = ["cpd", "precpd", "ne90", "ne95", "ne99", "wl", "clbs"]   # precpd is reported with the family but the Holm family is the 6 of the plan
TESTED = ["cpd", "ne90", "ne95", "ne99", "wl", "clbs"]
DESCR = ["pack_s", "total_s", "wmin"]
BOOT_N, BOOT_SEED = 10000, 20261030
TIE = 0.005
NORNS15 = rs.NORNS15
SCHABAS = {"alu4", "apex2", "apex4", "bigkey", "clma", "des", "diffeq", "dsip", "elliptic", "ex1010", "ex5p", "frisc", "misex3", "pdc", "s298", "s38417", "s38584.1", "seq", "spla", "tseng"}


def wlt(ratios):
    w = sum(r < 1 - TIE for r in ratios)
    l = sum(r > 1 + TIE for r in ratios)
    return w, l, len(ratios) - w - l


def measures(rd, mt):
    m = rs.run_measures(rd, mt)
    if m is None:
        return None
    t = (rd / "vpr.out").read_text(errors="replace")
    p = re.search(r"Placement estimated critical path delay \(least slack\): ([\d.]+) ns", t)
    m["precpd"] = float(p.group(1)) if p else 0.0
    w = re.search(r"Best routing used a channel width factor of (\d+)\.", t)
    m["wmin"] = float(w.group(1)) if w else 0.0
    g = re.search(r"FPGA sized to (\d+) x (\d+)", t)
    m["grid"] = [int(g.group(1)), int(g.group(2))] if g else None
    sp = re.search(r"Norns spare: s=(\d+) n=(\d+) crit_min=\S+ N=(\d+) logic_clusters=(\d+) qualified=(\d+) closed_at_limit=(\d+) overshoot=(\d+) ble_total=(\d+)", t)
    if sp:
        m["spare"] = dict(zip(("s", "n", "N", "logic", "qualified", "closed", "overshoot", "ble_total"), map(int, sp.groups())))
    return m


def mech_share(rd):
    """Share of the atoms on near-critical paths (path delay >= 0.90 x the longest) that lie in a qualified (spare-room) cluster, and the base rate
    (share of all clustered atoms that lie in a qualified cluster). None without a dump or report."""
    dump, rpt = rd / "spare.dump", rd / "report_timing.setup.rpt"
    if not dump.is_file():
        return None
    text = rpt.read_text(errors="replace") if rpt.is_file() else (gzip.open(rd / "report_timing.setup.rpt.gz", "rt", errors="replace").read() if (rd / "report_timing.setup.rpt.gz").is_file() else None)
    if text is None:
        return None
    qual, allat = set(), 0
    for ln in dump.read_text().splitlines():
        f = ln.split("\t")
        atoms = f[4:]
        allat += len(atoms)
        if f[2] == "1":
            qual.update(atoms)
    paths = []
    for blk in text.split("#Path ")[1:]:
        arr = re.search(r"data arrival time\s+(-?[\d.]+)", blk)
        if not arr:
            continue
        names = set(re.findall(r"^([^\s.:]+)\.\S+ \(", blk, re.M))
        paths.append((float(arr.group(1)), names))
    if not paths:
        return None
    top = max(a for a, _ in paths)
    near = [n for a, n in paths if a >= 0.90 * top]
    occ = sum(len(n) for n in near)
    inq = sum(len(n & qual) for n in near)
    return {"near_paths": len(near), "near_atom_occ": occ, "in_qualified": inq, "share": inq / occ if occ else None, "base_rate": len(qual) / allat if allat else None}


def verdict(cpd, wl, suites):
    gain = cpd["hi"] < 1.0
    wl_ok = wl["est"] <= 1.02
    both = all(v < 1.0 for v in suites.values())
    if gain and wl_ok and cpd["holm_p"] < 0.05 and both:
        return "USEFUL"
    if gain and wl_ok:
        return "POSSIBLY GOOD"
    if gain:
        return "INCONCLUSIVE (CPD gain, cost clause fails: WL %.3f)" % wl["est"]
    if cpd["est"] < 1.0:
        return "INCONCLUSIVE (positive geomean, interval touches 1)"
    if cpd["lo"] > 1.0 or (cpd["lo"] >= 0.98 and cpd["hi"] <= 1.02):
        return "DISMISSED"
    return "INCONCLUSIVE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mimir-src", default=str(Path.home() / "odin3-ws/mimir"))
    a = ap.parse_args()
    sys.path.insert(0, a.mimir_src)
    from mimir import timing as mt
    rs.BOOT_N = BOOT_N
    root = Path(a.root)
    prep = json.loads((root / "prep.json").read_text())
    designs = [d for d, _ in json.loads((root / "order.json").read_text())]
    data, failed, mech = {}, [], {}
    for st in SETTINGS:
        for arm in ARMS:
            for d in designs:
                for s in (1, 2, 3):
                    rd = root / "vpr" / f"q5{st}-{arm}" / d / f"vpr_sa.s{s}"
                    if not rd.is_dir():
                        continue
                    m = measures(rd, mt)
                    if m is None:
                        txt = (rd / "vpr.out").read_text(errors="replace") if (rd / "vpr.out").is_file() else ""
                        err = re.findall(r"^.*(?:Error|error).*$", txt, re.M)[:2]
                        failed.append({"setting": st, "arm": arm, "design": d, "seed": s, "error": " | ".join(e.strip()[:200] for e in err)})
                        continue
                    m["grid_ok"] = m["grid"] == prep[d]["grid"]
                    data[(st, arm, d, s)] = m
                    if arm != "stock" and st == "a":
                        ms = mech_share(rd)
                        if ms:
                            mech[(arm, d, s)] = ms
    bad = {(f["setting"], f["arm"], f["design"]) for f in failed}
    res = {"failed": failed, "settings": {}, "n_runs": len(data), "grid_mismatch": [f"{k}" for k, v in data.items() if not v["grid_ok"]], "prep": prep}
    rnd = random.Random(BOOT_SEED)
    for st in SETTINGS:
        S = {"arms": {}, "per_design": {}}
        tests = []
        for arm in NONSTOCK:
            ratios = {m: {} for m in METRICS + DESCR}
            for d in designs:
                if (st, arm, d) in bad or (st, "stock", d) in bad:
                    continue
                for m in METRICS + DESCR:
                    rr = [data[(st, arm, d, s)][m] / data[(st, "stock", d, s)][m] for s in (1, 2, 3)
                          if (st, arm, d, s) in data and (st, "stock", d, s) in data and data[(st, "stock", d, s)][m] > 0 and data[(st, arm, d, s)][m] > 0]
                    if rr:
                        ratios[m][d] = rs.geomean(rr)
            S["per_design"][arm] = ratios
            A = {"n_designs": len(ratios["cpd"]), "pooled": {}, "suites": {}, "schabas": {}}
            for m in METRICS + DESCR:
                v = list(ratios[m].values())
                if not v:
                    continue
                est, lo, hi, p = rs.boot(v, rnd)
                A["pooled"][m] = {"est": est, "lo": lo, "hi": hi, "p": p, "n": len(v), "win_pct": 100 * (1 - est), "wlt": wlt(v)}
                for suite, sel in (("vtr15", lambda d: d in NORNS15), ("mcnc20", lambda d: d not in NORNS15)):
                    sv = [r for d, r in ratios[m].items() if sel(d)]
                    if sv:
                        e2, l2, h2, _ = rs.boot(sv, rnd)
                        A["suites"].setdefault(suite, {})[m] = {"est": e2, "lo": l2, "hi": h2, "n": len(sv), "win_pct": 100 * (1 - e2), "wlt": wlt(sv)}
                if m in TESTED:
                    tests.append((arm, m, p))
            S["arms"][arm] = A
        adj = rs.holm([p for _, _, p in tests])
        for (arm, m, _), ap_ in zip(tests, adj):
            S["arms"][arm]["pooled"][m]["holm_p"] = ap_
        for arm in NONSTOCK:
            A = S["arms"][arm]
            if "cpd" in A["pooled"]:
                A["verdict"] = verdict(A["pooled"]["cpd"], A["pooled"]["wl"], {k: v["cpd"]["est"] for k, v in A["suites"].items()})
        res["settings"][st] = S
    # mechanism: fit/spare facts per arm, near-critical share
    res["spare_log"] = {f"{k[0]}/{k[1]}/{k[2]}/s{k[3]}": v["spare"] for k, v in data.items() if "spare" in v}
    ms = {}
    for arm in NONSTOCK:
        rows = [v for (ar, d, s), v in mech.items() if ar == arm and v["share"] is not None and v["base_rate"] is not None]
        if rows:
            ms[arm] = {"n_runs": len(rows), "mean_share": sum(r["share"] for r in rows) / len(rows), "mean_base_rate": sum(r["base_rate"] for r in rows) / len(rows)}
    res["near_critical_share_setting_a"] = ms
    res["runs"] = {f"{k[0]}/{k[1]}/{k[2]}/s{k[3]}": v for k, v in data.items()}
    res["mech_runs"] = {f"{k[0]}/{k[1]}/s{k[2]}": v for k, v in mech.items()}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    names = {"cpd": "speed CPD post", "precpd": "speed CPD pre", "ne90": "speed n_end_090", "ne95": "speed n_end_095", "ne99": "speed n_end_099", "wl": "WL", "clbs": "area CLBs used",
             "pack_s": "pack time", "total_s": "total time", "wmin": "Wmin"}
    for st in SETTINGS:
        for arm in NONSTOCK:
            A = res["settings"][st]["arms"][arm]
            print(f"== setting {st} {arm}: n_designs {A['n_designs']}, failed {len(res['failed'])}; verdict {A.get('verdict')}")
            for m in METRICS + DESCR:
                if m not in A["pooled"]:
                    continue
                p = A["pooled"][m]
                row = f"  {names[m]:16s} all {p['win_pct']:+6.2f}% [{100*(1-p['hi']):+.2f},{100*(1-p['lo']):+.2f}] W/L/T {p['wlt'][0]}/{p['wlt'][1]}/{p['wlt'][2]}"
                for sname, sv in A["suites"].items():
                    q = sv.get(m)
                    if q:
                        row += f" | {sname} {q['win_pct']:+6.2f}% {q['wlt'][0]}/{q['wlt'][1]}/{q['wlt'][2]}"
                if "holm_p" in p:
                    row += f" | holm {p['holm_p']:.3f}"
                print(row)
    print("near-critical share (setting a):", json.dumps(ms))


if __name__ == "__main__":
    main()
