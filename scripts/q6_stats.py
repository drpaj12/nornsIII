"""Q-N6 statistics (docs/plan/q-n6-duplication.md). Same measures, bootstrap, Holm and verdict rule as q5_stats.py.

  python3 q6_stats.py --root Q5_ROOT --q6 Q6_OUT --out OUT.json

Primary ratio: result of the arm (best round) / its paired baseline (round 0 = flat-recon of the same start placement, no duplication). Secondary: the
same result / the original Q-N5 stock run (dup) or Q-N5 s=2 run (spare: also / stock). Gate table: round-0 / original start run. Reads only.
"""
import argparse, json, random, sys
from pathlib import Path

import refresh_stats as rs
import q5_stats as q5

ARMS = ("dup", "spare")


def pooled(ratios_by_metric, rnd, tag):
    A = {"n_designs": len(ratios_by_metric["cpd"]), "pooled": {}, "suites": {}}
    tests = []
    for m in q5.METRICS + q5.DESCR:
        v = list(ratios_by_metric[m].values())
        if not v:
            continue
        est, lo, hi, p = rs.boot(v, rnd)
        A["pooled"][m] = {"est": est, "lo": lo, "hi": hi, "p": p, "n": len(v), "win_pct": 100 * (1 - est), "wlt": q5.wlt(v)}
        for suite, sel in (("vtr15", lambda d: d in q5.NORNS15), ("mcnc20", lambda d: d not in q5.NORNS15)):
            sv = [r for d, r in ratios_by_metric[m].items() if sel(d)]
            if sv:
                e2, l2, h2, _ = rs.boot(sv, rnd)
                A["suites"].setdefault(suite, {})[m] = {"est": e2, "lo": l2, "hi": h2, "n": len(sv), "win_pct": 100 * (1 - e2), "wlt": q5.wlt(sv)}
        if m in q5.TESTED:
            tests.append((m, p))
    return A, tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--q6", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mimir-src", default=str(Path.home() / "odin3-ws/mimir"))
    a = ap.parse_args()
    sys.path.insert(0, a.mimir_src)
    from mimir import timing as mt
    rs.BOOT_N = q5.BOOT_N
    root, q6 = Path(a.root), Path(a.q6)
    designs = [d for d, _ in json.loads((root / "order.json").read_text())]

    def dirs(st, arm, kind, d, s):
        if kind == "res":
            return q6 / "vpr" / f"q6{st}-{arm}" / d / f"vpr_sa.s{s}"
        if kind == "base":
            return q6 / "vpr" / f"q6{st}-{arm}-base" / d / f"vpr_sa.s{s}"
        return root / "vpr" / f"q5{st}-{ {'stock': 'stock', 'start': 'stock' if arm == 'dup' else 's2'}[kind] }" / d / f"vpr_sa.s{s}"

    cache = {}

    def meas(rd):
        if rd not in cache:
            cache[rd] = q5.measures(rd, mt) if rd.is_dir() else None
        return cache[rd]

    rnd = random.Random(q5.BOOT_SEED)
    res = {"settings": {}, "gate": {}, "mechanism": {}}
    dup_logs = {}
    for arm in ARMS:
        for d in designs:
            for s in (1, 2, 3):
                f = q6 / "work" / f"q6-{arm}" / d / f"s{s}" / "dup.json"
                if f.is_file():
                    dup_logs[(arm, d, s)] = json.loads(f.read_text())
    for st in ("a", "b"):
        S = {}
        for base_kind, label in (("base", "vs_paired_baseline"), ("stock", "vs_stock"), ("start", "vs_start")):
            tests, As = [], {}
            for arm in ARMS:
                if base_kind == "start" and arm == "dup":
                    continue
                ratios = {m: {} for m in q5.METRICS + q5.DESCR}
                for d in designs:
                    for m in q5.METRICS + q5.DESCR:
                        rr = []
                        for s in (1, 2, 3):
                            n, b = meas(dirs(st, arm, "res", d, s)), meas(dirs(st, arm, base_kind, d, s))
                            if n and b and n[m] > 0 and b[m] > 0:
                                rr.append(n[m] / b[m])
                        if rr:
                            ratios[m][d] = rs.geomean(rr)
                if not ratios["cpd"]:
                    continue
                A, t = pooled(ratios, rnd, label)
                A["per_design"] = ratios
                As[arm] = A
                tests += [(arm, m, p) for m, p in t]
            adj = rs.holm([p for _, _, p in tests]) if tests else []
            for (arm, m, _), h in zip(tests, adj):
                As[arm]["pooled"][m]["holm_p"] = h
            for arm, A in As.items():
                if "cpd" in A["pooled"] and "wl" in A["pooled"]:
                    A["verdict"] = q5.verdict(A["pooled"]["cpd"], A["pooled"]["wl"], {k: v["cpd"]["est"] for k, v in A["suites"].items()})
            S[label] = As
        res["settings"][st] = S
    # gate: round 0 / original start run, per design and seed
    for arm in ARMS:
        g = {}
        for d in designs:
            for s in (1, 2, 3):
                n, b = meas(dirs("a", arm, "base", d, s)), meas(dirs("a", arm, "start", d, s))
                if n and b:
                    g[f"{d}/s{s}"] = {"cpd": n["cpd"] / b["cpd"], "wl": n["wl"] / b["wl"], "clbs": n["clbs"] / b["clbs"], "wmin": n["wmin"] / b["wmin"], "grid_same": n["grid"] == b["grid"]}
        res["gate"][arm] = g
        if g:
            res["gate"][arm + "_summary"] = {"n": len(g), "cpd_geomean": rs.geomean([v["cpd"] for v in g.values()]), "wl_geomean": rs.geomean([v["wl"] for v in g.values()]),
                                             "cpd_identical": sum(abs(v["cpd"] - 1) < 1e-9 for v in g.values()), "clbs_same": sum(abs(v["clbs"] - 1) < 1e-9 for v in g.values()),
                                             "grid_same": sum(v["grid_same"] for v in g.values())}
    # mechanism
    for arm in ARMS:
        L = [v for (ar, d, s), v in dup_logs.items() if ar == arm]
        stops = {}
        for v in L:
            k = v.get("stop", "?").split(":")[0]
            stops[k] = stops.get(k, 0) + 1
        eq = [r.get("equiv") for v in L for r in v["rounds"] if "equiv" in r]
        pre = []
        for v in L:
            pass
        res["mechanism"][arm] = {"runs": len(L), "copies": sum(v["copies"] for v in L), "moves": sum(v["moves"] for v in L), "refused": sum(v["refused"] for v in L),
                                 "stops": stops, "equiv_true": sum(e is True for e in eq), "equiv_nochange": sum(e == "no netlist change" for e in eq),
                                 "equiv_false": sum(e is False for e in eq), "runs_with_gain": sum(v.get("best_round", 0) > 0 for v in L),
                                 "runs_with_copy_round": sum(v["copies"] + v["moves"] > 0 for v in L)}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    names = {"cpd": "speed CPD post", "precpd": "speed CPD pre", "ne90": "speed n_end_090", "ne95": "speed n_end_095", "ne99": "speed n_end_099", "wl": "WL", "clbs": "area CLBs",
             "wmin": "Wmin"}
    for st in ("a", "b"):
        for label, As in res["settings"][st].items():
            for arm, A in As.items():
                print(f"== setting {st} {label} {arm}: n {A['n_designs']} verdict {A.get('verdict')}")
                for m in ("cpd", "precpd", "ne90", "ne95", "ne99", "wl", "clbs", "wmin"):
                    p = A["pooled"].get(m)
                    if not p:
                        continue
                    row = f"  {names[m]:16s} {p['win_pct']:+6.2f}% [{100*(1-p['hi']):+.2f},{100*(1-p['lo']):+.2f}] W/L/T {p['wlt'][0]}/{p['wlt'][1]}/{p['wlt'][2]}"
                    for sn, sv in A["suites"].items():
                        q = sv.get(m)
                        if q:
                            row += f" | {sn} {q['win_pct']:+6.2f}% {q['wlt'][0]}/{q['wlt'][1]}/{q['wlt'][2]}"
                    if "holm_p" in p:
                        row += f" | holm {p['holm_p']:.3f}"
                    print(row)
    print("gate", json.dumps({k: v for k, v in res["gate"].items() if k.endswith("summary")}))
    print("mechanism", json.dumps(res["mechanism"]))


if __name__ == "__main__":
    main()
