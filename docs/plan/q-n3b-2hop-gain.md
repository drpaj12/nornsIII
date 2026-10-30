# Q-N3b: does a 2-hop connectivity gain term make APPack better on real designs? (plan written 2026-10-30, before the runs)

This file is committed and pushed before any VPR run. It is not edited after the runs; results are appended below under their own dated heading.

## Plain-English summary

Peter (2026-10-30), answering "So is the finding that your innovation picks better atoms and we should test it out on real designs?": "Sure, let's do it."
The innovation is the Q-N3 feature `members_2hop` (how many atoms of the open cluster lie within two hops of a candidate), which ranked the right atom
above the wrong pick with AUC 0.687 on the full round 9 view and 0.612 with the dummy atoms deleted. The test here is the one free of the round 9
construction: add that term to the APPack candidate gain and pack the 35 real E10 designs. Caveat from the controller, accepted: on D' with the dummies
deleted the combined score did not beat VPR (-5.2 and +0.1 points), so the prior is a small effect.

Path: Norns APPack questions ("what is APPack bad at ... and is there a way to make it better"): Q-N2 = bad at (wrong add with the right atom queued),
Q-N3 = data that ranks the right atom, Q-N3b = this. Purpose (hub docs/purpose.md): Norns packing quality. Measures in Peter's order: speed (post-route CPD,
near-critical endpoints), wirelength, area (CLBs); pack time is a cost.

## Hypothesis

H-2hop: adding w x h2 to the APPack candidate gain (w = 0.1 and w = 0.25) lowers post-route CPD, without raising CLBs or WL by more than 2%, against stock APPack
on the 35 E10 base designs.

## Overlay change (design, before writing the code)

* Option `--norns_2hop_weight <w>` (packer/vpr, default 0 = off, no code path differs from stock).
* h2(candidate molecule M, cluster Cl) = the Q-N3 feature `members_2hop` (scripts/q3feat.py): the number of atoms of Cl that are within two hops of an atom of M.
  One hop = two atoms share a net; nets with more than 32 sinks are ignored (the cap of q3feat, `q2gap.HF = 32`; clock nets and VPR-ignored/constant nets are
  also ignored, as q3feat's graph holds no clock net). Normalisation: h2 is divided by the number of atoms in Cl, so h2 is in [0, 1].
* New gain = (1 - w) x stock gain + w x h2, applied in `get_molecule_gain` after all stock terms (connectivity, timing, affinity bonus, tie-breakers, penalties)
  and BEFORE the APPack distance attenuation, which stays as stock and multiplies the blended gain.
* Incremental: when an atom joins the cluster, a bounded 2-hop breadth-first search (capped nets only) records, for every reached atom, the index of the cluster atom
  that reaches it. Evaluating a candidate is then a lookup (union over the atoms of the molecule). No change to seeds, legality, cluster closing, placement, routing.
* Log, one line when packing ends (only with w > 0): `Norns 2hop: w=<w> evals=<n> eval_time=<s> joins=<n> join_time=<s>`.
* Queue-time gains are stale in stock too (a queued molecule keeps the gain it had when queued); h2 follows the same rule. Stated, not changed.

## Gate (before any arm)

`--norns_2hop_weight 0` gives a `.net` byte-identical (sha256) to the stock keep-sweep `.net` on all 35 designs x VPR seeds 1, 2, 3 (105 packs, `--pack` only).
If it fails, stop and fix. A unit test of h2 on a tiny netlist (hand-computed) comes with the overlay.

## Arms and runs

* stock (the new binary, no option), w = 0.1, w = 0.25. The weights are fixed here; no tuning on the result.
* Designs: the 35 of E10 base (15 VTR Verilog + 20 MCNC), flags of the e10_main `base` config (K6 Norns architecture, default ABC netlists from the keep sweep,
  stock analytical flow with APPack, `vpr_sa`), VPR seeds 1-3, smallest first (LUT count). 315 runs. VPR under `/tmp/claude-1000/norns-vpr.lock`, memory <= 14 GB.
* Measures per run: CPD, n_endpoints_090/095/099 (kept 1000-path report, mimir.timing as refresh-crit), WL, CLBs, pack time, total VPR time.
* Secondary (mechanism only, after the main runs and only if the week allows): on 5 round 9 D' (own C) the share of right-atom picks (Q-N2 class b count) per arm.

## Statistics and verdict rule (said before the runs; as docs/plan/refresh-crit.md)

* Per design and metric: ratio arm/stock per seed (same seed), geometric mean over the 3 seeds. Pooled: geometric mean over designs (n = 35; also 20 MCNC and 15 VTR
  Verilog), 90% percentile bootstrap over designs (10000 resamples, seed 20261030). Ratio below 1 is better for every metric.
* CAD-style report first (memory cad-reporting-convention), per metric in the order speed (CPD, then near-critical counts), WL, area (CLBs): the geomean % win
  (100 x (1 - ratio)) and wins/losses/ties over designs (tie = within 0.5%), split VTR Verilog vs MCNC. Then the strict register verdict.
* Two-sided percentile-bootstrap p of H0 geomean = 1; Holm over the family of 12 tests (2 arms x CPD, n_endpoints_090/095/099, WL, CLBs). Times descriptive.
* Verdict per arm (CPD claim with the cost clause), thresholds 2%:
  * USEFUL: CPD pooled upper 90% bound < 1.000, Holm p < 0.05, CPD geomean < 1 in both suites, CLB and WL point estimates <= 1.02.
  * POSSIBLY GOOD: CPD upper bound < 1.000 and CLB, WL point estimates <= 1.02, but Holm p >= 0.05 or one suite has CPD geomean >= 1.
  * DISMISSED: the CPD interval wholly inside [0.98, 1.02] or wholly above 1.000, or a CLB or WL point estimate > 1.02 with a CPD point estimate not below 0.98.
    A CPD gain with CLB or WL > 1.02 is INCONCLUSIVE with the cost stated.
  * INCONCLUSIVE: anything else. A positive geomean win with a CI touching 1 is INCONCLUSIVE, not DISMISSED.
* Failed runs (non-zero exit, unroutable) are listed; a design with a failed run in an arm leaves that design out of that arm's pooled ratios (stated).
