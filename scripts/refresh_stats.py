"""H-refresh statistics (docs/plan/refresh-crit.md): per-run measures from the sweep, ratios refresh/stock, pooled geomeans,
bootstrap intervals, Holm, verdicts.

  python3 refresh_stats.py --root SWEEP_ROOT --out OUT.json [--label refresh] [--mimir-src DIR]

Run dirs: ROOT/vpr/<label>-<cfg>/<design>/vpr_sa.s<seed>, cfg base (stock), rc1, rc8. Endpoint counts come from mimir.timing
(parse_report + analyse) on each run's kept report_timing.setup.rpt (the same code that fills timing_run.n_endpoints_*).
Needs the Mimir source on PYTHONPATH (or --mimir-src). Reads only; writes OUT.json.
"""
import argparse, gzip, hashlib, json, math, random, re, sys
from pathlib import Path

ARMS = {"stock": "base", "k1": "rc1", "k8": "rc8"}
METRICS = ["cpd", "ne90", "ne95", "ne99", "wl", "clbs"]          # tested (Holm family with the 2 arms)
DESCR = ["pack_s", "total_s"]                                   # descriptive
BOOT_N, BOOT_SEED = 10000, 20261029
NORNS15 = ("ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B", "sha",
           "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2")


def run_measures(d, mimir_timing):
    out = d / "vpr.out"
    if not out.is_file():
        return None
    t = out.read_text(errors="replace")
    f = lambda pat: (re.search(pat, t) or [None, None])[1]
    cpd, wl, clbs, pk = f(r"Final critical path delay \(least slack\): ([\d.]+) ns"), f(r"Total wirelength: (\d+)"), f(r"Netlist clb blocks: (\d+)"), f(r"# Packing took ([\d.]+) seconds")
    rec = json.loads((d / "mimir-run.json").read_text()) if (d / "mimir-run.json").is_file() else {}
    if cpd is None or wl is None or clbs is None or not rec.get("ok", False):
        return None
    m = {"cpd": float(cpd), "wl": float(wl), "clbs": float(clbs), "pack_s": float(pk), "total_s": float(rec.get("time_s") or 0)}
    r = re.search(r"Norns refresh: k=(\d+) refreshes=(\d+) time=([\d.]+)", t)
    m["refreshes"], m["refresh_s"] = (int(r.group(2)), float(r.group(3))) if r else (0, 0.0)
    rp = d / "report_timing.setup.rpt"
    text = rp.read_text(errors="replace") if rp.is_file() else (gzip.open(d / "report_timing.setup.rpt.gz", "rt", errors="replace").read() if (d / "report_timing.setup.rpt.gz").is_file() else None)
    if text is None:
        return None
    inp = mimir_timing.parse_report(text, hashlib.sha256(text.encode()).hexdigest(), 1000)
    res = mimir_timing.analyse(inp)
    m["ne90"], m["ne95"], m["ne99"] = (float(max(x, 1)) for x in res.stats.n_endpoints)   # >= 1 so ratios exist (a design with none counts as 1)
    return m


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def boot(vals, rnd):
    est = geomean(vals)
    ests = sorted(geomean([vals[rnd.randrange(len(vals))] for _ in vals]) for _ in range(BOOT_N))
    le, ge = sum(e <= 1.0 for e in ests), sum(e >= 1.0 for e in ests)
    p = min(1.0, 2 * (min(le, ge) + 1) / (BOOT_N + 1))
    return est, ests[int(0.05 * BOOT_N)], ests[int(0.95 * BOOT_N) - 1], p


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def verdict(cpd, clb, wl, cpd_by_suite, holm_p):
    """The rule of docs/plan/refresh-crit.md ('Statistics and the verdict rule')."""
    cost_ok = clb["est"] <= 1.02 and wl["est"] <= 1.02
    gain = cpd["hi"] < 1.0
    both = all(v < 1.0 for v in cpd_by_suite.values())
    if gain and cost_ok and holm_p < 0.05 and both:
        return "USEFUL"
    if gain and cost_ok:
        return "POSSIBLY GOOD"
    if gain and not cost_ok:
        return "INCONCLUSIVE (CPD gain, cost clause fails: CLBs %.3f, WL %.3f)" % (clb["est"], wl["est"])
    if (cpd["lo"] >= 0.98 and cpd["hi"] <= 1.02) or cpd["lo"] > 1.0:
        return "DISMISSED"
    if not cost_ok and cpd["est"] >= 0.98:
        return "DISMISSED"
    return "INCONCLUSIVE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="refresh")
    ap.add_argument("--mimir-src", default=str(Path.home() / "odin3-ws/mimir"))
    a = ap.parse_args()
    sys.path.insert(0, a.mimir_src)
    from mimir import timing as mt
    root = Path(a.root)
    designs = [d for d, _ in json.loads((root / "order.json").read_text())]
    data, failed = {}, []
    for arm, cfg in ARMS.items():
        for d in designs:
            for s in (1, 2, 3):
                rd = root / "vpr" / f"{a.label}-{cfg}" / d / f"vpr_sa.s{s}"
                m = run_measures(rd, mt)
                if m is None:
                    failed.append({"arm": arm, "design": d, "seed": s})
                else:
                    data[(arm, d, s)] = m
    bad = {(f["arm"], f["design"]) for f in failed}
    # a design with a failed run in an arm or in stock leaves that arm's pooled ratios
    res = {"failed": failed, "arms": {}, "per_design": {}, "n_runs": len(data)}
    rnd = random.Random(BOOT_SEED)
    tests = []
    for arm in ("k1", "k8"):
        ratios = {m: {} for m in METRICS + DESCR}
        for d in designs:
            if (arm, d) in bad or ("stock", d) in bad:
                continue
            for m in METRICS + DESCR:
                rs = [data[(arm, d, s)][m] / data[("stock", d, s)][m] for s in (1, 2, 3) if data[("stock", d, s)][m] > 0 and data[(arm, d, s)][m] > 0]
                if rs:
                    ratios[m][d] = geomean(rs)
        res["per_design"][arm] = ratios
        arm_res = {"n_designs": len(ratios["cpd"]), "pooled": {}, "suites": {}}
        for m in METRICS + DESCR:
            v = list(ratios[m].values())
            est, lo, hi, p = boot(v, rnd)
            arm_res["pooled"][m] = {"est": est, "lo": lo, "hi": hi, "p": p, "n": len(v)}
            for suite, sel in (("norns15", lambda d: d in NORNS15), ("mcnc20", lambda d: d not in NORNS15)):
                sv = [r for d, r in ratios[m].items() if sel(d)]
                if sv:
                    e2, l2, h2, _ = boot(sv, rnd)
                    arm_res["suites"].setdefault(suite, {})[m] = {"est": e2, "lo": l2, "hi": h2, "n": len(sv)}
            if m in METRICS:
                tests.append((arm, m, p))
        res["arms"][arm] = arm_res
    adj = holm([p for _, _, p in tests])
    for (arm, m, _), ap_ in zip(tests, adj):
        res["arms"][arm]["pooled"][m]["holm_p"] = ap_
    for arm in ("k1", "k8"):
        A = res["arms"][arm]
        A["verdict"] = verdict(A["pooled"]["cpd"], A["pooled"]["clbs"], A["pooled"]["wl"], {s: v["cpd"]["est"] for s, v in A["suites"].items()}, A["pooled"]["cpd"]["holm_p"])
    # refresh bookkeeping
    res["refresh_counts"] = {arm: {"refreshes": sum(v["refreshes"] for (ar, d, s), v in data.items() if ar == arm), "refresh_s": sum(v["refresh_s"] for (ar, d, s), v in data.items() if ar == arm)} for arm in ("k1", "k8")}
    res["runs"] = {f"{k[0]}/{k[1]}/s{k[2]}": v for k, v in data.items()}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    for arm in ("k1", "k8"):
        A = res["arms"][arm]
        print(arm, "n_designs", A["n_designs"], "->", A["verdict"])
        for m in METRICS + DESCR:
            p = A["pooled"][m]
            print(f"  {m:8s} {p['est']:.4f} [{p['lo']:.4f}, {p['hi']:.4f}] n={p['n']}" + (f" holm={p['holm_p']:.3f}" if "holm_p" in p else ""))


if __name__ == "__main__":
    main()
