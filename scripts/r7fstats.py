"""Round-7 fix round: summaries of the .net hindsight arm (runs/r7f/) -> data/r7/net_gap.json.

The gap of a design is net0 over the fixed-point arm H, seed for seed on the TEST seeds 6-10 (H and the source run are chosen
on seeds 1-5); net0 is the stock clustering written by the same writer and run with the same placer (packing off), so the two
arms differ only in the clustering. Where H = net0 nothing is reported as a gap: the cell says "no gain found" and carries the
per-round numbers h1..hK. Fidelity is 1.0 by construction and is asserted per run in r7net.py; here it is counted.

  python scripts/r7fstats.py
"""

from __future__ import annotations

import statistics
import sys

import nornlib as nl
import r7lib as lib
import r7net as rn
import r7stats as st

METRICS = st.METRICS


def ratios(design: str, num: str, den: str, field: str, seeds) -> list[float]:
    out = []
    for s in seeds:
        a, b = rn.read_metrics(design, num, s), rn.read_metrics(design, den, s)
        if a and b and a.get("rc") == 0 and b.get("rc") == 0 and a.get(field) and b.get(field):
            out.append(float(a[field]) / float(b[field]))
    return out


def gaps(design: str, arm: str, seeds) -> dict:
    d = {m: st.gm_ci(ratios(design, "net0", arm, f, seeds)) for m, f in METRICS}
    d["objective"] = st.gm_ci([a * b for a, b in zip(ratios(design, "net0", arm, "wirelength", seeds),
                                                      ratios(design, "net0", arm, "cpd_ns", seeds))])
    return d


def net_gap(design: str) -> dict | None:
    rp = rn.R7F / design / "rounds.json"
    if not rp.is_file():
        return None
    rounds = nl.read_json(rp)
    if "hindsight_arm" not in rounds:
        return {"design": design, "note": rounds.get("stopped")}
    harm = rounds["hindsight_arm"]
    fid_runs = fid_ok = 0
    for arm in ["net0"] + [r["arm"] for r in rounds["rounds"]]:
        for s in rn.SEEDS:
            m = rn.read_metrics(design, arm, s)
            if m and m.get("rc") == 0:
                fid_runs += 1
                fid_ok += int(m.get("fidelity", {}).get("share") == 1.0 and m.get("fidelity", {}).get("clbs_mixed") == 0)
    rec: dict = {"design": design, "arm_type": "net", "hindsight_arm": harm, "no_gain": harm == "net0", "stopped": rounds.get("stopped"),
                 "units": rounds["units"], "frozen_clbs": rounds["frozen_clbs"], "movable_clbs": rounds["movable_clbs"],
                 "fidelity_runs": fid_runs, "fidelity_one": fid_ok,
                 "medians_train": rounds.get("medians_train"),
                 "rounds": [{"arm": r["arm"], "units_moved": r["recluster"].get("units_moved"), "cost_before": r["recluster"].get("cost_before"),
                             "cost_after": r["recluster"].get("cost_after"), "source_seed": r["recluster"].get("source_seed"),
                             "clbs_after": r["recluster"].get("clbs_after"), "gap": gaps(design, r["arm"], rn.SEEDS)} for r in rounds["rounds"] if r.get("ok", 0) >= rn.MIN_OK]}
    if not rec["no_gain"]:
        rec["H"] = gaps(design, harm, rn.SEEDS)
    # flow difference: the analytical-placement flow of runs/r7 (stock) over net0 (same clustering, annealing from a random start)
    ap = {}
    for m, f in METRICS:
        a, b = st.gm_of(design, "stock", f), st.gm_of(design, "net0", f, root=rn.read_metrics)
        ap[m] = (a / b) if a and b else None
    rec["ap_stock_over_net0"] = ap
    if design.startswith("n5_") and rounds.get("known", {}).get("built"):
        rec["known"] = {m: st.gm_ci(ratios(design, "net0", "net_known", f, rn.SEEDS)) for m, f in METRICS}
        rec["recovery"] = {}
        for m, f in METRICS[:3]:
            if rec["no_gain"]:
                rec["recovery"][m] = {"value": None, "note": "no gain found",
                                      "known_gap": st.gm_of(design, "net0", f, rn.SEEDS, rn.read_metrics) /
                                      st.gm_of(design, "net_known", f, rn.SEEDS, rn.read_metrics)
                                      if st.gm_of(design, "net_known", f, rn.SEEDS, rn.read_metrics) else None}
            else:
                rec["recovery"][m] = st.recovery(design, "net0", harm, "net_known", f, rn.SEEDS, rn.read_metrics)
    elif design.startswith("n5_"):
        rec["known"] = None
        rec["known_note"] = rounds.get("known", {}).get("why", "not built")
    return rec


