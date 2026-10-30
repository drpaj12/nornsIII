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

---

# Results (2026-10-30)

Plan commit 6b0dfa7 (written before the runs); overlay commit and gate commit on `exp/q-n3b-2hop`. Tool: nornsIII `exp/q-n3b-2hop`, VPR 3c9a4d23b2 with the overlay,
private tree `work/norns-vtr-2hop` (`packer/build.sh`). Code: `packer/vpr/src/pack/{norns_twohop.h,greedy_candidate_selector.cpp}`, `scripts/q3b_gate.py`,
`q3b_run.sh`, `q3b_stats.py`, configs `h1` and `h25` in `scripts/e10_main.py`; unit test `tests/test_twohop.py` (`packer/tests/twohop_test.cpp`).
Data: `data/analysis/q3b-gate.json`, `data/analysis/q3b-stats.json` (per-run measures, per-design ratios, all intervals).

## Plain-English summary

Adding the "how many atoms of the cluster are two hops away" term to APPack's gain did not make the packed designs faster, shorter in wire or smaller on the
35 real designs. At w = 0.1 the critical-path delay is 0.7 percent lower (17 wins, 14 losses, 4 ties of 35), which is inside the noise (90 percent interval
-1.9 to +0.6 percent). At w = 0.25 it is 1.9 percent worse. Wirelength and CLBs do not move beyond 1 percent either way. The number of near-critical endpoints
falls (14 to 19 percent, pooled geomean over designs) but no test survives the Holm correction, the same pattern as H-refresh, and the critical path does not
follow. w = 0.25 is DISMISSED and w = 0.1 INCONCLUSIVE (relabelled by the controller 2026-10-30 under the CAD convention; see Verdicts). The prior from Q-N3 (a small effect on D' with the dummies deleted) held: the term that ranks the right
atom better on the round 9 benchmark does not carry over to real designs as a gain.

## Gate

`--norns_2hop_weight 0`: `.net` byte-identical (sha256) to the stock keep-sweep `.net` on 35 of 35 designs x 3 seeds (105 of 105, pack only); with the option absent, 3 of 3
spot checks (stereovision3, ch_intrinsics, diffeq2, seed 1). The new code is inert at w = 0 (no log line, no changed path). The tiny-netlist unit test of the 2-hop index passes.
The gate `.net` files are kept uncompressed in `work/q3b-out/gate` (not gzipped; nothing was deleted).

## Sweep

315 runs (35 designs x seeds 1-3 x 3 arms: stock = the new binary, no option; w = 0.1; w = 0.25), E10 `base` flags, kept timing on, all rc 0 and routed, 0 failed.
VPR under the Norns VPR lock. Mechanism cost of the term (105 runs per arm): w = 0.1: 5.95 M gain evaluations in 0.69 s and 416,697 atom joins in 4.0 s in total;
w = 0.25: 5.89 M evaluations in 0.68 s and 416,529 joins in 4.0 s. The term itself is cheap (about 0.1 microsecond per evaluation, 10 microseconds per join).

## CAD-style report (ratio arm/stock, geomean over seeds then designs; win = 1 - ratio; tie = within 0.5 percent; 90 percent bootstrap over designs)

Order: speed (CPD, then near-critical endpoints), wirelength, area. W/L/T = wins, losses, ties over designs. VTR = the 15 Verilog designs, MCNC = the 20 MCNC designs.

w = 0.1:

| metric | all 35: geomean win [90% interval] | W/L/T | VTR 15: win, W/L/T | MCNC 20: win, W/L/T |
|---|---|---|---|---|
| speed CPD | +0.67% [-0.58, +1.85] | 17/14/4 | +1.24%, 7/7/1 | +0.24%, 10/7/3 |
| endpoints >= 0.90 | +13.60% [+2.08, +24.22] | 17/13/5 | +9.77%, 7/6/2 | +16.36%, 10/7/3 |
| endpoints >= 0.95 | +6.45% [-5.32, +17.12] | 18/13/4 | +14.03%, 9/3/3 | +0.33%, 9/10/1 |
| endpoints >= 0.99 | +7.14% [-11.92, +22.86] | 14/14/7 | +34.60%, 8/4/3 | -20.79%, 6/10/4 |
| WL | -0.22% [-1.19, +0.73] | 15/16/4 | -0.92%, 6/7/2 | +0.30%, 9/9/2 |
| area CLBs | -0.56% [-1.17, +0.05] | 9/14/12 | +0.31%, 5/2/8 | -1.21%, 4/12/4 |
| pack time | -6.41% [-8.18, -4.65] (slower) | 1/33/1 | -5.05%, 0/14/1 | -7.44%, 1/19/0 |
| total VPR time | -1.95% [-3.75, -0.17] (slower) | 13/21/1 | -0.48%, 8/6/1 | -3.06%, 5/15/0 |

w = 0.25:

| metric | all 35: geomean win [90% interval] | W/L/T | VTR 15: win, W/L/T | MCNC 20: win, W/L/T |
|---|---|---|---|---|
| speed CPD | -1.93% [-3.96, -0.02] | 15/17/3 | -0.18%, 7/7/1 | -3.27%, 8/10/2 |
| endpoints >= 0.90 | +19.46% [+5.87, +31.62] | 17/14/4 | +7.32%, 5/8/2 | +27.51%, 12/6/2 |
| endpoints >= 0.95 | +17.56% [+1.55, +31.14] | 18/14/3 | +26.08%, 7/5/3 | +10.53%, 11/9/0 |
| endpoints >= 0.99 | +13.90% [-0.03, +26.58] | 14/12/9 | +25.24%, 6/6/3 | +4.29%, 8/6/6 |
| WL | -1.01% [-2.02, -0.03] | 13/17/5 | -1.18%, 6/7/2 | -0.89%, 7/10/3 |
| area CLBs | +0.11% [-0.44, +0.65] | 12/11/12 | +0.34%, 6/2/7 | -0.07%, 6/9/5 |
| pack time | -4.86% [-6.78, -2.99] (slower) | 8/26/1 | -2.13%, 5/9/1 | -6.95%, 3/17/0 |
| total VPR time | -1.83% [-4.27, +0.39] (slower) | 13/18/4 | -0.18%, 7/7/1 | -3.08%, 6/11/3 |

Pooled ratios (arm/stock, same numbers): w = 0.1: CPD 0.993 [0.982, 1.006], endpoints 0.864 / 0.936 / 0.929, WL 1.002, CLBs 1.006, pack time 1.064, total 1.020;
w = 0.25: CPD 1.019 [1.000, 1.040], endpoints 0.805 / 0.824 / 0.861, WL 1.010, CLBs 0.999, pack time 1.049, total 1.018. Holm p over the 12 tests: smallest 0.288
(w = 0.25, endpoints >= 0.90); CPD 1.000 and 0.846. The endpoint counts are floored at 1 for the ratio (as in refresh-crit). Pack time rises 5 to 6 percent although the
term itself costs under 5 s in total; the rise is not diagnosed (a candidate reason: the blended gain changes which molecules are tried and refused; machine load was not controlled).

## Verdicts (rule as written in the plan, applied unchanged)

* w = 0.1: **INCONCLUSIVE** (relabelled by the controller 2026-10-30 under the CAD convention; the first run of the rule wrote DISMISSED). CAD view: CPD +0.67% geomean win [-0.58, +1.85] (ratio 0.993 [0.982, 1.006]), 17 W / 14 L / 4 T over 35 designs; not separable from noise at this sample size. WL -0.22% (15 / 16 / 4) and CLBs -0.56% (9 / 14 / 12) are small losses, so it is a speed-versus-WL/area trade-off; pack time 6.4% slower. A positive geomean whose interval touches 1 is INCONCLUSIVE, not DISMISSED.
* w = 0.25: **DISMISSED**. CPD 1.019 [1.000, 1.040]: the interval is wholly above 1.000 (worse) with its lower bound at 1.0002; WL 1.010 and CLBs 0.999 within 2 percent.
* H-2hop (CPD lower without raising CLBs or WL by more than 2 percent): not supported at w = 0.25 (dismissed) and not shown at w = 0.1 (inconclusive). The CAD-style positive geomean win of the near-critical endpoint
  counts is reported, but those tests are not significant after Holm (smallest p 0.288) and the CPD does not follow, so it is not a verdict basis.

## Not met / limits

* Mechanism check on 5 round 9 D' (share of right-atom picks per arm) was not run: the main result is a clear no on real designs, and the week meter was at 92 percent.
  So we do not know whether the term picks more right atoms in the packer on D'; Q-N3 said it ranks them better offline.
* Two weights only (fixed before the runs, no tuning). h2 is normalised by the cluster's atom count, computed at queue time (stale like all queue-time gains).
* Only the stock analytical flow with APPack was run. The term acts only where the connectivity step queues candidates; timing-pull picks (63 percent of the wrong picks in Q-N3) are not addressed by it.
