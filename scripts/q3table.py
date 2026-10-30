"""Q-N3: markdown tables and the decision rule from the q3stats.py summary. Usage: python q3table.py <summary.json> <out.md>"""
import json
import sys

FEATS = ["shared_nets", "common_nbrs", "members_2hop", "absorbed", "d_pins", "fanout", "seq_gap", "nearcrit_shared"]


def cell(r, k):
    x = r.get(k)
    return "n/a" if not x else f"{x['mean']:.3f} ({x['lo']:.3f} to {x['hi']:.3f})"


def rule(r, f):
    """Plan rule: connectivity-stratum TEST AUC lower bound > 0.55, same sign (AUC > 0.5) on own and foreign, BH q < 0.05 (both), and not
    construction-dependent (|AUC full - AUC real| <= 0.05 on the pooled connectivity stratum)."""
    k = lambda v, g: r.get(f"{v}|{g}|conn|{f}|auc")
    both, own, fo, real = k("full", "both"), k("full", "own"), k("full", "foreign"), k("real", "both")
    if not (both and own and fo and real):
        return False, "missing"
    why = []
    if both["lo"] <= 0.55:
        why.append("lower bound <= 0.55")
    if not (own["mean"] > 0.5 and fo["mean"] > 0.5):
        why.append("sign differs own/foreign")
    if max(own.get("q", 1), fo.get("q", 1)) >= 0.05:
        why.append("q >= 0.05")
    if abs(both["mean"] - real["mean"]) > 0.05:
        why.append(f"construction-dependent (full {both['mean']:.3f}, real {real['mean']:.3f})")
    return not why, "; ".join(why) or "passes"


def main(argv):
    d = json.load(open(argv[0]))
    r = d["results"]
    out = []
    for strat, title in (("conn", "CONNECTIVITY stratum (the innovation target)"), ("time", "TIMING-PULL stratum")):
        out.append(f"### Pairwise AUC (right vs pick), {title}, TEST designs, mean over designs (90 percent bootstrap interval)\n")
        out.append("| score | all events | own C | foreign C | real view (dummies deleted) | q own / foreign (BH) |")
        out.append("|---|---|---|---|---|---|")
        for s in FEATS + ["vpr", "comb_A", "comb_B"]:
            q = [r.get(f"full|{g}|{strat}|{s}|auc", {}).get("q") for g in ("own", "foreign")]
            qs = " / ".join("-" if x is None else f"{x:.3f}" for x in q)
            out.append(f"| {s} | {cell(r, f'full|both|{strat}|{s}|auc')} | {cell(r, f'full|own|{strat}|{s}|auc')} | {cell(r, f'full|foreign|{strat}|{s}|auc')} | "
                       f"{cell(r, f'real|both|{strat}|{s}|auc')} | {qs} |")
        out.append("")
        out.append(f"### Top-1 on the wrong picks of the {strat} stratum (is the best-scored queued molecule a right one)\n")
        out.append("| score | all events | own C | foreign C | real view |")
        out.append("|---|---|---|---|---|")
        for s in FEATS + ["vpr", "comb_A", "comb_B"]:
            out.append(f"| {s} | " + " | ".join(cell(r, f"{v}|{g}|{strat}|{s}|top1") for v, g in (("full", "both"), ("full", "own"), ("full", "foreign"), ("real", "both"))) + " |")
        out.append("")
    for strat, title in (("conn", "wrong picks of the connectivity stratum + right picks"), ("all", "all wrong picks + right picks")):
        out.append(f"### Top-1 over all decisions ({title}); VPR gain = share of correct picks; last column = difference to VPR\n")
        out.append("| score | all events | own C | foreign C | real view | difference to VPR (all events) |")
        out.append("|---|---|---|---|---|---|")
        for s in FEATS + ["vpr", "comb_A", "comb_B"]:
            out.append(f"| {s} | " + " | ".join(cell(r, f"{v}|{g}|{strat}|{s}|alltop1") for v, g in (("full", "both"), ("full", "own"), ("full", "foreign"), ("real", "both"))) +
                       f" | {cell(r, f'full|both|{strat}|{s}|alltop1_minus_vpr')} |")
        out.append("")
    out.append("### Decision rule (plan), connectivity stratum\n")
    out.append("| feature | verdict | reason |")
    out.append("|---|---|---|")
    for f in FEATS:
        ok, why = rule(r, f)
        out.append(f"| {f} | {'ranks' if ok else 'does not rank'} | {why} |")
    out.append("")
    out.append("### Label counts (events, summed over the 4 shuffles; divide by 4 for the per-shuffle mean)\n")
    out.append("| side | cons | wrong picks, connectivity | wrong picks, timing-pull | right picks (sampled 1 in 3) |")
    out.append("|---|---|---|---|---|")
    c = d["event_counts"]
    for side in ("TUNE", "TEST"):
        for cons in ("own", "foreign"):
            out.append(f"| {side} | {cons} | {c.get(f'{side}|{cons}|b|conn', 0)} | {c.get(f'{side}|{cons}|b|time', 0)} | {c.get(f'{side}|{cons}|ok|None', 0)} |")
    open(argv[1], "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
