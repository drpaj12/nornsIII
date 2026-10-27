"""Round-7 summaries of the .net hindsight arm (runs/r7f/) -> data/r7/net_gap.json.

Seeds. H (the fixed-point arm: the best of net0, h1..h5 by median objective) is chosen on the SELECTION seeds 1-5 (rn.SEEDS) and its
gap there is in sample ("selection seeds"). Since fix round 2 (protocol amendment 2026-10-27 in docs/plan/round7.md) net0 and H are
also run on the HELD-OUT seeds 6-10 (lib.HELD_SEEDS) with H fixed from rounds.json; the held-out gap is the headline. The gap of a
design is net0 over H, seed for seed; net0 is the stock clustering written by the same writer and run with the same placer (packing
off), so the two arms differ only in the clustering. Where H = net0 nothing is reported as a gap ("no gain found"; it carries the
per-round numbers h1..hK) and the pooled medians count it as gap 1 / recovery 0, beside the medians over the designs with H != net0.
A design has a held-out gain when the 95% interval of its objective ratio (WL x CPD, net0 over H) lies above 1; borderline = H != net0
without that. Fidelity is 1.0 by construction (asserted per run in r7net.py); here it is counted.

  python scripts/r7fstats.py
"""

from __future__ import annotations

import json
import math
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
    d["objective"] = st.gm_ci(ratios(design, "net0", arm, "objective", seeds))
    return d


def classify(obj: dict) -> str:
    """gain: the objective interval lies above 1 (net0 worse than H); harm: below 1; borderline otherwise."""
    if obj.get("n", 0) < 3 or obj["lo"] != obj["lo"]:
        return "undetermined"
    return "gain" if obj["lo"] > 1.0 else ("worse" if obj["hi"] < 1.0 else "borderline")


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
        for s in tuple(rn.SEEDS) + tuple(lib.HELD_SEEDS):
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
        rec["H"] = gaps(design, harm, rn.SEEDS)                 # selection seeds 1-5 (in sample)
        rec["selection_class"] = classify(rec["H"]["objective"])
        rec["heldout"] = gaps(design, harm, lib.HELD_SEEDS)     # held-out seeds 6-10
        rec["heldout_class"] = classify(rec["heldout"]["objective"])
        rec["heldout_runs"] = {a: sum(1 for s_ in lib.HELD_SEEDS if (rn.read_metrics(design, a, s_) or {}).get("rc") == 0) for a in ("net0", harm)}
    rec["heldout_probe_pre_amendment"] = design == "n5_mesh_dp_16"   # its seeds 6-10 were run before the amendment (queued probe); H = net0 there
    # flow difference: the analytical-placement flow of runs/r7 (stock) over net0 (same clustering, annealing from a random start)
    ap = {}
    for m, f in METRICS:
        a, b = st.gm_of(design, "stock", f), st.gm_of(design, "net0", f, root=rn.read_metrics)
        ap[m] = (a / b) if a and b else None
    rec["ap_stock_over_net0"] = ap
    if design.startswith("n5_") and rounds.get("known", {}).get("built"):
        rec["known"] = {m: st.gm_ci(ratios(design, "net0", "net_known", f, rn.SEEDS)) for m, f in METRICS}
        rec["known_heldout"] = {m: st.gm_ci(ratios(design, "net0", "net_known", f, lib.HELD_SEEDS)) for m, f in METRICS}
        rec["recovery"] = {}
        rec["recovery_heldout"] = {}
        # no gain found (H = net0): recovery is 0 where the known arm is >= 5% better (st.recovery gives exactly 0 for H = net0), undefined otherwise
        for m, f in METRICS[:3]:
            rec["recovery"][m] = st.recovery(design, "net0", harm, "net_known", f, rn.SEEDS, rn.read_metrics)
            rec["recovery_heldout"][m] = st.recovery(design, "net0", harm, "net_known", f, lib.HELD_SEEDS, rn.read_metrics)
            for key in ("recovery", "recovery_heldout"):
                if rec["no_gain"] and rec[key][m].get("value") is not None:
                    rec[key][m]["note"] = "no gain found, counted as 0"
    elif design.startswith("n5_"):
        rec["known"] = None
        rec["known_note"] = rounds.get("known", {}).get("why", "not built")
    return rec


def pooled_recovery(recs: list[dict], key: str = "recovery") -> dict:
    """Median recovery per metric, by B (16/64/256) and overall. `pooled` = every design whose known arm is >= 5% better, a design
    with no gain found counting as recovery 0 (the headline); `defined_only` = the designs where H differs from net0 (what the
    earlier rounds reported). `key` picks the seeds: 'recovery' (selection seeds 1-5) or 'recovery_heldout' (6-10)."""
    out: dict = {}
    for grp, pick in (("all", lambda d: True), ("B16", lambda d: d.endswith("_16")), ("B64", lambda d: d.endswith("_64")),
                      ("B256", lambda d: d.endswith("_256"))):
        row = {}
        for m, _f in METRICS[:3]:
            sel = [r for r in recs if pick(r["design"]) and r.get(key, {}).get(m)]
            pooled, defined = [], []
            for r in sel:
                v = r[key][m]
                nogain = r[key][m].get("note") in ("no gain found", "no gain found, counted as 0") or r.get("no_gain") is True
                if v.get("value") is not None:
                    pooled.append(v["value"])
                    if not nogain:
                        defined.append(v["value"])
                elif v.get("note") == "no gain found" and (v.get("known_gap") or 0) >= math.exp(st.RECOVERY_MIN):
                    pooled.append(0.0)   # affinity-bias records: known arm better, H = stock
            row[m] = {"median": statistics.median(pooled) if pooled else None, "n_pooled": len(pooled),
                      "median_defined_only": statistics.median(defined) if defined else None, "n_defined": len(defined),
                      "n_designs": len(sel), "n_nogain": len(pooled) - len(defined)}
        out[grp] = row
    return out


