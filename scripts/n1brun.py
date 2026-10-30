"""Q-N1b runner and statistics (docs/plan/q-n1b-true-seed-oracle.md): the true seed oracle (--norns_seed_oracle).

  python scripts/n1brun.py gate                 # byte-identical .net gate with the option absent (HS0 gate, N1B binary)
  python scripts/n1brun.py arms [DESIGN ...]    # oracle arm on the round 9 D' (own C, ordered file), VPR seeds 1-3, smallest first
  python scripts/n1brun.py pool [--json FILE]   # exact-rebuild shares, Jaccard, gaps, bootstrap, Holm, verdict

Stock runs are read from data/hs0/runs.jsonl (HS0, same flow). Outputs under $N1B_OUT (default ~/odin3-ws/work/n1b-out), outside the
worktree; nothing is deleted. A run is finished iff its metrics.json exists (resume = run again). Disk guard and weekly meter as HS0.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import random
import re
import shutil
import sys
from pathlib import Path

HOME = Path.home()
WS = Path(os.environ.get("WS_ROOT", str(HOME / "odin3-ws")))
OUT = Path(os.environ.get("N1B_OUT", str(WS / "work" / "n1b-out")))
os.environ["HS0_OUT"] = str(OUT)
os.environ.setdefault("NORNS_VPR", str(WS / "work" / "norns-vtr-n1b" / "build" / "vpr" / "vpr"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hs0run as H  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
STOCK_RUNS = HERE / "data" / "hs0" / "runs.jsonl"
SEEDS = H.SEEDS
METRICS = H.METRICS


def stock_records() -> dict:
    out = {}
    for line in STOCK_RUNS.read_text().splitlines():
        r = json.loads(line)
        if r["arm"] == "stock" and r["rc"] == 0:
            out[(r["design"], r["vseed"])] = r
    return out


def design_list() -> list:
    have = {d for d, _s in stock_records()}
    return [d for d in H.designs_by_size() if d in have]


def oracle_run(b, seed: int) -> dict:
    cwd = OUT / "runs" / b.design / f"oracle.s{seed}"
    mp = cwd / "metrics.json"
    if mp.is_file():
        return json.loads(mp.read_text())
    cwd.mkdir(parents=True, exist_ok=True)
    args = [str(b.blif), "--seed", str(seed), "--timing_report_npaths", "100", "--place_file", "/dev/null", "--route_file", "/dev/null",
            "--norns_seed_oracle", str(b.sh / "affinity.tsv")]
    log = cwd / "vpr.out"
    rc = H.run_vpr(args, cwd, log)
    rec: dict = {"design": b.design, "arm": "oracle", "vseed": seed, "rc": rc, "n_c": b.n_c, "blif_sha": b.build["shuffles"]["0"]["sha256"]}
    if rc == 0:
        import nornlib as nl
        rec.update({k: v for k, v in nl.Metrics(log).values.items() if k in ("wirelength", "cpd_ns", "chan_width", "flow_s")})
        net = cwd / f"{b.blif.stem}.net"
        rec["logic_clbs"] = H.count_clbs(net)
        text = log.read_text(errors="replace")
        lines = [x for x in text.splitlines() if x.startswith("NORNS_ORACLE\t")]
        (cwd / "oracle.log").write_text("\n".join(lines) + "\n")
        m = re.search(r"Norns seed oracle summary: clusters=(\d+) exact=(\d+) single_candidate=(\d+) trials=(\d+) recheck_mismatch=(\d+)", text)
        if m:
            rec["oracle"] = dict(zip(("clusters", "exact", "single", "trials", "recheck_mismatch"), map(int, m.groups())))
        rec["net_sha"] = H.sha(net)
        for f in (net, log):  # compress in place: .net and vpr.out
            with f.open("rb") as src, gzip.open(str(f) + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            f.write_bytes(b"")  # the uncompressed copy is emptied, not removed (no deletion rule)
    mp.write_text(json.dumps(rec, sort_keys=True))
    with (OUT / "runs.jsonl").open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{b.design}/oracle.s{seed}: rc={rc} clbs={rec.get('logic_clbs')} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} oracle={rec.get('oracle')}", flush=True)
    return rec


def arms(designs: list) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for d in (designs or design_list()):
        H.guard()
        w = H.weekly()
        if w >= 100:
            print(f"WEEKLY METER {w} >= 100; stopping", file=sys.stderr)
            return 4
        b = H.Build(d)
        for s in SEEDS:
            oracle_run(b, s)
    return 0


def oracle_runs() -> dict:
    out = {}
    p = OUT / "runs.jsonl"
    for x in (p.read_text().splitlines() if p.is_file() else []):
        r = json.loads(x)
        if r.get("rc") == 0 and "logic_clbs" in r:
            out[(r["design"], r["vseed"])] = r
    return out


def quantiles(xs: list, qs=(0.05, 0.25, 0.5, 0.75, 0.95)) -> dict:
    s = sorted(xs)
    return {str(q): s[min(len(s) - 1, int(q * len(s)))] for q in qs} if s else {}


def pool(json_path: str) -> int:
    st = stock_records()
    orc = oracle_runs()
    designs = [d for d in design_list() if all((d, s) in orc for s in SEEDS)]
    kc = H.corrected_bounds(designs)
    rows = []
    jacc_all: list = []
    exact_tot = clusters_tot = 0
    mismatch = 0
    for d in designs:
        row = {"design": d, "n_c": orc[(d, 1)]["n_c"], "n_c_corrected": kc.get(d)}
        ex = cl = 0
        for s in SEEDS:
            o = orc[(d, s)]
            ex += o["oracle"]["exact"]
            cl += o["oracle"]["clusters"]
            mismatch += o["oracle"]["recheck_mismatch"]
            for line in (OUT / "runs" / d / f"oracle.s{s}" / "oracle.log").read_text().splitlines():
                f = line.split("\t")
                jacc_all.append(float(f[5]))
        row["exact_share"] = ex / cl if cl else 0.0
        row["clusters_handled"] = cl
        exact_tot += ex
        clusters_tot += cl
        for m in METRICS:
            row[f"{m}:gap"] = sum(math.log(st[(d, s)][m]) - math.log(orc[(d, s)][m]) for s in SEEDS) / len(SEEDS)
        nc = math.log(row["n_c"])
        row["clb:stock_over_nc"] = sum(math.log(st[(d, s)]["logic_clbs"]) for s in SEEDS) / len(SEEDS) - nc
        row["clb:oracle_over_nc"] = sum(math.log(orc[(d, s)]["logic_clbs"]) for s in SEEDS) / len(SEEDS) - nc
        rows.append(row)
    rnd = random.Random(H.BOOT_SEED)
    res: dict = {"n_designs": len(rows), "designs": designs, "per_design": rows, "recheck_mismatch_total": mismatch,
                 "exact": {"clusters": clusters_tot, "exact": exact_tot, "share": exact_tot / clusters_tot if clusters_tot else None,
                           "design_share_quantiles": quantiles([r["exact_share"] for r in rows])},
                 "jaccard_quantiles": quantiles(jacc_all), "jaccard_mean": sum(jacc_all) / len(jacc_all) if jacc_all else None, "tests": {}, "extra": {}}
    tmp, ps = [], []
    for m in METRICS:
        mean, lo, hi, p = H.boot([r[f"{m}:gap"] for r in rows], rnd)
        tmp.append((m, mean, lo, hi))
        ps.append(p)
    for (m, mean, lo, hi), pa in zip(tmp, H.holm(ps)):
        exists = pa < 0.05 and math.exp(lo) > 1.0
        rev = pa < 0.05 and math.exp(hi) < 1.0
        res["tests"][m] = {"gap": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "p_holm_str": H.fmt_p(pa),
                           "verdict": "significant gain" if exists else ("REVERSED" if rev else "INCONCLUSIVE")}
    # per-metric distribution of stock/oracle over designs (reporting order: speed, wirelength, area)
    res["distribution"] = {}
    for m in ("cpd_ns", "wirelength", "logic_clbs"):
        rs = sorted(math.exp(r[f"{m}:gap"]) for r in rows)
        q = lambda f: rs[min(len(rs) - 1, int(f * len(rs)))]  # noqa: E731
        res["distribution"][m] = {"wins": sum(1 for x in rs if x > 1 + 1e-9), "losses": sum(1 for x in rs if x < 1 - 1e-9),
                                  "ties": sum(1 for x in rs if abs(x - 1) <= 1e-9), "median": q(0.5), "p10": q(0.1), "p90": q(0.9),
                                  "by_design": {r["design"]: math.exp(r[f"{m}:gap"]) for r in rows}}
    for k in ("stock_over_nc", "oracle_over_nc"):
        mean, lo, hi, _p = H.boot([r[f"clb:{k}"] for r in rows], rnd)
        res["extra"][k] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi)}
        if all(r["n_c_corrected"] for r in rows):
            mean, lo, hi, _p = H.boot([r[f"clb:{k}"] + math.log(r["n_c"] / r["n_c_corrected"]) for r in rows], rnd)
            res["extra"][k + "_corrected"] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi)}
    ls, lo_ = math.log(res["extra"]["stock_over_nc"]["gm"]), math.log(res["extra"]["oracle_over_nc"]["gm"])
    res["share_of_log_gap_closed"] = (ls - lo_) / ls if ls else None
    clb = res["tests"]["logic_clbs"]
    closed = clb["verdict"] == "significant gain" and res["share_of_log_gap_closed"] is not None and res["share_of_log_gap_closed"] >= 0.5
    exact_share = res["exact"]["share"]
    if closed:
        res["verdict"] = "gap closed by seeds (POSSIBLY GOOD)"
    elif exact_share is not None and exact_share < 0.5:
        res["verdict"] = "not closed; most clusters not rebuilt exactly: the gap is in growth (gain / closing), not seeding"
    else:
        res["verdict"] = "not closed by seeds (INCONCLUSIVE / REVERSED, see tests)"
    if json_path:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(res, indent=1, sort_keys=True))
    print(f"designs pooled: {len(rows)}; exact share {exact_share}; recheck mismatches {mismatch}")
    print("jaccard", res["jaccard_quantiles"], res["jaccard_mean"])
    for m in ("cpd_ns", "wirelength", "logic_clbs"):
        d = res["distribution"][m]
        print(f"{m:11s} wins/losses/ties {d['wins']}/{d['losses']}/{d['ties']} median {d['median']:.4f} p10 {d['p10']:.4f} p90 {d['p90']:.4f}")
    for k, v in res["tests"].items():
        print(f"{k:12s} stock/oracle {v['gap']:.4f} [{v['lo']:.4f}, {v['hi']:.4f}] Holm p {v['p_holm_str']} {v['verdict']}")
    for k, v in res["extra"].items():
        print(f"{k:28s} {v['gm']:.4f} [{v['lo']:.4f}, {v['hi']:.4f}]")
    print("share of log gap to N_C closed:", res["share_of_log_gap_closed"])
    print("VERDICT:", res["verdict"])
    return 0


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("gate", "arms", "pool"))
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    if a.mode == "gate":
        return H.gate()
    if a.mode == "arms":
        return arms(a.designs)
    return pool(a.json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
