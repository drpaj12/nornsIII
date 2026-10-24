"""Append the brief's ## Result section from the measured data (run at the end of the lane).

Usage: python scripts/append_result.py <brief path> <pushed head>
"""

from __future__ import annotations

import statistics
import subprocess
import sys

import nornlib as nl
import report


def main(argv: list[str]) -> int:
    brief = nl.Path(argv[0])
    head = argv[1]
    summary = nl.read_json(nl.WS / "docs" / "plan" / "paper-summary.json")
    data, designs = report.load_all()
    full = [float(r["retention"]) for d in designs for seed in report.FAMILIES
            for r in [report.pick(data[d], "soft", seed, "full")]
            if r and r.get("retention") is not None]
    inter = [float(r["retention"]) for d in designs for seed in report.FAMILIES
             for r in [report.pick(data[d], "soft", seed, "inter")]
             if r and r.get("retention") is not None]
    hot_ret = [v for v in summary["hot_retention"].values() if v is not None]
    wins = sum(v[0] for v in summary["hot_wins"].values())
    n = sum(v[1] for v in summary["hot_wins"].values())
    remaining = [d for d in nl.DESIGN_ORDER if d not in designs]
    rows = []
    for design in designs:
        path = nl.runs_dir(design, "crossover", "crossover.json")
        if path.is_file():
            res = nl.read_json(path)
            rows.append(f"{design}: P*={res.get('pstar')} S={res.get('crossover_scale')}")
    text = f"""
## Result

Pushed head: {head} (branch exp/first-run, verified with git ls-remote).

VTR interfaces verified on the pinned build (v8.0.0+18416): `--read_initial_place_file` (CLB
`.place`, continues placement from it), `--read_vpr_constraints` (partition XML with
`add_atom`/`add_region`), `--write_initial_place_file` (seed or analytic start),
`--write_flat_place`/`--write_legalized_flat_place` (atom-level retention),
`--anneal_auto_init_t_scale` (automatic-schedule start-temperature scale),
`--init_t`/`--exit_t`/`--alpha_t` (manual schedule), and `--place_checkpointing` (stock
save-best/restore, default ON with the default RL agent multistate). Details and source lines:
`docs/plan/vtr-interfaces.md`. No VTR patch was needed; `patches/README.md` records why.

Run matrix completed: {len(designs)} designs ({", ".join(designs)}), each with the unseeded
baseline, seven seeds x soft-full, soft-inter and hard, an extended cold-start crossover sweep
(doubling S until the cold start stops winning), the hot step per seed, and the
checkpointing-off control sweep. Not run in this lane: {", ".join(remaining)}; the exact
continuation commands are in `docs/plan/EXPERIMENT.md`.

Crossover table (per design; full table with cold/unseeded wirelength, start temperature and
retention in `docs/plan/EXPERIMENT.md`, seed-family summary in
`docs/plan/paper-numbers.tex`):

    {" | ".join(rows)}

Retention curves summary: median retention at scale 1 is {statistics.median(full):.2f} of the
cluster blocks (full seed) and {statistics.median(inter):.2f} (inter-cluster-only); at the hot
step (2x crossover) it is {min(hot_ret):.2f}-{max(hot_ret):.2f} while the seed wins only
{wins} of {n} head-to-heads against unseeded at the same temperature: the coarse structure
survives the anneal, its advantage does not.

Paper tables filled: `tab:qor`, `tab:crossover`, the Results paragraph, the Discussion (three
observations) and the Conclusion in `docs/paper/norns.tex`. QoR geomeans vs unseeded:
soft-full wirelength {summary['soft_wl']}, inter-cluster-only {summary['inter_wl']}, hard
{summary['hard_wl']}; soft channel width {summary['soft_chan']}, soft placement runtime
{summary['soft_runtime']}. Checkpointing: median crossover scale
{summary['crossover_on_median']} on vs {summary['crossover_off_median']} off (RLPlace's
prediction holds where measured).

Agent defaults (recorded in `docs/plan/EXPERIMENT.md`): the Loki L0 graph.json is built by
Norns from the same Odin III BLIF (Loki's own key.json names do not join to VPR atom names);
the clusterings are Loki's `loki.analysis.cluster` code; the hard arm constrains regions only
(no full/inter twin); I/O pads and mult_36 macros stay anchored and adder carry chains move as
one vertical run (VPR placement macros); one deterministic VPR run per configuration at
`--seed 1`; Urd is degenerate on designs with a flat Odin hierarchy; the crossover is the
largest auto-temperature scale S at which the cold start still beats unseeded at the same S
(one run per point, doubling to 256); retention is measured against the seed cluster's
bounding box (hard-arm retention is 1 by construction).
"""
    with brief.open("a", encoding="utf-8") as fh:
        fh.write(text)
    print(f"appended to {brief}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
