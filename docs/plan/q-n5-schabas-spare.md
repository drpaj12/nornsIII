# Q-N5: does loosening the clustering inside the same square FPGA buy speed? (Schabas packing) (plan written 2026-10-30, before the runs)

This file is committed and pushed before any VPR run. It is not edited after the runs; results are appended below under their own dated heading.

## Plain-English summary

Peter (2026-10-30), verbatim: "My feel is we should go down the schabas path with a slight restriction where we say that after clustering that determines the
size of the FPGA (squared) so we will round up to make a square FPGA which suggests how much space we have to loosen the clustering by - this is a known (as we
did it once). Let's build out this idea and test Karl's ideas. of first not packing."

The question: stock VPR packs as tightly as it can, then the FPGA is made just big enough (and square). The chip then has some CLB tiles the design does not
use. Schabas and Brown (FPGA 2003, `schabas2003duplication`) spent such room on purpose: in the most timing-critical clusters they left a few BLEs empty
(packing change alone, no duplication). The test here keeps the chip exactly as big as stock needs and spends the spare tiles on loosening the critical
clusters. Does the design then run faster, with the same chip? This is Karl's first idea (the packing change) only. Duplication after placement (the second
half of Schabas) is a later question and is not built here.

Path: Norns packing quality (hub docs/purpose.md). Measures in Peter's order: speed (post-route critical-path delay, near-critical endpoints), wirelength,
area. Area here is the DEVICE SIZE (grid), which is held fixed and equal to stock's; the CLBs used rise by design and are reported, not counted as a loss.

Schabas's own numbers, as stated in the paper and the controller recompute (labelled, not ours): packing change alone, s = 4, 20 MCNC circuits, 4-LUT
architecture, 5 seeds, channel width 1.2 x Wmin: the paper's Table 1 total gain 6.4% (post-route critical path); the controller recompute of Table 1 as a
geomean gives 7.3% faster (16 wins, 4 losses); pre-route critical path (Table 2) 5.8% WORSE, i.e. the paper's gain is routing relief, not a shorter placed
path. Their s sweep (Fig. 4): packing alone is best near s = 2 and falls above s = 5. Which of our 20 MCNC designs are in Schabas's 20: all 20 (alu4,
apex2, apex4, bigkey, clma, des, diffeq, dsip, elliptic, ex1010, ex5p, frisc, misex3, pdc, s298, s38417, s38584.1, seq, spla, tseng are the Table 1
circuits and the VTR 20 MCNC list). So the MCNC split is a replication on modern VPR (K6 fracturable-LUT architecture, N = 10, VTR 3c9a4d23b2 timing-driven
APPack flow instead of T-VPack, annealing placer) and the 15 VTR Verilog designs are new.

## Hypothesis

H-spare-s (s = 2 and s = 4, two hypotheses H-spare-2 and H-spare-4): inside the stock square grid of each design, leaving s BLEs empty in the clusters whose seeds
are most timing critical (as many clusters as the spare CLB tiles allow) lowers post-route CPD against stock, without changing the grid, and without raising WL
by more than 2%. (CLBs used is expected to rise and is reported; it does not count as a loss because the chip size is fixed.) A pack that does not fit the fixed
grid counts as a loss for that design (reported).

## The device-size rule (Peter)

* Pass 1: stock pack and VPR's auto layout of the architecture (`k6_frac_N10_frac_chain_mem32K_40nm`; `<auto_layout aspect_ratio="1.0">`, i.e. square by
  construction; checked on all 35 stock runs of the keep sweep: width = height on every design). The grid W x H of pass 1 is read from the stock run's log
  ("FPGA sized to W x H"), the CLB tiles of the grid and the stock CLBs from its "Resource usage" block. If W != H on any design the rule would round up to
  the smallest square holding stock's CLBs, IOs and hard blocks; none needed it.
* The grid is then FIXED for every arm of that design (all seeds): a per-design copy of the architecture file with `<fixed_layout name="spare" width=W height=H>`
  in place of the auto layout (same perimeter, fill, mult and memory columns; the layout section only), run with `--device spare`. This is how VPR 3c9a4d23b2
  takes a fixed device (`<fixed_layout>` and `--device <name>`). The stock arm is also run on the fixed grid.
* spare(design) = CLB tiles of the grid minus stock's CLBs. Per design the spare and what sets the grid (CLB, IO, memory/multiplier) are reported: a design
  whose grid is set by IOs or hard blocks has a large spare (most of the 35 here).

