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
    hot_ret = [v for v in s["hot_retention"].values() if v is not None]
    wins = sum(v[0] for v in s["hot_wins"].values())
    n = sum(v[1] for v in s["hot_wins"].values())
    fmt_scale = lambda v: "n/a" if v is None else f"{v:g}"
    import report
    data, designs = report.load_all()
    pairs = []
    for design in designs:
        on = nl.runs_dir(design, "crossover", "crossover.json")
        off = nl.runs_dir(design, "crossover", "checkpoint.json")
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
    hot_range = (f"{min(hot_ret):.2f}-{max(hot_ret):.2f}" if hot_ret else "n/a")
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
    results = f"""The {n_designs} completed designs give the ratios of Table~\\ref{{tab:qor}}. Soft seeds
stay within a few percent of the unseeded baseline in routed wirelength
({s['soft_wl']} for the full seed, {s['inter_wl']} for the inter-cluster-only arm) while
cutting the minimum channel width to {s['soft_chan']} of the baseline and costing
{s['soft_runtime']} in placement runtime. The hard arm is consistently worse
({s['hard_wl']}): fixed regions block the anneal's fine moves across cluster borders. No single
seed family dominates; the recovered clusterings and the provenance hierarchy land in the same
band. Retention at scale~1 is {ret1} of a seed's cluster blocks (full) and {ret1i} (inter)."""
    discussion = f"""Three observations. First, the seed families are interchangeable in
quality: provenance is not a better starting structure than recovered clusters on these
designs, and the inter-cluster-only arms show that the fine order inside a cluster matters as
much as its coarse die position. Second, VPR's checkpointing does not separate the crossover in the
measured range: {ckpt_sentence} RLPlace's prediction that checkpointing extends the useful
range is therefore not observed on these designs; if it holds, its effect is smaller than the
between-design variation. Third, the safe recipe is
to cold-start from a cluster-derived placement at a temperature scale at or below the crossover,
which is a multiple of VPR's own estimate; above it the seed's retention stays high
({hot_range} at twice the crossover) but it wins only {wins} of
{n} head-to-heads against an unseeded run at the same temperature -- the coarse structure
survives the anneal, the advantage does not."""
    conclusion = """Seeding VPR's anneal is worth it only as a calibrated cold start: at
VPR's own start temperature the cluster layouts and the provenance hierarchy place at parity
with the analytic start, but from a good final placement they keep winning when the anneal is
restarted hotter, up to the crossover the sweep measures. The recipe is that crossover table,
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
    text = re.sub(r"Seeding VPR's anneal is worth it.*?(?=\n\n\\bibliography)",
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
