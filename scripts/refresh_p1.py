"""H-refresh mechanism check (docs/plan/refresh-crit.md): P1 of docs/plan/heap-picking.md recomputed per arm.

  python3 refresh_p1.py --sweep KEEP_SWEEP_ROOT --root REFRESH_ROOT --census CENSUS_ROOT --out OUT.json

For each arm (stock = cfg base, k1 = rc1, k8 = rc8), design of the 15 Verilog set and seed 1-3: the pack census (CENSUS_ROOT/k<k>c/<design>/s<seed>/census.tsv,
`refresh_gate.py --census`, pack only) gives the molecules picked and the pack-time criticality pc of each atom (max P value of its cluster); the arm's own full run
(REFRESH_ROOT/vpr/refresh-<cfg>/<design>/vpr_sa.s<seed>/attribution.json.xz, the kept 1000-path report with the HDL attribution) gives the post-route criticality rc of
each atom (max criticality of the reported paths through it, matched atoms). A heap pick = a molecule with an atom of pc >= 0.90; it leaves the heap when no atom
of the molecule has rc >= 0.90 (the definition of P1 in heappick_run.p1). Per design: pooled over its 3 seeds (sum of leaving / sum of heap picks); over designs:
median with a 90% percentile bootstrap (2000 resamples, seed 20261029), as heap-picking.md.
Also checks that the census run's .net equals the full run's .net (the census is log-only and the packer deterministic).
"""
import argparse, collections, hashlib, json, lzma, random, statistics, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heap_lib as hl
import heappick_lib as pl

ARMS = {"stock": ("base", "k0c"), "k1": ("rc1", "k1c"), "k8": ("rc8", "k8c")}
HEAP = 0.90
NORNS15 = ("ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B", "sha",
           "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rc_of(attr_xz, mt):
    data = json.loads(lzma.open(attr_xz, "rt").read())
    inp = mt.parse_attribution(data, "x")
    res = mt.analyse(inp)
    rc = {}
    for p in inp.paths:
        c = res.crit.get(p.index)
        if c is None:
            continue
        for n in p.nodes:
            if n.category == "matched" and n.atom and c > rc.get(n.atom, -1.0):
                rc[n.atom] = c
    return rc


def one_run(cen_path, attr_xz, blif_text, mt):
    cen0 = hl.parse_census(cen_path)
    g = hl.parse_blif_graph(blif_text, set(cen0))
    pads = set(g["pis"]) | {"out:" + n for n in g["pos"]}
    pc = {a: v["pc"] for a, v in hl.parse_census(cen_path, pads).items()}
    full = pl.parse_census_full(cen_path)
    rc = rc_of(attr_xz, mt)
    R = {a for a, c in rc.items() if c >= HEAP and a in pc}
    n = leave = seed_n = seed_leave = cand_n = cand_leave = picks = 0
    for m in full["mols"]:
        if m["cseq"] not in full["closed"]:
            continue
        atoms = [a for a in m["atoms"] if a in pc]
        if not atoms:
            continue
        picks += 1
        mpc = max((pc[a] for a in atoms if pc[a] is not None), default=None)
        if mpc is None or mpc < HEAP:
            continue
        gone = not any(a in R for a in atoms)
        n += 1
        leave += gone
        if m["kind"] == "seed":
            seed_n += 1
            seed_leave += gone
        else:
            cand_n += 1
            cand_leave += gone
    return {"picks": picks, "heap_picks": n, "leave": leave, "seed_heap": seed_n, "seed_leave": seed_leave, "cand_heap": cand_n, "cand_leave": cand_leave, "route_heap_atoms": len(R)}


def boot_median(vals, rnd, n=2000):
    ests = sorted(statistics.median([vals[rnd.randrange(len(vals))] for _ in vals]) for _ in range(n))
    return statistics.median(vals), ests[int(0.05 * n)], ests[int(0.95 * n) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--census", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mimir-src", default=str(Path.home() / "odin3-ws/mimir"))
    a = ap.parse_args()
    sys.path.insert(0, a.mimir_src)
    from mimir import timing as mt
    sweep, root, cens = Path(a.sweep), Path(a.root), Path(a.census)
    out = {"arms": {}, "runs": {}, "net_equal_census_vs_full": {}}
    rnd = random.Random(20261029)
    for arm, (cfg, ck) in ARMS.items():
        per_design, eq = {}, [0, 0]
        for d in NORNS15:
            blif = (sweep / "netlists" / "base" / d / "netlist" / f"{d}.blif").read_text(errors="replace")
            tot = collections.Counter()
            for s in (1, 2, 3):
                run = root / "vpr" / f"refresh-{cfg}" / d / f"vpr_sa.s{s}"
                cpath = cens / ck / d / f"s{s}" / "census.tsv"
                if not (run / "attribution.json.xz").is_file() or not cpath.is_file():
                    continue
                r = one_run(cpath, run / "attribution.json.xz", blif, mt)
                out["runs"][f"{arm}/{d}/s{s}"] = r
                tot.update(r)
                n1, n2 = cens / ck / d / f"s{s}" / f"{d}.net", run / f"{d}.net"
                if n1.is_file() and n2.is_file():
                    eq[1] += 1
                    eq[0] += sha(n1) == sha(n2)
            if tot["heap_picks"]:
                per_design[d] = {"share_leave": tot["leave"] / tot["heap_picks"], "heap_picks": tot["heap_picks"], "picks": tot["picks"],
                                 "share_heap_of_picks": tot["heap_picks"] / tot["picks"],
                                 "seed_leave": (tot["seed_leave"] / tot["seed_heap"]) if tot["seed_heap"] else None,
                                 "cand_leave": (tot["cand_leave"] / tot["cand_heap"]) if tot["cand_heap"] else None}
        vals = [v["share_leave"] for v in per_design.values()]
        med, lo, hi = boot_median(vals, rnd) if vals else (None, None, None)
        shares = [v["share_heap_of_picks"] for v in per_design.values()]
        sm = boot_median(shares, rnd) if shares else (None,) * 3
        out["arms"][arm] = {"n_designs": len(vals), "p1_leave_median": med, "lo": lo, "hi": hi, "heap_pick_share_median": sm[0], "heap_pick_share_lo": sm[1], "heap_pick_share_hi": sm[2],
                            "per_design": per_design}
        out["net_equal_census_vs_full"][arm] = {"equal": eq[0], "of": eq[1]}
    # paired change vs stock (per design, same designs)
    for arm in ("k1", "k8"):
        diffs = [out["arms"][arm]["per_design"][d]["share_leave"] - out["arms"]["stock"]["per_design"][d]["share_leave"]
                 for d in NORNS15 if d in out["arms"][arm]["per_design"] and d in out["arms"]["stock"]["per_design"]]
        if diffs:
            m, lo, hi = boot_median(diffs, rnd)
            out["arms"][arm]["change_vs_stock_median"] = {"median": m, "lo": lo, "hi": hi, "n": len(diffs)}
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    for arm, v in out["arms"].items():
        print(arm, "P1 leave", v["p1_leave_median"], v["lo"], v["hi"], "n", v["n_designs"], "| change", v.get("change_vs_stock_median"))
    print("net equal census vs full:", out["net_equal_census_vs_full"])


if __name__ == "__main__":
    main()
