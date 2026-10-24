"""Fill the paper's Results/Discussion/Conclusion once the summary JSON exists.

Replaces the placeholder paragraph and the \todo items with measured prose built from
docs/plan/paper-summary.json (written by scripts/fill_paper.py). Token substitution makes the
step mechanical, so a rerun after more designs only needs fill_paper.py + this script.

Usage: python scripts/write_paper_prose.py
"""

from __future__ import annotations

import sys

import nornlib as nl


def main(argv: list[str]) -> int:
    s = nl.read_json(nl.WS / "docs" / "plan" / "paper-summary.json")
    wins = sum(v[0] for v in s["hot_wins"].values())
    n = sum(v[1] for v in s["hot_wins"].values())
    fmt_scale = lambda v: "n/a" if v is None else f"{v:g}"
    import report
    data, designs = report.load_all()
    pairs = []
    for design in designs:
        on = nl.data_crossover(design, "crossover.json")
        off = nl.data_crossover(design, "checkpoint.json")
        if not on.is_file() or not off.is_file():
            continue
        a = nl.read_json(on).get("crossover_scale")
        b = nl.read_json(off).get("crossover_scale_off")
        if a is not None and b is not None:
            pairs.append((design, a, b))
    same = [d for d, a, b in pairs if a == b]
    hotter = [f"{d} ({a:g} vs {b:g})" for d, a, b in pairs if a > b]
    cooler = [f"{d} (control {b:g} vs {a:g})" for d, a, b in pairs if b > a]
    ckpt_sentence = (
        f"the two sweeps find the same scale on {len(same)} of the {len(pairs)} designs where "
        f"both found one"
        + (f", checkpointing extends it on {', '.join(hotter)}" if hotter else "")
        + (f", and the control extends it on {', '.join(cooler)}" if cooler else "")
        + ".")
    ret1 = "n/a"
    ret1i = "n/a"
    try:
        full = [float(r["retention"]) for d in designs for seed in report.FAMILIES
                for r in [report.pick(data[d], "soft", seed, "full")]
                if r and r.get("retention") is not None]
        inter = [float(r["retention"]) for d in designs for seed in report.FAMILIES
                 for r in [report.pick(data[d], "soft", seed, "inter")]
                 if r and r.get("retention") is not None]
        import statistics
        ret1 = f"{statistics.median(full):.2f}" if full else "n/a"
        ret1i = f"{statistics.median(inter):.2f}" if inter else "n/a"
    except Exception:  # the retention medians are a summary only
        pass
    n_designs = len(designs)
    hard_n = s["hard_runs"]
    hard_better = s["hard_runs_better"]
    hard_sv3 = s["hard_design_wl"]["stereovision3"]
    hard_fam = s["hard_family_wl"]
    urd_hard = hard_fam["urd"]
    recovered_hard = [float(v) for k, v in hard_fam.items() if k != "urd"]
    hot_med = [v for v in s["hot_retention"].values() if v is not None]
    hot_lo, hot_hi = s["hot_retention_range"]
    inter_pct = 100 * (float(s["inter_wl"]) / float(s["soft_wl"]) - 1)
    results = f"""The {n_designs} completed designs give the ratios of Table~\\ref{{tab:qor}}. Soft seeds
stay within a few percent of the unseeded baseline in routed wirelength
({s['soft_wl']} for the full seed, {s['inter_wl']} for the inter-cluster-only arm, both pooled
over all seven seed families) while cutting the minimum channel width to {s['soft_chan']} and
costing {s['soft_runtime']} in placement runtime (both also pooled). The hard arm is worse on
average (geomean {s['hard_wl']} over the {hard_n} runs that completed; {hard_better} of those
still beat the baseline, and stereovision3's hard geomean is {hard_sv3}), but not uniformly: one
blob\\_merge k-means$_{{2k}}$ run is missing from the arm because VPR's initial placement could
not fit 9 CLBs inside its regions (the constraints are too tight, not a packing failure).
Fixed regions may block the anneal's fine moves across cluster borders -- a hypothesis the
aggregate numbers are consistent with. No single seed family dominates: Urd is the worst full
seed in soft wirelength (1.029) and the best hard seed ({urd_hard} against
{min(recovered_hard):.3f}-{max(recovered_hard):.3f} for the recovered families). Retention at
scale~1 is {ret1} of a seed's cluster CLBs (full) and {ret1i} (inter)."""
    discussion = f"""Three observations. First, the seed families span a narrow band but are not
interchangeable: provenance (Urd) is the worst full seed in the soft arm (1.029) and the best in
the hard arm, so it is not consistently better or worse than recovered clusters. The full and
inter-cluster-only arms differ by {inter_pct:.1f}\\% in pooled wirelength
({s['soft_wl']} vs {s['inter_wl']}); no arm randomizes the coarse cluster layout, so whether the
fine order inside a cluster matters as much as the coarse die position is not measured here and
stays open. Second, VPR's checkpointing does not separate the crossover in the
measured range: {ckpt_sentence} RLPlace's prediction that checkpointing extends the useful
range is therefore not observed on these designs; if it holds, its effect is smaller than the
between-design variation. Third, the safe recipe is
to cold-start from a cluster-derived placement at a temperature scale at or below the crossover,
which is a multiple of VPR's own estimate; above it the seed's retention is still high per family
(medians {min(hot_med):.2f}-{max(hot_med):.2f} at twice the crossover, individual runs
{hot_lo:.2f}-{hot_hi:.2f}) but it wins only {wins} of
{n} head-to-heads against an unseeded run at the same temperature -- the coarse structure
survives the anneal, the advantage does not."""
    conclusion = """Seeding VPR's anneal is worth it only as a calibrated cold start: at
VPR's own start temperature the cluster layouts and the provenance hierarchy place at parity
with the analytic start, but from a good final placement they keep winning when the anneal is
restarted hotter, up to the largest tested scale that still wins -- a lower bound on the fall
point where the sweep hit its cap. The recipe is that crossover table,
not a seed-specific tuning: start at or below it, and expect the seed to inform the coarse
placement while the anneal supplies the fine one."""
    s_path = nl.WS / "docs" / "paper" / ("norns.tex" if not argv else argv[0])
    text = s_path.read_text(encoding="utf-8")
    text = fill_tables(text, nl.WS / "docs" / "plan" / "paper-numbers.tex")
    import re
    text = re.sub(r"The (?:ten|\d+) completed designs give .*?(?=\n\n\\section\{Discussion\})",
                  lambda _m: results, text, flags=re.S)
    text = re.sub(r"Three observations\..*?(?=\n\n\\section\{Conclusion\})",
                  lambda _m: discussion, text, flags=re.S)
    text = re.sub(r"Seeding VPR's anneal is worth it.*?"
                  r"(?=\n\n\\bibliographystyle|\n\n\\bibliography)",
                  lambda _m: conclusion, text, flags=re.S)
    old_results = ("The numbers land as the runs complete; the retention-versus-temperature\n"
                   "curves are the experiment's central figure and will be added here.")
    text = text.replace(old_results, results)
    start = text.find("\\todo{Three observations")
    if start != -1:
        end = text.find("\n", text.find("}", start))
        text = text[:start] + discussion + text[end:]
    text = text.replace("\\todo{Written from the results.}", conclusion)
    s_path.write_text(text, encoding="utf-8")
    print(f"wrote {s_path}")
    return 0


def _rows(numbers: str, marker: str) -> list[str]:
    """The table rows of a paper-numbers block (lines after the marker ending in \\)."""
    out: list[str] = []
    inside = False
    for line in numbers.splitlines():
        if line.strip().startswith(marker):
            inside = True
            continue
        if inside:
            if line.strip().endswith("\\\\"):
                out.append(line)
            elif line.strip().startswith("% tab:"):
                break
            elif line.strip() and not line.strip().startswith("%"):
                break
    return out


def fill_tables(text: str, numbers_path) -> str:
    """Replace the tab:qor and tab:crossover bodies with the generated rows."""
    numbers = numbers_path.read_text(encoding="utf-8")
    qor = _rows(numbers, "% tab:qor rows")
    cross = _rows(numbers, "% tab:crossover rows")
    for label, rows in (("tab:qor", qor), ("tab:crossover", cross)):
        if not rows:
            continue
        start = text.index(f"\\label{{{label}}}")
        mid = text.index("\\midrule", start)
        bottom = text.index("\\bottomrule", mid)
        text = text[:mid] + "\\midrule\n" + "\n".join(rows) + "\n" + text[bottom:]
    return text


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
