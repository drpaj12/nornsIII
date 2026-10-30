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
