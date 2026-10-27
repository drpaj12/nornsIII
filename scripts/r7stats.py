"""Round-7 summaries (docs/plan/round7.md, Stage 2): the hindsight gap per design, the calibration against the known
optimum, the duplication counts. Reads runs/r7/<d>/ and writes data/r7/gap.json, data/r7/dup.json (no absolute paths).

  python scripts/r7stats.py
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

import nornlib as nl
import r7lib as lib

METRICS = (("WL", "wirelength"), ("CPD", "cpd_ns"), ("CLB", "logic_clbs"), ("W", "chan_width"))
BOOT = 10000
RECOVERY_MIN = 0.05   # ln-ratio of stock over known below which there is no gap to recover (about 5%)
BOOT_SEED = 20261026


def boot_ci(vals: list[float], stat=statistics.fmean, seed: int = BOOT_SEED) -> tuple[float, float]:
    if len(vals) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(vals)
    res = sorted(stat([vals[rng.randrange(n)] for _ in range(n)]) for _ in range(BOOT))
    return res[int(0.025 * BOOT)], res[int(0.975 * BOOT) - 1]


def gm_ci(ratios: list[float]) -> dict:
    logs = [math.log(r) for r in ratios if r > 0]
    if not logs:
        return {"gm": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    lo, hi = boot_ci(logs)
    return {"gm": math.exp(statistics.fmean(logs)), "lo": math.exp(lo), "hi": math.exp(hi), "n": len(logs)}


def seed_ratio_pairs(design: str, num_arm: str, den_arm: str, field: str) -> list[tuple[int, float]]:
    """(seed, ratio) for every seed where both arms ran ok with the field set: ONE filter builds ratios and seeds together."""
    out = []
    for s in lib.SEEDS:
        a, b = lib.read_metrics(design, num_arm, s), lib.read_metrics(design, den_arm, s)
        if a and b and a.get("rc") == 0 and b.get("rc") == 0 and a.get(field) and b.get(field):
            out.append((s, float(a[field]) / float(b[field])))
    return out


def seed_ratios(design: str, num_arm: str, den_arm: str, field: str) -> list[float]:
    return [r for _s, r in seed_ratio_pairs(design, num_arm, den_arm, field)]




def gm_of(design: str, arm: str, field: str, seeds=lib.SEEDS, root=None) -> float | None:
    """Geometric mean over `seeds` of a metric of one arm (None when fewer than 3 runs)."""
    rd = root or lib.read_metrics
    vals = []
    for s in seeds:
        m = rd(design, arm, s)
        if m and m.get("rc") == 0 and m.get(field):
            vals.append(math.log(float(m[field])))
    return math.exp(statistics.fmean(vals)) if len(vals) >= 3 else None


def recovery(design: str, stock: str, hind: str, known: str, field: str, seeds=lib.SEEDS, rd=None) -> dict:
    """Recovery from aggregated geometric means: (ln gm stock - ln gm H) / (ln gm stock - ln gm known). Undefined (no gap to
    recover) when the known arm is not at least 5% better than stock (denominator < RECOVERY_MIN)."""
    st, h, kn = (gm_of(design, a, field, seeds, rd) for a in (stock, hind, known))
    if None in (st, h, kn):
        return {"value": None, "note": "arm missing"}
    den = math.log(st) - math.log(kn)
    if den < RECOVERY_MIN:
        return {"value": None, "note": "no gap to recover", "known_gap": st / kn}
    return {"value": (math.log(st) - math.log(h)) / den, "known_gap": st / kn, "h_gap": st / h}


def design_gap(design: str) -> dict | None:
    """The affinity-bias arm (Norns packer with an affinity file at weight 100): its gap is the gap reachable via affinity bias,
    not a lower bound on the packer against a best-known clustering (the packer rebuilds only part of the requested groups)."""
    rp = lib.R7 / design / "rounds.json"
    if not rp.is_file():
        return None
    rounds = nl.read_json(rp)
    if "hindsight_arm" not in rounds:
        return {"design": design, "note": rounds.get("stopped"), "stock_ok": rounds.get("stock_ok")}
    harm = rounds["hindsight_arm"]
    fids = [r.get("fidelity", {}).get("share") for r in rounds["rounds"]]
    rec: dict = {"design": design, "arm_type": "affinity-bias", "hindsight_arm": harm, "stopped": rounds.get("stopped"),
                 "stock_ok": rounds["stock_ok"], "no_gain": harm == "stock",
                 "not_realised": bool(fids) and all(f is not None and f < lib.FID_MIN for f in fids),
                 "rounds": [{"arm": r["arm"], "median_objective": r.get("median_objective"),
                             "fidelity": r.get("fidelity", {}).get("share"), "ok": r["ok"],
                             **{m: gm_ci(seed_ratios(design, "stock", r["arm"], f)) for m, f in METRICS}} for r in rounds["rounds"]],
                 "median_objective": rounds.get("medians")}
    arms = [("h1", "h1")] + ([] if harm == "stock" else [("H", harm)])
    for label, arm in arms:
        rec[label] = {m: gm_ci(seed_ratios(design, "stock", arm, f)) for m, f in METRICS}
        rec[label]["objective"] = gm_ci([a * b for a, b in zip(seed_ratios(design, "stock", arm, "wirelength"),
                                                                seed_ratios(design, "stock", arm, "cpd_ns"))])
    # out-of-sample check (Peter 2026-10-26): choose the arm on seeds 1-5 (best median objective), evaluate stock/arm on seeds 6-10
    tr, te = lib.SEEDS[:5], lib.SEEDS[5:]
    meds = {}
    for arm in ["stock"] + [r["arm"] for r in rounds["rounds"]]:
        v = [m["objective"] for m in (lib.read_metrics(design, arm, s_) for s_ in tr) if m and m.get("rc") == 0 and m.get("objective")]
        if len(v) >= 4:
            meds[arm] = statistics.median(v)
    oarm = min(meds, key=lambda a: meds[a]) if meds else "stock"
    rec["oos"] = {"arm": oarm, "no_gain": oarm == "stock", "medians_seeds_1_5": meds}
    if oarm != "stock":
        for m, f in METRICS:
            rec["oos"][m] = gm_ci([r for s_, r in seed_ratio_pairs(design, "stock", oarm, f) if s_ in te])
    rec["fidelity_h1"] = fids[0] if fids else None
    rec["fidelity_H"] = next((r.get("fidelity", {}).get("share") for r in rounds["rounds"] if r["arm"] == harm), None)
    rec["fidelity_max"] = max((f for f in fids if f is not None), default=None)
    if design.startswith("n5_"):
        rec["known"] = {m: gm_ci(seed_ratios(design, "stock", "known", f)) for m, f in METRICS}
        rec["recovery"] = {}
        for m, f in METRICS[:3]:
            if harm == "stock":
                rec["recovery"][m] = {"value": None, "note": "no gain found", "known_gap": rec["known"][m]["gm"]}
            else:
                rec["recovery"][m] = recovery(design, "stock", harm, "known", f)
    return rec


def dup_summary(design: str, harm: str | None) -> dict | None:
    p = lib.R7 / design / "dup.json"
    if not p.is_file():
        return None
    d = nl.read_json(p)

    def vals(arm: str, fn) -> list[float]:
        out_: list[float] = []
        for k, v in d.items():
            if k.startswith(arm + ".s"):
                x = fn(v)
                if x is not None:
                    out_.append(x)
        return out_

    def med(arm: str, fn) -> float | None:
        v = vals(arm, fn)
        return statistics.median(v) if v else None

    def ratio(num: str, den: str):
        return lambda v: (v[num] / v[den]) if v[den] else None

    out: dict = {"design": design}
    arms = [("stock", "stock")] + ([("H", harm)] if harm and harm != "stock" else [])
    for label, arm in arms:
        # per-run ratios first, then the median over runs (not the ratio of two medians)
        out[label] = {"candidates": med(arm, lambda v: v["candidates"]), "share_of_luts": med(arm, ratio("candidates", "luts")),
                      "near5": med(arm, lambda v: v["near5"]), "near10": med(arm, lambda v: v["near10"]),
                      "near5_share": med(arm, ratio("near5", "candidates")), "near10_share": med(arm, ratio("near10", "candidates")),
                      "paths_with_hop": med(arm, lambda v: v["paths_with_hop"]),
                      "saved_share_of_cpd": med(arm, ratio("saved", "cpd")),
                      "cand_with_pad_sink": med(arm, lambda v: v.get("cand_with_pad_sink")),
                      "cand_with_hard_sink": med(arm, lambda v: v.get("cand_with_hard_sink")),
                      "other_only": med(arm, lambda v: v.get("other_only")), "runs": len(vals(arm, lambda v: 0))}
    return out


def corpus_summary() -> dict:
    """Runs per design and arm (ok, failed), logic CLBs, VPR seconds, disk sizes (bytes) of runs/r7 and the scratch directory."""
    import subprocess
    p = lib.R7 / "runs.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
    last: dict[tuple, dict] = {}
    for r in rows:
        last[(r["design"], r["arm"], r["seed"])] = r
    per: dict[str, dict] = {}
    for (d, arm, _s), r in last.items():
        e = per.setdefault(d, {"ok": 0, "failed": 0, "arms": {}, "flow_s": 0.0})
        e["arms"].setdefault(arm, {"ok": 0, "failed": 0})
        if r["rc"] == 0:
            e["ok"] += 1
            e["arms"][arm]["ok"] += 1
            e["flow_s"] += float(r.get("flow_s") or 0.0)
        else:
            e["failed"] += 1
            e["arms"][arm]["failed"] += 1
    for d, e in per.items():
        m = lib.read_metrics(d, "stock", 1)
        e["logic_clbs_seed1"] = m.get("logic_clbs") if m else None
        e["grid"] = m.get("grid") if m else None
        stock = [lib.read_metrics(d, "stock", s) for s in lib.SEEDS]
        stock = [x for x in stock if x and x.get("rc") == 0]
        e["max_rss_mib"] = max((x.get("max_rss_mib") or 0.0) for x in stock) if stock else None

    def du(path: Path) -> int:
        try:
            return int(subprocess.run(["du", "-sb", str(path)], capture_output=True, text=True, check=False).stdout.split()[0])
        except (IndexError, OSError):
            return 0

    sp = lib.R7 / "scratch_path.txt"
    scratch = Path(sp.read_text().strip()) if sp.is_file() else None
    return {"designs": per, "runs_logged": len(rows), "runs_ok": sum(e["ok"] for e in per.values()),
            "runs_failed": sum(e["failed"] for e in per.values()), "vpr_seconds": sum(e["flow_s"] for e in per.values()),
            "runs_r7_bytes": du(lib.R7), "scratch_bytes": du(scratch) if scratch else 0}


def r5_crosscheck() -> dict:
    """Why stock/known here differs from round 5's headline: same flow, same known arm (r5.py:121-125 and r7.py run_arm both
    use VPR's default flow with the affinity file at weight 100). Per calibration design, stock/known wirelength in round 5
    (its seeds) against this round (10 seeds)."""
    rows = {}
    for d in lib.CALIB:
        out = {}
        for tag, get in (("r5", lambda arm, s_, d=d: nl.runs_dir(d, "r5", f"{arm}.s{s_}", "metrics.json")),
                         ("r7", lambda arm, s_, d=d: lib.run_dir(d, arm, s_) / "metrics.json")):
            vals = {}
            for arm in ("stock", "known"):
                v = []
                for s_ in lib.SEEDS:
                    pth = get(arm, s_)
                    if pth.is_file():
                        m = nl.read_json(pth)
                        if m.get("rc") == 0 and m.get("wirelength"):
                            v.append(math.log(float(m["wirelength"])))
                vals[arm] = (math.exp(statistics.fmean(v)), len(v)) if v else None
            if vals["stock"] and vals["known"]:
                out[tag] = {"wl_gap": vals["stock"][0] / vals["known"][0], "seeds": vals["stock"][1]}
        if "r5" in out and "r7" in out:
            rows[d] = out
    ratio = [r["r7"]["wl_gap"] / r["r5"]["wl_gap"] for r in rows.values()]
    return {"designs": rows, "r7_over_r5_min": min(ratio) if ratio else None, "r7_over_r5_max": max(ratio) if ratio else None,
            "n": len(rows)}


def main() -> int:
    nl.write_json(lib.DATA7 / "r5check.json", r5_crosscheck())
    nl.write_json(lib.DATA7 / "corpus.json", corpus_summary())
    gaps = []
    dups = []
    for d in lib.CALIB + lib.MAIN:
        g = design_gap(d)
        if g is None:
            continue
        gaps.append(g)
        ds = dup_summary(d, g.get("hindsight_arm"))
        if ds:
            dups.append(ds)
    nl.write_json(lib.DATA7 / "gap.json", gaps)
    nl.write_json(lib.DATA7 / "dup.json", dups)
    for g in gaps:
        if "hindsight_arm" in g:
            print(g["design"], g["hindsight_arm"], "no gain found" if g["no_gain"] else
                  {m: round(g["H"][m]["gm"], 3) for m, _f in METRICS}, "fid", g.get("fidelity_H"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