## What one "BLE" is, and the overlay rule

* The architecture has `clb` with 10 `fle` instances (N = 10). One BLE = one occupied `fle` instance of the cluster's pb tree at that moment: a fracturable fle
  holding two LUT5 (or a LUT6, or a LUT with its FF, or one adder-chain element) counts as one BLE. A carry-chain molecule spanning k fle counts k.
* Cluster budget (Schabas Eq. 7 with DeviceSize = the CLB tiles of the fixed grid): n = floor(spare x N / s), capped at the number of stock logic clusters
  (so the sum of the empty slots, n x s, does not exceed the room the spare tiles provide, N x spare).
* Which clusters are "timing critical": modern VPR does not seed by criticality alone (blend2 mixes criticality and input pins), so we define it directly: the
  criticality of a cluster is the pre-pack setup criticality of its seed molecule, = the maximum over its atoms of VPR's `calc_atom_setup_criticality` (the
  maximum over the atom's input pins, computed from the pre-cluster timing that VPR already builds before packing). Pass 1 (stock pack with a log-only dump) lists
  the seed criticality of every stock logic cluster; the threshold T is the n-th highest value (all clusters if n >= the number of stock clusters). In the
  arm run, a logic cluster qualifies when its seed criticality >= T and fewer than n clusters have qualified so far; it is grown by the stock rule until it holds N - s
  BLEs and then closed. Clusters that do not qualify are stock. Everything else (seed order, gains, legalizer) is stock. A multi-BLE molecule can push a qualified cluster
  past N - s; this is counted ("overshoot") and reported.
* Options (packer/vpr): `--norns_spare_bles s`, `--norns_spare_clusters n`, `--norns_spare_crit_min T`, `--norns_spare_dump FILE` (log-only: per logic cluster seed
  criticality, qualified, BLEs, atoms). With s = 0 the code is inert.

## Gate (before any arm)

`--norns_spare_bles 0` (with the dump on, and with the options absent) on the FIXED grid gives a `.net` byte-identical (sha256) to the stock keep-sweep `.net` of the
same design and seed, on all 35 designs x VPR seeds 1, 2, 3 (105 packs, `--pack` only). If it fails, stop and fix.

## Arms and runs

* stock (fixed grid), s = 2, s = 4 (Schabas's value). Fixed before the runs, no tuning.
* 35 E10 base designs (15 VTR Verilog + 20 MCNC), the keep sweep's Odin III netlists, E10 `base` flags (K6 Norns architecture, stock analytical flow with APPack,
  `vpr_sa` arm of `placers_main.py`, kept 1000-path timing), VPR seeds 1, 2, 3, smallest first (LUT count). Memory <= 14 GB, VPR under the Norns VPR lock.
* Channel width, both reported. The E10 base flow does NOT route at a fixed relaxed width: with no `--route_chan_width` VPR searches the minimum width and reports the
  result at that minimum (so each arm is measured at its own Wmin). (a) = that flow as is: post-route CPD at each arm's own Wmin, Wmin reported. (b) = Schabas's
  setting: every arm of a design and seed routes at the fixed W = ceil(1.2 x Wmin of the stock arm of the same design and seed from (a)). 2 x 3 x 3 x 35 = 630 runs.