def corpus() -> dict:
    """Runs of runs/r7f: last record per (design, arm, seed), by arm kind and by seed group (selection 1-5, held-out 6-10)."""
    p = rn.R7F / "runs.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
    last = {(r["design"], r["arm"], r["seed"]): r for r in rows}
    ok = [r for r in last.values() if r["rc"] == 0]

    def kind(a: str) -> str:
        return "net0" if a == "net0" else ("net_known" if a == "net_known" else "net_h")
    by_kind: dict = {}
    for r in ok:
        e = by_kind.setdefault(kind(r["arm"]), {"selection": 0, "heldout": 0, "seeds_selection": set(), "seeds_heldout": set()})
        g = "heldout" if r["seed"] in lib.HELD_SEEDS else "selection"
        e[g] += 1
        e["seeds_" + g].add(r["seed"])
    for e in by_kind.values():
        e["seeds_selection"], e["seeds_heldout"] = sorted(e["seeds_selection"]), sorted(e["seeds_heldout"])
    return {"runs_ok": len(ok), "runs_failed": len(last) - len(ok), "vpr_seconds": sum(float(r.get("flow_s") or 0.0) for r in ok),
            "runs_by_arm": {a: sum(1 for r in ok if r["arm"] == a) for a in sorted({r["arm"] for r in ok})},
            "runs_by_kind": by_kind,
            "runs_heldout_ok": sum(1 for r in ok if r["seed"] in lib.HELD_SEEDS),
            "runs_selection_ok": sum(1 for r in ok if r["seed"] in lib.NET_SEEDS),
            "runs_beyond_protocol_seeds": sum(1 for r in ok if r["seed"] not in lib.NET_SEEDS and r["seed"] not in lib.HELD_SEEDS)}


def med_of(v: list[float]) -> float | None:
    return statistics.median(v) if v else None


def heldout_summary(real: list[dict]) -> dict:
    """Held-out gap medians over the real designs, three ways: all designs (no gain found = gap 1), the designs where H != net0,
    and the designs with a held-out gain (objective interval above 1)."""
    out: dict = {"seeds": list(lib.HELD_SEEDS), "n_real": len(real)}
    ch = [r for r in real if not r["no_gain"]]
    out["n_h_not_net0"] = len(ch)
    out["classes"] = {c: [r["design"] for r in ch if r["heldout_class"] == c] for c in ("gain", "borderline", "worse", "undetermined")}
    out["no_gain_designs"] = [r["design"] for r in real if r["no_gain"]]
    sets = {"pooled_all": [(r, None) for r in real], "h_not_net0": [(r, "x") for r in ch],
            "heldout_gain": [(r, "x") for r in ch if r["heldout_class"] == "gain"],
            "without_borderline": [(r, "x") for r in ch if r["heldout_class"] in ("gain", "worse")]}
    for name, items in sets.items():
        row: dict = {"n": len(items)}
        for m, _f in METRICS:
            row[m] = med_of([1.0 if r["no_gain"] else r["heldout"][m]["gm"] for r, _x in items])
        row["objective"] = med_of([1.0 if r["no_gain"] else r["heldout"]["objective"]["gm"] for r, _x in items])
        out[name] = row
    sel = {"n": len(ch)}
    for m, _f in METRICS:
        sel[m] = med_of([r["H"][m]["gm"] for r in ch])
    sel["objective"] = med_of([r["H"]["objective"]["gm"] for r in ch])
    out["selection_h_not_net0"] = sel
    return out


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
               "corpus": corpus(), "seeds_selection": list(rn.SEEDS), "seeds_heldout": list(lib.HELD_SEEDS)}
    for m, _f in METRICS:
        v = [r["H"][m]["gm"] for r in gain]
        summary[f"median_{m}_designs_with_gain"] = statistics.median(v) if v else None   # selection seeds, in sample
    summary["heldout"] = heldout_summary(real)
    summary["recovery_net"] = pooled_recovery(calib, "recovery_heldout")           # headline: held-out seeds
    summary["recovery_net_selection"] = pooled_recovery(calib, "recovery")         # selection seeds, in sample
    # the affinity-bias arm recovery on the same footing (aggregated geometric means, threshold, by B)
    aff = []
    for d in lib.CALIB:
        g = st.design_gap(d)
        if g and "recovery" in g:
            aff.append(g)
    summary["recovery_affinity"] = pooled_recovery(aff)
    nl.write_json(lib.DATA7 / "net_gap.json", {"summary": summary, "designs": recs})
    for r in done:
        held = "" if r["no_gain"] else {m: round(r["heldout"][m]["gm"], 3) for m, _f in METRICS}
        print(r["design"], r["hindsight_arm"], "no gain found" if r["no_gain"] else {m: round(r["H"][m]["gm"], 3) for m, _f in METRICS},
              "held-out", held, r.get("heldout_class", ""), f"fid {r['fidelity_one']}/{r['fidelity_runs']}")
    print(json.dumps(summary["heldout"], indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
