"""Q-N3b statistics (docs/plan/q-n3b-2hop-gain.md): per-run measures, ratios arm/stock, CAD-style table (geomean % win, W/L/T), pooled geomeans,
bootstrap intervals, Holm, verdicts. Reuses the functions of refresh_stats.py (same measures, same verdict rule).

  python3 q3b_stats.py --root RUN_ROOT --out OUT.json [--label q3b] [--mimir-src DIR]

Run dirs: ROOT/vpr/<label>-<cfg>/<design>/vpr_sa.s<seed>, cfg base (stock), h1 (w = 0.1), h25 (w = 0.25). Reads only; writes OUT.json.
"""
import argparse, json, random, re, sys
from pathlib import Path

import refresh_stats as rs

ARMS = {"stock": "base", "w0.1": "h1", "w0.25": "h25"}
NONSTOCK = ("w0.1", "w0.25")
METRICS = rs.METRICS
DESCR = rs.DESCR
BOOT_N, BOOT_SEED = 10000, 20261030
TIE = 0.005
NORNS15 = rs.NORNS15


def wlt(ratios):
    w = sum(r < 1 - TIE for r in ratios)
    l = sum(r > 1 + TIE for r in ratios)
    return w, l, len(ratios) - w - l


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="q3b")
    ap.add_argument("--mimir-src", default=str(Path.home() / "odin3-ws/mimir"))
    a = ap.parse_args()
    sys.path.insert(0, a.mimir_src)
    from mimir import timing as mt
    rs.BOOT_N = BOOT_N
    root = Path(a.root)
    designs = [d for d, _ in json.loads((root / "order.json").read_text())]
    data, failed, h2log = {}, [], {}
    for arm, cfg in ARMS.items():
        for d in designs:
            for s in (1, 2, 3):
                rd = root / "vpr" / f"{a.label}-{cfg}" / d / f"vpr_sa.s{s}"
                m = rs.run_measures(rd, mt)
                if m is None:
                    failed.append({"arm": arm, "design": d, "seed": s})
                    continue
                data[(arm, d, s)] = m
                t = (rd / "vpr.out").read_text(errors="replace")
                x = re.search(r"Norns 2hop: w=(\S+) evals=(\d+) eval_time=([\d.]+) s joins=(\d+) join_time=([\d.]+) s", t)
                if x:
                    h2log[(arm, d, s)] = {"evals": int(x.group(2)), "eval_s": float(x.group(3)), "joins": int(x.group(4)), "join_s": float(x.group(5))}
    bad = {(f["arm"], f["design"]) for f in failed}
    res = {"failed": failed, "arms": {}, "per_design": {}, "n_runs": len(data)}
    rnd = random.Random(BOOT_SEED)
    tests = []
    for arm in NONSTOCK:
        ratios = {m: {} for m in METRICS + DESCR}
        for d in designs:
            if (arm, d) in bad or ("stock", d) in bad:
                continue
            for m in METRICS + DESCR:
                rr = [data[(arm, d, s)][m] / data[("stock", d, s)][m] for s in (1, 2, 3) if data[("stock", d, s)][m] > 0 and data[(arm, d, s)][m] > 0]
                if rr:
                    ratios[m][d] = rs.geomean(rr)
        res["per_design"][arm] = ratios
        A = {"n_designs": len(ratios["cpd"]), "pooled": {}, "suites": {}, "cad": {}}
        for m in METRICS + DESCR:
            v = list(ratios[m].values())
            est, lo, hi, p = rs.boot(v, rnd)
            A["pooled"][m] = {"est": est, "lo": lo, "hi": hi, "p": p, "n": len(v), "win_pct": 100 * (1 - est), "wlt": wlt(v)}
            for suite, sel in (("vtr15", lambda d: d in NORNS15), ("mcnc20", lambda d: d not in NORNS15)):
                sv = [r for d, r in ratios[m].items() if sel(d)]
                if sv:
                    e2, l2, h2, _ = rs.boot(sv, rnd)
                    A["suites"].setdefault(suite, {})[m] = {"est": e2, "lo": l2, "hi": h2, "n": len(sv), "win_pct": 100 * (1 - e2), "wlt": wlt(sv)}
            if m in METRICS:
                tests.append((arm, m, p))
        res["arms"][arm] = A
    adj = rs.holm([p for _, _, p in tests])
    for (arm, m, _), ap_ in zip(tests, adj):
        res["arms"][arm]["pooled"][m]["holm_p"] = ap_
    for arm in NONSTOCK:
        A = res["arms"][arm]
        A["verdict"] = rs.verdict(A["pooled"]["cpd"], A["pooled"]["clbs"], A["pooled"]["wl"], {s: v["cpd"]["est"] for s, v in A["suites"].items()}, A["pooled"]["cpd"]["holm_p"])
        A["h2_cost"] = {"evals": sum(v["evals"] for (ar, d, s), v in h2log.items() if ar == arm), "eval_s": sum(v["eval_s"] for (ar, d, s), v in h2log.items() if ar == arm),
                        "joins": sum(v["joins"] for (ar, d, s), v in h2log.items() if ar == arm), "join_s": sum(v["join_s"] for (ar, d, s), v in h2log.items() if ar == arm)}
    res["runs"] = {f"{k[0]}/{k[1]}/s{k[2]}": v for k, v in data.items()}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    names = {"cpd": "speed CPD", "ne90": "speed n_end_090", "ne95": "speed n_end_095", "ne99": "speed n_end_099", "wl": "WL", "clbs": "area CLBs", "pack_s": "pack time", "total_s": "total time"}
    for arm in NONSTOCK:
        A = res["arms"][arm]
        print(f"== {arm}: n_designs {A['n_designs']}, failed {len(res['failed'])}; verdict {A['verdict']}")
        for m in METRICS + DESCR:
            p = A["pooled"][m]
            row = f"  {names[m]:16s} all {p['win_pct']:+6.2f}% [{100*(1-p['hi']):+.2f},{100*(1-p['lo']):+.2f}] W/L/T {p['wlt'][0]}/{p['wlt'][1]}/{p['wlt'][2]}"
            for sname, sv in A["suites"].items():
                q = sv[m]
                row += f" | {sname} {q['win_pct']:+6.2f}% {q['wlt'][0]}/{q['wlt'][1]}/{q['wlt'][2]}"
            if "holm_p" in p:
                row += f" | holm {p['holm_p']:.3f}"
            print(row)
        print("  2hop cost:", A["h2_cost"])


if __name__ == "__main__":
    main()