* Measures per run: post-route CPD, pre-route (placement-estimated) CPD ("Placement estimated critical path delay"), n_endpoints_090/095/099 (kept report, mimir.timing as
  refresh-crit), WL, CLBs, grid (must equal stock's), Wmin (a), pack/place/route time, total VPR time.

## Statistics and verdict rule (said before the runs; as q-n3b-2hop-gain.md)

* Per design and metric: ratio arm/stock per seed (same seed), geometric mean over the 3 seeds. Pooled: geometric mean over designs (n = 35; also 15 VTR, 20 MCNC =
  the Schabas-overlap subset), 90% percentile bootstrap over designs (10000 resamples, seed 20261030). Ratio below 1 is better for every metric.
* CAD-style report first (memory cad-reporting-convention), per metric in the order speed (post-route CPD, pre-route CPD, then near-critical counts), WL, area
  (CLBs used, with the grid fixed): geomean % win (100 x (1 - ratio)) and wins/losses/ties over designs (tie = within 0.5%), VTR vs MCNC, per channel-width setting.
  Then the strict register verdict.
* Two-sided percentile-bootstrap p of H0 geomean = 1; Holm over the family of 12 tests inside each channel-width setting (2 arms x post-route CPD, n_endpoints_090/095/099,
  WL, CLBs). Times descriptive.
* Verdict per arm and setting (CPD claim with the cost clause), thresholds 2%:
  * USEFUL: CPD pooled upper 90% bound < 1.000, Holm p < 0.05, CPD geomean < 1 in both suites, WL point estimate <= 1.02.
  * POSSIBLY GOOD: CPD upper bound < 1.000 and WL point estimate <= 1.02, but Holm p >= 0.05 or one suite has CPD geomean >= 1.
  * DISMISSED: the geomean points the wrong way (CPD ratio >= 1) with the interval wholly above 1.000 or wholly inside [0.98, 1.02], or the CI excludes the claimed effect (interval wholly
    inside [0.98, 1.02]); a CPD gain with WL > 1.02 is INCONCLUSIVE with the cost stated.
  * INCONCLUSIVE: anything else. A positive geomean win whose interval touches 1 is INCONCLUSIVE, not DISMISSED.
  CLBs used is not part of the cost clause (the chip is fixed); a design that does not fit the fixed grid is a loss on every metric for that design and is listed.
* Failed runs (non-zero exit, unroutable) are listed; a design with a failed run in an arm leaves that design out of that arm's pooled ratios unless the failure is "does not fit the
  grid", which is counted as a loss (ratio set to the worst ratio observed for that metric, reported separately).

## Mechanism (same runs, cheap)

* Routing relief or a shorter path: pre-route CPD change vs post-route CPD change per arm, and the Wmin change (a).
* Share of the near-critical connections inside spare-room clusters: from the dump (atoms of qualified clusters) and the kept 1000-path report of the same run, the share of
  the path endpoints with criticality >= 0.90 whose driver lies in a qualified cluster, against the share of all atoms in qualified clusters.
* Spare per design, clusters qualified, closed at the limit, overshoot (from the `Norns spare:` log line).

Out of scope: duplication after placement; other values of s; tuning of the threshold rule.

---

# Results (2026-10-30)

Plan commit c85317d (written before the runs). Tool: nornsIII `exp/q-n5-spare`, VPR 3c9a4d23b2 with the overlay, private tree `work/norns-vtr-spare` (`packer/build.sh`).
Code: `packer/vpr/src/pack/greedy_clusterer.cpp` (rule), `norns_affinity.h/.cpp`, `base/read_options.*`, `setup_vpr.cpp`; `scripts/q5_prep.py`, `q5_gate.py`, `q5_run.py`, `q5_stats.py`;
`tests/test_q5.py`. Data: `data/analysis/q5-prep.json` (grid, spare, n and T per design), `q5-gate.json`, `q5-stats.json` (per-run measures, per-design ratios, all intervals).

## Plain-English summary

Keeping the chip exactly as big as stock needs and leaving 2 or 4 BLEs empty in the most timing-critical clusters did not make the designs faster. It made them slightly
slower: post-route critical-path delay is 1.4 to 2.1 percent worse (geomean over 35 designs), wirelength 2 to 3 percent worse, CLBs used 11 to 17 percent higher. The
sign is the opposite of Schabas and Brown's 6.4 percent gain from the same packing change, and the placed (pre-route) delay is worse too (1.8 to 2.8 percent), which is
what they also saw; what they saw and we do not is the routing relief that turns the worse placed delay into a better routed one. Verdicts: s = 4 is DISMISSED in both
channel-width settings; s = 2 is INCONCLUSIVE in the E10 flow (the interval reaches 1) and DISMISSED at fixed 1.2 x Wmin. Three of the 35 designs have a spare of at most 2 CLB
tiles, 15 have a spare of at least a quarter of their CLBs; the result does not depend on that split (both worse).

## Gate

On the fixed grid, `--norns_spare_bles 0` with the dump on: `.net` byte-identical to the stock keep-sweep `.net` on 105 of 105 (35 designs x seeds 1-3, `--pack`); with only `--device spare`
(no Norns option): 35 of 35 (seed 1). The comparison blanks the `architecture_id` attribute (the only line that differs: the fixed-layout architecture file hashes differently from
the stock one). A first gate run was repeated after the overlay fix below (final binary: 105/105 and 35/35). Data: `data/analysis/q5-gate.json`.

## The grid and spare rule as built

Pass 1: all 35 stock auto grids are square (width = height). Grid W x H per design is read from the stock log and fixed through `<fixed_layout name="spare">` + `--device spare`
(per-design architecture copy, layout section only). Spare = CLB tiles - stock CLBs; what sets the grid: CLB 21 designs, IO 7, multipliers 4, memories 3. Spare ranges from 1 CLB
tile (tseng, misex3) to 2835 (stereovision2); 15 designs have a spare of at least 25 percent of their CLBs. n = floor(spare x 10 / s) capped at the stock logic clusters; T = the n-th
highest seed criticality of the stock logic clusters (pass-1 dump). A BLE = an occupied `fle` of the cluster pb tree (10 per CLB). Per design table: `q5-prep.json`.
Totals over the 3 seeds (setting a): s = 2: 12,732 of 21,846 logic clusters qualified, 10,407 closed at N - s, 1,923 ended above N - s (a molecule spanning several BLEs); s = 4: 11,442 of
23,871 qualified, 11,070 closed at the limit, 2,178 overshoot.

Fix found during the smoke run (before any result): VPR re-packs (unrelated clustering and balanced block types) when a pack does not fit the device, so `do_clustering` can run twice;
the budget counter and dump were not reset per call, so the second pack was stock-like. Reset added, binary rebuilt, the gate rerun, and the smoke runs moved aside
(`work/q5-out/discarded-prefix-bug`, not deleted). Not a change of the plan.

## Sweep

630 runs (35 designs x seeds 1-3 x 3 arms x 2 settings). Setting (a) = E10 base flow, min-width search, each arm measured at its own Wmin. Setting (b) = every arm routes at
W = 2 x ceil(1.2 x Wmin of the stock arm of the same design and seed / 2) (rounded up to even because VPR's unidirectional routing needs an even width; the first (b) runs with odd W failed in
check_setup after 0.04 s and were re-run). 622 of 630 runs produced measures. Failed: seq s = 2 (all 3 seeds, both settings): the loosened pack needs 89 CLBs, the fixed grid has 88
("Failed to find device which satisfies resource requirements"): counted as a LOSS on every metric (worst ratio observed for that arm and metric). sha stock seed 3 in (b) and mkPktMerge s = 4
seed 1 in (b) did not route at 1.2 x Wmin ("VPR failed to implement circuit"): the design leaves that setting's pooled ratios for the affected arm(s) (sha for both arms, mkPktMerge for s = 4: n = 34 and 33).
In 45 of 102 (s = 2) and 42 of 105 (s = 4) runs VPR's first pack did not fit and it re-packed with unrelated clustering on (stock: 0 of 105).

## CAD-style report (geomean win = 100 x (1 - ratio) over designs, 90% bootstrap over designs; tie within 0.5%; W/L/T over designs)

Absolute geomeans over the runs (stock / s = 2 / s = 4), setting (a): post-route CPD 5.85 / 5.93 / 5.94 ns; pre-route CPD 5.16 / 5.28 / 5.31 ns; n_endpoints >= 0.90 16.9 / 14.5 / 15.6; >= 0.95 6.7 / 6.1 / 6.9; >= 0.99 2.1 / 1.9 / 1.9;
WL 14,041 / 14,418 / 14,479; CLBs used 94.4 / 104.7 / 110.0; Wmin 50.7 / 50.0 / 49.8; pack time 0.86 / 0.88 / 0.94 s; total VPR time 4.7 / 5.0 / 5.0 s. Setting (b): CPD 5.48 / 5.62 / 5.64;
pre-route 5.14 / 5.27 / 5.33; WL 12,695 / 13,062 / 13,007; CLBs 94.1 / 104.7 / 111.7; total time 2.0 / 2.1 / 2.2 s. (Geomean of the per-run values over the runs that finished; the tables below are of per-design ratios.)

Setting (a), E10 flow (Wmin each):

| metric | s = 2 all 35 | W/L/T | VTR 15 | MCNC 20 (= the Schabas 20) | s = 4 all 35 | W/L/T | VTR 15 | MCNC 20 |
|---|---|---|---|---|---|---|---|---|
| speed: post-route CPD | -1.42% [-3.07, +0.19] | 12/21/2 | -1.39% | -1.45% | -1.54% [-2.80, -0.23] | 10/23/2 | -1.81% | -1.35% |
| speed: pre-route CPD | -2.10% [-3.33, -0.97] | 7/22/6 | -1.51% | -2.54% | -2.78% [-3.97, -1.71] | 4/26/5 | -3.47% | -2.26% |
| speed: endpoints >= 0.90 | +12.21% [+0.27, +22.80] | 20/13/2 | +15.93% | +9.31% | +7.74% [-2.48, +16.93] | 16/14/5 | +13.76% | +2.95% |
| speed: endpoints >= 0.95 | +5.77% [-13.60, +21.71] | 18/14/3 | +20.63% | -7.17% | -2.41% [-14.47, +8.55] | 19/14/2 | +3.72% | -7.26% |
| speed: endpoints >= 0.99 | +5.99% [-12.49, +21.21] | 15/13/7 | +24.53% | -10.85% | +7.25% [-7.25, +19.40] | 16/11/8 | +15.91% | +0.18% |
| WL | -2.19% [-3.23, -1.15] | 7/22/6 | -3.13% | -1.50% | -3.11% [-4.19, -2.07] | 6/26/3 | -5.08% | -1.66% |
| area: CLBs used (grid fixed) | -10.78% [-15.27, -5.92] | 5/27/3 | -16.30% | -6.82% | -16.45% [-22.73, -10.14] | 4/30/1 | -29.79% | -7.36% |
| Wmin | +0.83% [-0.43, +2.08] (ratio 0.992 as win) | 17/11/7 | +2.27% | -0.26% | +1.66% [+0.18, +3.17] | 19/10/6 | +3.49% | +0.26% |

(Wmin: win = fewer tracks; an arm/stock ratio of 0.992 means 0.8% fewer.) Setting (b), fixed W = 1.2 x stock Wmin:

| metric | s = 2 all 34 | W/L/T | VTR | MCNC | s = 4 all 33 | W/L/T | VTR | MCNC |
|---|---|---|---|---|---|---|---|---|
| speed: post-route CPD | -1.63% [-2.66, -0.62] | 10/21/3 | -1.37% | -1.81% | -2.08% [-3.35, -0.88] | 10/20/3 | -2.49% | -1.81% |
| speed: pre-route CPD | -1.75% [-3.08, -0.50] | 8/21/5 | -1.27% | -2.09% | -2.72% [-4.11, -1.40] | 7/21/5 | -3.82% | -2.02% |
| speed: endpoints >= 0.90 | -0.02% [-9.53, +9.01] | 12/16/6 | +13.74% | -10.94% | +2.61% [-9.09, +14.31] | 12/16/5 | +10.28% | -2.73% |
| speed: endpoints >= 0.95 | -7.84% [-25.05, +7.58] | 12/18/4 | +4.42% | -17.35% | -3.75% [-21.61, +10.99] | 13/17/3 | -0.47% | -5.94% |
| speed: endpoints >= 0.99 | -17.39% [-41.56, +2.14] | 16/15/3 | -13.19% | -20.43% | -3.16% [-19.40, +10.55] | 14/13/6 | -17.03% | +4.97% |
| WL | -2.31% [-3.20, -1.40] | 6/27/1 | -1.62% | -2.80% | -2.55% [-3.56, -1.53] | 6/23/4 | -3.10% | -2.20% |
| area: CLBs used (grid fixed) | -10.65% [-15.18, -5.71] | 5/26/3 | -16.36% | -6.82% | -16.76% [-23.51, -9.88] | 4/28/1 | -32.84% | -7.36% |

Schabas-overlap subset = the 20 MCNC designs (all 20 are in Table 1 of the paper): post-route CPD -1.45% / -1.35% (a), -1.81% / -1.81% (b) for s = 2 / s = 4, against the paper's +6.4% (and the controller recompute +7.3%, 16 W / 4 L) for s = 4.
Time cost: pack time +2% / +9% in (a) is dominated by the re-packs; total VPR time similar (descriptive).

## Verdicts (rule as written in the plan, applied unchanged; Holm over 12 tests per setting)

* s = 2, E10 flow (a): **INCONCLUSIVE**. CPD ratio 1.014 [0.998, 1.031], Holm p 0.87: the geomean points the wrong way (1.4% slower) but the interval [0.998, 1.031] is neither wholly above 1.000 nor inside [0.98, 1.02]. WL 2.2% and CLBs 10.8% worse (WL Holm p 0.008).
* s = 2, fixed W (b): **DISMISSED**. CPD 1.016 [1.006, 1.027], wholly above 1.000 (Holm p 0.063).
* s = 4, (a): **DISMISSED**. CPD 1.015 [1.002, 1.028], wholly above 1.000. (b): **DISMISSED**, CPD 1.021 [1.009, 1.033], Holm p 0.024.
* H-spare-2 and H-spare-4 (post-route CPD lower inside the fixed grid, WL cost within 2%): not supported. Both arms also fail the cost clause (WL 1.022 to 1.031 > 1.02 in (a)).
  Only WL and CLBs survive Holm (as losses), and post-route CPD at s = 4 in (b) (Holm p 0.024, a loss).

Note on signs: a positive "win" for the endpoint rows means fewer near-critical endpoints (ratio below 1); +12.21% at s = 2 in (a) is a ratio of 0.878 with Holm p 0.65. It does not carry to CPD.

## Mechanism

* Routing relief or a shorter path (setting a): pre-route CPD ratio 1.021 [1.010, 1.033] (s = 2) and 1.028 [1.017, 1.040] (s = 4); post-route 1.014 and 1.015. The loosened packs place slower (as Schabas's Table 2),
  and routing recovers 0.7 and 1.3 points of that, but not all of it, so there is no net routing relief; the paper's relief that flipped the sign is absent. Wmin: ratio 0.992 [0.979, 1.004] (s = 2) and 0.983 [0.968, 0.998] (s = 4): up to 1.7% fewer tracks, a small congestion gain, far below the 1.4 to 3 point placement and WL cost.
* Share of near-critical-path atoms (paths within 90% of the longest in the kept 1000-path report) that lie in a spare-room cluster, mean over runs (setting a): s = 2 54.7% against a base rate (share of all atoms in qualified clusters) of
  56.8%; s = 4 40.9% against 36.7%. So the qualified clusters hold no more of the near-critical atoms than their share of the design (with s = 2, nearly all clusters qualify; with s = 4 the criticality selection is only 4 points above chance).
* Spare size: designs with a spare of at least 25% of their CLBs (15, grid set by IOs or hard blocks): post-route CPD win in (a) -2.15% (s = 2) and -1.59% (s = 4); the 20 with a smaller spare -0.88% and -1.51%. In both groups most designs lose (3/10 and 9/11 W/L for s = 2; 4/11 and 6/12 for s = 4 of those clearly moving).
  More spare room did not help; the second VPR re-pack (unrelated clustering) fires in about 43% of the runs and is part of the loosened arms.

## Deviations from the brief and limits

* Pre-route CPD is VPR's final "Placement estimated critical path delay" (placement-time estimate), a different run from the post-route number in (a) only through Wmin; in (b) placement differs from (a) because the delay model depends on W.
* The seed-criticality threshold T and the budget n come from one pass-1 pack per design (VPR seed 1) and are used for all three seeds; whether the stock pack is the same for seeds 2 and 3 was not tested separately.
* Wmin in (b) for the stock arm is per seed; arms share W per (design, seed). The unroutable cases above leave the design out for that arm.
* Duplication (second half of Schabas) not built, as briefed. Only s = 2, 4.
* Pack time rises; VPR's re-pack with unrelated clustering is part of the arm when the first pack does not fit (45 of 102 and 42 of 105 runs); not separated from the spare rule.

## Controller review note (2026-10-30): fit vs re-pack split

VPR re-packed with unrelated clustering in 45 of 102 s = 2 runs and 42 of 105 s = 4 runs (setting a), so the
controller split the per-design ratios (geomean over seeds, then over designs; computed from
data/analysis/q5-stats.json, `refit` field) by whether the arm's run kept the loosened pack (fit) or fell back.
Positive = better than stock.

| setting | arm | runs kept (fit) | designs | post-route CPD | W/L | WL | CLBs used |
|---|---|---|---|---|---|---|---|
| a | s = 2 | fit | 19 | -0.71% | 6/11 | -2.59% | -13.75% |
| a | s = 2 | re-pack | 15 | -1.49% | 6/9 | -1.18% | -3.05% |
| a | s = 4 | fit | 21 | -2.23% | 5/16 | -3.29% | -20.23% |
| a | s = 4 | re-pack | 14 | -0.45% | 5/7 | -2.62% | -4.10% |
| b | s = 2 | fit | 19 | -1.53% | 5/13 | -2.10% | -13.75% |
| b | s = 2 | re-pack | 15 | -1.35% | 5/8 | -2.32% | -3.05% |
| b | s = 4 | fit | 21 | -2.81% | 4/16 | -2.75% | -20.23% |
| b | s = 4 | re-pack | 14 | -0.92% | 6/6 | -1.97% | -4.10% |

The fallback does not explain the loss: runs that kept the loosened clustering lose as much or more speed, and the
re-packed runs have mostly undone the loosening (CLBs within 3 to 4% of stock). The verdicts stand. Exploratory split
after the result, not in the plan.
