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


def seed_ratios(design: str, num_arm: str, den_arm: str, field: str) -> list[float]:
    out = []
    for s in lib.SEEDS:
        a, b = lib.read_metrics(design, num_arm, s), lib.read_metrics(design, den_arm, s)
        if a and b and a.get("rc") == 0 and b.get("rc") == 0 and a.get(field) and b.get(field):
            out.append(float(a[field]) / float(b[field]))
    return out




def design_gap(design: str) -> dict | None:
    rp = lib.R7 / design / "rounds.json"
    if not rp.is_file():
        return None
    rounds = nl.read_json(rp)
    if "hindsight_arm" not in rounds:
        return {"design": design, "note": rounds.get("stopped"), "stock_ok": rounds.get("stock_ok")}
    harm = rounds["hindsight_arm"]
    rec: dict = {"design": design, "hindsight_arm": harm, "stopped": rounds.get("stopped"), "stock_ok": rounds["stock_ok"],
                 "rounds": [{"arm": r["arm"], "median_objective": r.get("median_objective"),
                             "fidelity": r.get("fidelity", {}).get("share"), "ok": r["ok"]} for r in rounds["rounds"]],
                 "median_objective": rounds.get("medians")}
    for label, arm in (("H", harm), ("h1", "h1")):
        rec[label] = {}
        if arm == "stock":
            rec[label] = {m: {"gm": 1.0, "lo": 1.0, "hi": 1.0, "n": 0} for m, _f in METRICS}
            continue
        for m, f in METRICS:
            rec[label][m] = gm_ci(seed_ratios(design, "stock", arm, f))
        rec[label]["objective"] = gm_ci([a * b for a, b in zip(seed_ratios(design, "stock", arm, "wirelength"),
                                                                seed_ratios(design, "stock", arm, "cpd_ns"))])
    fid = [r.get("fidelity", {}).get("share") for r in rounds["rounds"]]
    rec["fidelity_h1"] = fid[0] if fid else None
    rec["fidelity_H"] = next((r.get("fidelity", {}).get("share") for r in rounds["rounds"] if r["arm"] == harm), None)
    if design.startswith("n5_"):
        rec["known"] = {m: gm_ci(seed_ratios(design, "stock", "known", f)) for m, f in METRICS}
        rec["recovery"] = {}
        for m, f in METRICS:
            if harm == "stock":
                rec["recovery"][m] = {"median": 0.0, "note": "H = stock"}
                continue
            per = []
            dens = []
            for s in lib.SEEDS:
                st, h, kn = (lib.read_metrics(design, a, s) for a in ("stock", harm, "known"))
                if not (st and h and kn and st.get("rc") == 0 and h.get("rc") == 0 and kn.get("rc") == 0):
                    continue
                den = math.log(st[f]) - math.log(kn[f])
                dens.append(den)
                if den > 0.01:
                    per.append((math.log(st[f]) - math.log(h[f])) / den)
            if not per or statistics.median(dens) < 0.01:
                rec["recovery"][m] = {"median": None, "note": "no gap to recover", "n": len(per)}
            else:
                lo, hi = boot_ci(per, statistics.median)
                rec["recovery"][m] = {"median": statistics.median(per), "lo": lo, "hi": hi, "n": len(per)}
    return rec


def dup_summary(design: str, harm: str | None) -> dict | None:
    p = lib.R7 / design / "dup.json"
    if not p.is_file():
        return None
    d = nl.read_json(p)

    def med(arm: str, key: str, per_lut: bool = False, per_cpd: bool = False) -> float | None:
        vals = []
        for k, v in d.items():
            if k.startswith(arm + ".s"):
                x = v[key]
                if per_lut:
                    x = x / v["luts"] if v["luts"] else 0.0
                if per_cpd:
                    x = x / v["cpd"] if v["cpd"] else 0.0
                vals.append(x)
        return statistics.median(vals) if vals else None

    out: dict = {"design": design}
    for label, arm in (("stock", "stock"), ("H", harm or "stock")):
        out[label] = {"candidates": med(arm, "candidates"), "share_of_luts": med(arm, "candidates", per_lut=True),
                      "near5": med(arm, "near5"), "near10": med(arm, "near10"),
                      "near5_share": (med(arm, "near5") / med(arm, "candidates")) if med(arm, "candidates") else None,
                      "near10_share": (med(arm, "near10") / med(arm, "candidates")) if med(arm, "candidates") else None,
                      "paths_with_hop": med(arm, "paths_with_hop"), "saved_share_of_cpd": med(arm, "saved", per_cpd=True)}
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


def main() -> int:
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
        if "H" in g:
            print(g["design"], g["hindsight_arm"], {m: round(g["H"][m]["gm"], 3) for m, _f in METRICS},
                  "fid", g.get("fidelity_H"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