def pooled_recovery(recs: list[dict]) -> dict:
    """Median recovery per metric, by B (16/64/256) and overall, over designs where the known arm is >= 5% better."""
    out: dict = {}
    for key, pick in (("all", lambda d: True), ("B16", lambda d: d.endswith("_16")), ("B64", lambda d: d.endswith("_64")),
                      ("B256", lambda d: d.endswith("_256"))):
        row = {}
        for m, _f in METRICS[:3]:
            sel = [r for r in recs if pick(r["design"]) and r.get("recovery", {}).get(m)]
            defined = [r["recovery"][m]["value"] for r in sel if r["recovery"][m].get("value") is not None]
            row[m] = {"median": statistics.median(defined) if defined else None, "n_defined": len(defined), "n_designs": len(sel),
                      "n_nogain": sum(1 for r in sel if r["recovery"][m].get("note") == "no gain found")}
        out[key] = row
    return out


def corpus() -> dict:
    """Runs of runs/r7f: last record per (design, arm, seed)."""
    import json
    p = rn.R7F / "runs.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
    last = {(r["design"], r["arm"], r["seed"]): r for r in rows}
    ok = [r for r in last.values() if r["rc"] == 0]
    return {"runs_ok": len(ok), "runs_failed": len(last) - len(ok), "vpr_seconds": sum(float(r.get("flow_s") or 0.0) for r in ok),
            "runs_by_arm": {a: sum(1 for r in ok if r["arm"] == a) for a in sorted({r["arm"] for r in ok})}}


def main() -> int:
    recs = []
    for d in lib.CALIB + lib.MAIN:
        r = net_gap(d)
        if r is not None:
            recs.append(r)
    done = [r for r in recs if "hindsight_arm" in r]
    calib = [r for r in done if r["design"].startswith("n5_")]
    real = [r for r in done if not r["design"].startswith("n5_")]
    gain = [r for r in real if not r["no_gain"]]
    summary = {"designs": len(done), "real_designs": len(real), "real_with_gain": len(gain),
               "real_no_gain": [r["design"] for r in real if r["no_gain"]],
               "fidelity_runs": sum(r["fidelity_runs"] for r in done), "fidelity_one": sum(r["fidelity_one"] for r in done),
               "corpus": corpus(), "seeds": list(rn.SEEDS), "in_sample": True}
    for m, _f in METRICS:
        v = [r["H"][m]["gm"] for r in gain]
        summary[f"median_{m}_designs_with_gain"] = statistics.median(v) if v else None
    summary["recovery_net"] = pooled_recovery(calib)
    # the affinity-bias arm recovery on the same footing (aggregated geometric means, threshold, by B)
    aff = []
    for d in lib.CALIB:
        g = st.design_gap(d)
        if g and "recovery" in g:
            aff.append(g)
    summary["recovery_affinity"] = pooled_recovery(aff)
    nl.write_json(lib.DATA7 / "net_gap.json", {"summary": summary, "designs": recs})
    for r in done:
        print(r["design"], r["hindsight_arm"], "no gain found" if r["no_gain"] else {m: round(r["H"][m]["gm"], 3) for m, _f in METRICS},
              f"fid {r['fidelity_one']}/{r['fidelity_runs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
