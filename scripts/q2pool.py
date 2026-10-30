"""Q-N2: pool the per-pack results of q2gap.py (docs/plan/q-n2-appack-gap.md). CAD-style: per design (mean over the 4 shuffles), then
median, 10th and 90th percentile over designs, and the pooled share (sum over designs).

Usage: python q2pool.py <runs dir> <full-summary.json> <out.json>
"""
from __future__ import annotations

import collections
import json
import statistics
import sys
from pathlib import Path

KINDS = ("b", "c", "d", "e", "a", "x")
VTR = {"blob_merge", "boundtop", "ch_intrinsics", "diffeq1", "diffeq2", "mkDelayWorker32B", "mkPktMerge", "mkSMAdapter4B", "or1200",
       "raygentop", "sha", "stereovision0", "stereovision1", "stereovision2", "stereovision3"}


def pct(vals, p):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def summarize(vals):
    return {"median": pct(vals, 0.5), "p10": pct(vals, 0.1), "p90": pct(vals, 0.9), "n": len(vals)}


def load(runs, summary):
    kc = {(r["design"], r["cons"]): r["Kc"] for r in summary["designs"]}
    kn = {(r["design"], r["cons"]): r["K"] for r in summary["designs"]}
    per = collections.defaultdict(list)
    for p in sorted(Path(runs).glob("*.json")):
        design, cons, sh = p.stem.rsplit(".", 2)
        per[(design, cons)].append(json.loads(p.read_text()))
    rows = []
    for (design, cons), rs in sorted(per.items()):
        if (design, cons) not in kc:
            continue
        n = len(rs)
        row = {"design": design, "cons": cons, "kind": "VTR" if design in VTR else "MCNC", "n_shuffles": n, "Kc": kc[(design, cons)], "K": kn[(design, cons)]}
        row["S"] = sum(r["S"] for r in rs) / n
        row["gap"] = row["S"] - row["Kc"]
        row["resid"] = sum(r["T"] / 10 for r in rs) / n - row["Kc"]
        for k in KINDS:
            row["w_" + k] = sum(r["waste"].get(k, 0) for r in rs) / n / 10
        row["ratio"] = row["S"] / row["Kc"]
        # root-cause view: the waste of the leftover pieces (a) handed back to the kind of pick that took the other members of the C cluster
        sub = {k: sum(r["a_sub"].get(k, 0) for r in rs) / n for k in ("b", "c", "d", "e", "filler", "x", "none_found")}
        stot = sum(sub.values())
        for k in ("b", "c", "d", "e", "filler", "x"):
            own = row["w_" + k] if k != "filler" else 0.0
            row["r_" + k] = own + (row["w_a"] * sub[k] / stot if stot else 0.0)
        row["r_x"] += row["w_a"] * sub["none_found"] / stot if stot else row["w_a"]
        for key in ("a_sub", "events", "b", "c", "d", "e"):
            tot = collections.Counter()
            for r in rs:
                tot.update(r[key])
            row[key] = {k: v / n for k, v in tot.items()}
        row["seed_in_major"] = sum(r.get("seed_in_major", 0) for r in rs) / n
        row["pure"] = sum(r.get("pure", 0) for r in rs) / n
        row["fle_mismatch"] = sum(r["fle_mismatch"] for r in rs)
        row["cut"] = {"stock": sum(r["cut"]["stock"] for r in rs) / n, "C": sum(r["cut"]["C"] for r in rs) / n,
                      "extra_by_kind": {k: sum(r["cut"]["extra_by_kind"].get(k, 0) for r in rs) / n for k in ("a", "b", "c", "filler", "seed", "track")}}
        row["near"] = {"edges": sum(r["near"]["edges"] for r in rs) / n, "cross_stock": sum(r["near"]["cross_stock"] for r in rs) / n,
                       "cross_C": sum(r["near"]["cross_C"] for r in rs) / n,
                       "extra_by_kind": {k: sum(r["near"]["extra_by_kind"].get(k, 0) for r in rs) / n for k in ("a", "b", "c", "filler", "seed", "track")}}
        row["examples"] = rs[0]["examples"]
        rows.append(row)
    return rows


def share_table(rows):
    ok = [r for r in rows if r["gap"] > 0.5]
    out = {"n_designs": len(rows), "n_gap_pos": len(ok), "gap_sum": sum(r["gap"] for r in rows), "resid_sum": sum(r["resid"] for r in rows)}
    tot = sum(r["gap"] for r in rows)
    out["pooled"] = {k: sum(r["w_" + k] for r in rows) / tot if tot else None for k in KINDS}
    out["pooled"]["resid"] = out["resid_sum"] / tot if tot else None
    rk = ("b", "c", "d", "e", "filler", "x")
    out["root_pooled"] = {k: sum(r["r_" + k] for r in rows) / tot if tot else None for k in rk}
    out["root_per_design_share"] = {k: summarize([r["r_" + k] / r["gap"] for r in ok]) for k in rk}
    out["per_design_share"] = {k: summarize([r["w_" + k] / r["gap"] for r in ok]) for k in KINDS}
    out["gap_ratio"] = summarize([r["ratio"] for r in rows])
    return out


def main(argv):
    runs, summ, dst = argv
    rows = load(runs, json.loads(Path(summ).read_text()))
    res = {"rows": rows}
    res["all"] = share_table(rows)
    res["no_clma"] = share_table([r for r in rows if r["design"] != "clma"])
    for cons in ("own", "foreign"):
        res[cons] = share_table([r for r in rows if r["cons"] == cons])
    for kind in ("VTR", "MCNC"):
        res[kind] = share_table([r for r in rows if r["kind"] == kind])
    # event pooling (own+foreign, all designs)
    ev = collections.Counter()
    for key in ("a_sub", "events", "b", "c", "d", "e"):
        tot = collections.Counter()
        for r in rows:
            tot.update(r[key])
        res["pool_" + key] = dict(tot)
    cut = {"stock": sum(r["cut"]["stock"] for r in rows), "C": sum(r["cut"]["C"] for r in rows)}
    cut["extra_by_kind"] = {k: sum(r["cut"]["extra_by_kind"][k] for r in rows) for k in rows[0]["cut"]["extra_by_kind"]}
    cut["ratio_per_design"] = summarize([r["cut"]["stock"] / r["cut"]["C"] for r in rows if r["cut"]["C"]])
    res["cut"] = cut
    near = {k: sum(r["near"][k] for r in rows) for k in ("edges", "cross_stock", "cross_C")}
    near["extra_by_kind"] = {k: sum(r["near"]["extra_by_kind"][k] for r in rows) for k in rows[0]["near"]["extra_by_kind"]}
    near["cross_ratio_per_design"] = summarize([r["near"]["cross_stock"] / r["near"]["cross_C"] for r in rows if r["near"]["cross_C"]])
    res["near"] = near
    Path(dst).write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1:])
    for k in ("all", "no_clma", "own", "foreign", "VTR", "MCNC"):
        print(k, "n", r[k]["n_designs"], "gap", r[k]["gap_sum"], "first-dev", {a: round(b, 3) for a, b in r[k]["pooled"].items()}, "root", {a: round(b, 3) for a, b in r[k]["root_pooled"].items()})
    for k in ("pool_a_sub", "pool_events", "pool_b", "pool_c", "pool_d", "pool_e", "cut", "near"):
        print(k, json.dumps(r[k]))
