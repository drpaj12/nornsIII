"""Round 9 full-set statistics (docs/plan/round9-tpeko-real.md, entry 2026-10-29 (b)). The design is the unit.

  python scripts/r9pool.py [--json data/r9/full-summary.json] [DESIGN ...]

Per design and construction: ratios over the (shuffle 1 to 3) x (VPR seed 1 to 3) pairs, as geometric means:
  CLB   stock / N_C            (N_C = exact bound, as in the pilot), stock / exact, stock / known, known / N_C
  WL    stock / exact, stock / known
  CPD   stock / exact, stock / known
Pooled over designs: geometric mean, 90 percent bootstrap over designs (10000, seed 20261029, percentile), Holm over the three
metrics, room rule of round 5. Self-bias: per design log(ratio on own) - log(ratio on foreign), pooled the same way.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from pathlib import Path

import r9run as rr

BOOT, SEED = rr.BOOT, rr.BOOT_SEED
R5 = {"logic_clbs": 1.073, "wirelength": 1.220, "cpd_ns": 1.093}  # round 5, stock/known, 72 synthetic designs, same architecture and flags
METRICS = ("logic_clbs", "wirelength", "cpd_ns")


def load(designs: list) -> dict:
    out = rr.OUT
    runs = rr.read_runs()
    keep = collections.defaultdict(dict)
    for r in runs:
        if r["rc"] != 0 or (designs and r["design"] not in designs) or r.get("shuffle", -1) == 0 and r["arm"] != "stock":
            continue
        try:
            if r["sha"] != rr.blif_sha(r["design"], r["cons"], r["shuffle"]):
                continue
        except (KeyError, FileNotFoundError):
            continue
        keep[(r["design"], r["cons"])][(r["shuffle"], r["arm"], r["vseed"])] = r
    return keep


def gm(xs: list) -> float:
    return math.exp(sum(xs) / len(xs))


def per_design(keep: dict) -> dict:
    res: dict = {}
    for (d, c), recs in sorted(keep.items()):
        build = json.loads((rr.OUT / d / c / "build.json").read_text())
        row = {"design": d, "cons": c, "K": build["K"], "K_vpr": build["K_vpr"], "dummies": build["dummies"]}
        pairs = [(sh, s) for sh in (1, 2, 3) for s in (1, 2, 3) if all((sh, a, s) in recs for a in ("stock", "known"))]
        row["n_pairs"] = len(pairs)
        if not pairs:
            continue
        ex = [(sh, s) for sh, s in pairs if (sh, "exact", s) in recs]
        row["n_exact"] = len(ex)
        logs: dict = {}
        logs["clb_over_K"] = [math.log(recs[(sh, "stock", s)]["logic_clbs"] / build["K"]) for sh, s in pairs]
        logs["known_over_K"] = [math.log(recs[(sh, "known", s)]["logic_clbs"] / build["K"]) for sh, s in pairs]
        for m, tag in (("logic_clbs", "clb"), ("wirelength", "wl"), ("cpd_ns", "cpd")):
            logs[f"{tag}_over_known"] = [math.log(recs[(sh, "stock", s)][m] / recs[(sh, "known", s)][m]) for sh, s in pairs]
            if ex:
                logs[f"{tag}_over_exact"] = [math.log(recs[(sh, "stock", s)][m] / recs[(sh, "exact", s)][m]) for sh, s in ex]
        for k, v in logs.items():
            row[k] = gm(v)
        for arm in ("stock", "known", "exact"):
            sel = [recs[(sh, arm, s)] for sh, s in (ex if arm == "exact" else pairs) if (sh, arm, s) in recs]
            if sel:
                row[f"{arm}_purity"] = sum(r["purity"] for r in sel) / len(sel)
                row[f"{arm}_clbs"] = sum(r["logic_clbs"] for r in sel) / len(sel)
        row["_logs"] = logs
        res[(d, c)] = row
    return res


def boot(vals: list, rnd: random.Random) -> tuple:
    n = len(vals)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    lo, hi = means[int(0.05 * BOOT)], means[int(0.95 * BOOT) - 1]
    p = min(1.0, 2 * min(sum(1 for m in means if m <= 0) / BOOT, sum(1 for m in means if m >= 0) / BOOT))
    return sum(vals) / n, lo, hi, p


def pooled(rows: dict, cons: str, keys: dict, rnd: random.Random) -> dict:
    """keys: label -> ratio key, e.g. {'CLB': 'clb_over_exact', ...}. Holm over the labels."""
    rs = [r for (d, c), r in rows.items() if c == cons and all(k in r for k in keys.values())]
    out: dict = {"n": len(rs)}
    if len(rs) < 2:
        return out
    ps, tmp = [], {}
    for lab, k in keys.items():
        vals = [math.log(r[k]) for r in rs]
        mean, lo, hi, p = boot(vals, rnd)
        tmp[lab] = (mean, lo, hi, p)
        ps.append(p)
    adj = rr.holm(ps)
    for (lab, (mean, lo, hi, _p)), pa in zip(tmp.items(), adj):
        out[lab] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa,
                    "status": rr.status(math.exp(mean), lo, hi, pa) if len(rs) >= 12 else "inconclusive (n < 12)"}
    return out


def self_bias(rows: dict, keys: dict, rnd: random.Random) -> dict:
    ds = sorted({d for d, _c in rows})
    out: dict = {}
    both = [d for d in ds if (d, "own") in rows and (d, "foreign") in rows]
    out["n"] = len(both)
    if len(both) < 2:
        return out
    ps, tmp = [], {}
    for lab, k in keys.items():
        vals = [math.log(rows[(d, "own")][k]) - math.log(rows[(d, "foreign")][k]) for d in both
                if k in rows[(d, "own")] and k in rows[(d, "foreign")]]
        mean, lo, hi, p = boot(vals, rnd)
        tmp[lab] = (mean, lo, hi, p, len(vals))
        ps.append(p)
    for (lab, (mean, lo, hi, _p, n)), pa in zip(tmp.items(), rr.holm(ps)):
        out[lab] = {"own_over_foreign": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "n": n}
    return out


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    rows = per_design(load(a.designs))
    rnd = random.Random(SEED)
    res: dict = {"designs": [{k: v for k, v in r.items() if k != "_logs"} for r in rows.values()], "pooled": {}, "self_bias": {}}
    sets = {"stock_over_exact": {"CLB": "clb_over_exact", "WL": "wl_over_exact", "CPD": "cpd_over_exact"},
            "stock_over_known": {"CLB": "clb_over_known", "WL": "wl_over_known", "CPD": "cpd_over_known"},
            "stock_over_K_clb": {"CLB": "clb_over_K"}}
    for cons in ("own", "foreign"):
        for name, keys in sets.items():
            res["pooled"][f"{name}/{cons}"] = pooled(rows, cons, keys, rnd)
    res["self_bias"]["stock_over_exact"] = self_bias(rows, sets["stock_over_exact"], rnd)
    res["self_bias"]["stock_over_known"] = self_bias(rows, sets["stock_over_known"], rnd)
    res["self_bias"]["stock_over_K_clb"] = self_bias(rows, sets["stock_over_K_clb"], rnd)
    res["round5_stock_over_known"] = R5
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, indent=1, sort_keys=True))
    print("design cons N_C N_Cvpr n/ne | stock/N_C known/N_C | CLB s/e s/k | WL s/e s/k | CPD s/e s/k | purity stock known exact")
    f = lambda r, k: f"{r[k]:.3f}" if k in r else "  -  "  # noqa: E731
    for r in res["designs"]:
        print(f"{r['design']} {r['cons']} {r['K']} {r['K_vpr']} {r['n_pairs']}/{r.get('n_exact', 0)} | {f(r, 'clb_over_K')} {f(r, 'known_over_K')} | "
              f"{f(r, 'clb_over_exact')} {f(r, 'clb_over_known')} | {f(r, 'wl_over_exact')} {f(r, 'wl_over_known')} | "
              f"{f(r, 'cpd_over_exact')} {f(r, 'cpd_over_known')} | {f(r, 'stock_purity')} {f(r, 'known_purity')} {f(r, 'exact_purity')}")
    for k, v in res["pooled"].items():
        print("POOLED", k, json.dumps({a_: (round(b["gm"], 3), round(b["lo"], 3), round(b["hi"], 3), round(b["p_holm"], 4), b["status"]) if isinstance(b, dict) else b
                                       for a_, b in v.items()}))
    for k, v in res["self_bias"].items():
        print("SELFBIAS", k, json.dumps({a_: (round(b["own_over_foreign"], 3), round(b["lo"], 3), round(b["hi"], 3), round(b["p_holm"], 4)) if isinstance(b, dict) else b
                                         for a_, b in v.items()}))
    print("ROUND5 stock/known", R5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
