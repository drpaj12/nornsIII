# Q-N6: does logic duplication after placement buy speed on modern VPR? (Schabas part 2) (plan written 2026-10-30, before the runs)

This file is committed and pushed before any VPR run. It is not edited after the runs; results are appended below under their own dated heading.

## Plain-English summary

Peter (2026-10-30), verbatim: "Try the duplication after placement. That might be the end of norns". Confirmed by Peter (2026-10-30), verbatim: "Okay let's run duplication testing with the goal of speed improvement". So speed (post-route critical-path delay) is the primary measure and the hypothesis target; wirelength and area (CLBs used) are costs. Q-N5 (nornsIII #39) tested the first half of Schabas and Brown
(FPGA 2003, `schabas2003duplication`): empty BLEs in critical clusters on a fixed square grid. It did not replicate (CPD 1.4 to 1.5 percent slower). In the paper the
second half, duplicating logic on the critical path after placement, gave the rest: +7.7 percent in total (1.4 from plain BLE moves, 6.3 from copies). Question: on VPR
3c9a4d23b2 with the same 35 designs and the same fixed square grids, does copying a critical-path LUT into a nearby cluster with room, so that the copy drives only the
critical connection, make the routed design faster? Purpose: Norns speed. Measures in Peter's order: speed (post-route CPD, pre-route CPD, near-critical endpoints),
wirelength, area (grid fixed; CLBs used reported).

## Hypothesis

H-dup: starting from the stock placement of each design (fixed grid), duplicating critical-path LUTs after placement lowers post-route CPD against stock with WL not worse by
more than 2 percent. H-dup-spare: the same starting from the Q-N5 s = 2 packing (Schabas's full method: spare BLEs in critical clusters, then duplication into them).

## Method choice: (ii) netlist-level loop on VPR's flat-placement reconstruction

Read in VPR 3c9a4d23b2 (`vpr/src/base/read_options.cpp`, `doc/src/vpr/command_line_usage.rst`): `--write_flat_place` writes one line per atom (x, y, layer, sub_tile) after the
run; `--analytical_place --read_flat_place F --ap_full_legalizer flat-recon` rebuilds the clusters from F (atoms with the same x, y, sub_tile form a cluster, legalized by the
cluster legalizer, so cluster legality of a copy is checked by VPR itself) and keeps every cluster at its location (flat-recon "reconstructs a clustered placement as close to the
incoming flat placement as possible"; the AP flow's detailed annealer is switched off with `--ap_detailed_placer none`). Then `--route --analysis`.
Option (i) (an in-VPR stage that edits the clustered and atom netlists) would need new intra-cluster routing and incremental timing code; (ii) needs no C++, keeps every original
atom at its stock location and the copy at its target, and VPR's legalizer rejects an illegal cluster. Chosen for stability and cost. It is a Norns script
(`scripts/q6_dup.py`, `q6_run.py`, `q6_stats.py`); no overlay change.

Per round r (R rounds, at most k copies per round):
1. Read the previous run's post-route 1000-path setup report (`report_timing.setup.rpt`), its `final.flat_place`, and `.net` (cluster occupancy: occupied `fle` count).
2. Candidates: for each path within 2 percent of the worst path, each connection LUT s -> LUT q (both `.names` atoms, q not a primary output, s not feeding an FF input
   only) where s and q are in different clusters. The copy s' (same inputs, same truth table) drives only q. If s has fanout one the candidate is a plain MOVE of s (no netlist
   change). Source-side duplication only (the sink side of Schabas is not built; stated deviation). BLE = a LUT; LUT+FF pairs are not duplicated (FF would need to go with it).
3. Targets: clusters with at least one empty `fle` (10 - occupied) within Manhattan distance 3 of the sink cluster or of the source cluster. Estimated gain: net delay is modelled
   as a + b x Manhattan distance, with a, b least-squares fitted per run from the inter-cluster connections in the report; gain = delay(p->s) + delay(s->q) - delay(p->t) - delay(t->q)
   where p is the predecessor on the path. Only gain > 0 qualifies (Schabas: "must result in a shortening of the critical path"). Cost (stand-in for Eq. 6): the negative estimated
   gain (timing term) with the bounding-box growth of the nets touched as tie-break; lowest cost first. This is a simplified Eq. 6 (no annealer cost state offline); stated deviation.
4. Do the best k non-conflicting candidates (distinct s, distinct target capacity), write the new BLIF and flat placement, check equivalence, run flat-recon + route + analysis.
   If VPR refuses the legalization the candidate list for that round is retried without the refused copy (counted).
5. Stop when no candidate has gain > 0, when R rounds are done, or the congestion guard fires. Guard: Schabas Eq. 8 needs the criticality of all connections, which VPR does not
   export; the guard is the mean criticality of the connections in the kept 1000-path report is not usable (always high), so the guard used is: stop and KEEP THE PREVIOUS ROUND
   when the post-route CPD of the new round is worse than the best so far (the purpose of the guard: do not let congestion make the routed result worse). Eq. 8 over the kept report is
   logged. Stated deviation.
   k = 4 copies per round, R = 4 rounds (fixed before the runs, no tuning). Final result = best round (the round-0 result if no round helped; round 0 = flat-recon of the stock).

## Correctness

Each duplicated BLIF is checked equivalent to the original with ABC `cec` (`yosys-abc` from the yosys build in the workspace, `read_blif A; cec B`), before it is placed. A failed
check stops that design and is reported. Pure MOVEs leave the BLIF unchanged (byte-identical, noted).

## Gate

Zero duplications (flat-recon of the stock `final.flat_place` with the unchanged BLIF) vs the stock run of the same design and seed: shown on all designs x seeds 1-3 as post-route CPD
ratio and WL ratio, and whether the clustering is the same (CLBs, grid). If flat-recon is not bit-identical to stock, the paired baseline for all dup ratios is the round-0 flat-recon
result ("stock-recon"), and the ratio to the original stock is also reported. If the gate fails (grid differs, unroutable, large drift) stop and report.

## Arms, device, runs

Device: fixed square grid per design as Q-N5 (`work/q5-out/arch/<design>.xml`, `--device spare`). Arms: stock (reference), dup (start: Q-N5 stock run), dup+spare (start: Q-N5 s = 2 run;
its packing has the empty BLEs). 35 E10 designs, VPR seeds 1-3, smallest first. Routing: (a) E10 flow (min-width search, own Wmin), (b) fixed W = 2 x ceil(1.2 x stock Wmin / 2) as Q-N5.
The Q-N5 runs under `work/q5-out/vpr` are the starting points; the dup arms use the same seeds (the router seed equals the run seed).

Measures per run: post-route CPD, pre-route CPD, n_endpoints_090/095/099, WL, CLBs, grid, Wmin, copies, plain moves, rounds, stop reason, times.

## Statistics and verdict rule (as q-n5)

CAD style first, per metric in the order speed (post-route CPD, pre-route CPD, endpoints), WL, area (CLBs): geomean percent win (100 x (1 - ratio)) and wins/losses/ties (tie
within 0.5 percent), VTR (15) vs MCNC (20; all 20 are in Schabas Table 1; his duplication stage gives +7.7 percent), per setting. Then the strict verdict: ratios arm/stock per
seed, geomean over 3 seeds, geomean over designs, 90 percent percentile bootstrap over designs (10000, seed 20261030), two-sided p, Holm over arms x metrics inside a setting,
2 percent band. USEFUL: CPD upper bound < 1, Holm p < 0.05, geomean < 1 in both suites, WL <= 1.02. POSSIBLY GOOD: upper bound < 1 and WL <= 1.02 but Holm p >= 0.05 or one suite >= 1.
DISMISSED: geomean points the wrong way with the interval wholly above 1 or wholly inside [0.98, 1.02]. INCONCLUSIVE: anything else; a positive geomean whose interval touches 1 is
INCONCLUSIVE, not DISMISSED. Split by any fallback or failure mode that changes the algorithm.

## Mechanism

Pre-route vs post-route CPD change (how much the router keeps), copies landing on near-critical paths, the stop reasons (no candidate, rounds, guard), refused legalizations.

Out of scope: sink-side duplication, FF-carrying BLEs, tuning of k, R, distance 3.

## Resume / stop rule

Stop at weekly meter >= 100 or C: below 15G; commit, push, and note the next step here (below) first.

---

# Results (2026-10-30 / 31)

Plan commits 172007f (written before the runs) and 4d225bc (Peter's confirmation). Tool: VPR 3c9a4d23b2 with the Norns overlay (unchanged), private tree `work/norns-vtr-dup`; code
`scripts/q6_dup.py` (loop), `q6_run.py` (driver), `q6_stats.py`; `tests/test_q6.py`. Data: `data/analysis/q6-stats.json` (ratios, intervals, gate, mechanism). Run outputs `work/q6-out`.

## Plain-English summary

Duplicating critical-path LUTs after placement did not make the designs faster on this flow. The first numbers look good (post-route delay 1.9 to 2.8 percent better than stock when
the best of up to five rounds is kept), but that is the router's run-to-run noise being selected: when the same chosen netlist and placement are routed again at the fixed width the gain
disappears and turns into a 0.4 to 0.5 percent loss against stock (95 percent of the interval inside the 2 percent band). Verdict: DISMISSED for both arms, on the unbiased
(fixed-width re-route) measurement. Schabas's +7.7 percent (duplication stage) is not reproduced.

## What was built (method as built)

* Route (ii) of the plan: netlist-level loop on `--analytical_place --read_flat_place F --ap_full_legalizer flat-recon --ap_detailed_placer none --route --analysis --device spare`
  (`flat-recon` rebuilds the clusters from the flat placement; atoms at one (x, y, sub-tile) form a cluster, legalized by VPR's cluster legalizer). Round 0 = the unchanged BLIF and the start
  run's `final.flat_place`; round r copies (or moves) up to k = 4 LUTs chosen from the previous round's 1000-path report and re-runs. R = 4. The start placement of the dup arm is the Q-N5 stock run
  (same seed), of the spare arm the Q-N5 s = 2 run. Candidate model, cost, source-side-only copies as planned. Targets: any clb tile of the fixed grid with an empty `fle`, existing clusters
  (from `.net`/`.place`) or empty tiles (from the fixed layout), at any distance (see deviations).
* Equivalence: ABC `cec` (`yosys-abc`) of every duplicated BLIF against the original, before placement: 219 of 219 netlists with a copy equivalent, 0 failures; 36 rounds were plain moves only
  (BLIF unchanged, noted).
* Setting a: the loop runs in the E10 min-width flow; the best round (lowest post-route CPD, ties earlier) is kept. Setting b: the paired baseline (round 0) and the best round are
  each re-routed fresh at W = 2 x ceil(1.2 x Wmin(Q-N5 stock arm, same design and seed) / 2).

## Gate

Zero duplications does NOT reproduce stock bit for bit: the flat-recon rebuild assigns atoms to the pb tree differently, so the clusters (CLBs equal on 48 of 105 dup runs) and the routing differ
slightly. Round-0 / original start run, dup arm (105 runs): post-route CPD geomean 1.0045 (per-run range 0.70 to 1.24, i.e. router noise), WL 0.9964; grid identical on 105 of 105.
Spare arm: CPD 0.9946, WL 1.0014 (99 runs; 6 spare round-0 runs failed to legalize and are excluded). A re-implementation step is therefore unavoidable, and every dup ratio is
reported against BOTH the paired baseline (round 0, same flow) and the original Q-N5 stock run.

## CAD view (geomean percent win, W/L/T over designs, tie within 0.5 percent; 35 designs, 15 VTR + 20 MCNC; 90 percent bootstrap)

Against the original stock run (the claim of the hypothesis), setting b (fixed W, fresh route of the chosen result; the unbiased one):

| arm | post-route CPD | VTR / MCNC | endpoints >=0.90 / 0.95 / 0.99 | WL | CLBs used |
|---|---|---|---|---|---|
| dup | -0.50% [-1.14, +0.10] W/L/T 11/20/4 | -0.39% 5/8/2 / -0.59% 6/12/2 | -7.7 / -4.0 / +3.1 | -0.13% 10/17/8 | -1.13% 0/20/15 |
| dup + spare | -0.44% [-1.49, +0.65] W/L/T 12/20/2 | -1.05% 3/11/1 / +0.04% 9/9/1 | -1.3 / -10.2 / -31.0 | -2.48% 5/26/3 | -10.30% 4/27/3 |

Setting a (E10 flow, best round chosen on the measured result; biased towards a win): dup +1.92% [+0.43, +3.30] 23/7/5 (VTR +0.55%, MCNC +2.94%), WL +0.71%, CLBs -1.13%, Wmin -1.03%;
dup + spare +2.83% [+1.56, +4.09] 24/9/1 (VTR +0.80%, MCNC +4.40%), WL -1.84%, CLBs -10.30%.
Against the paired baseline (round 0): a: dup +2.36% [+1.55, +3.21] 19/0/16, spare +3.36% [+2.44, +4.29] 19/0/15; b: dup +0.05% [-0.33, +0.42] 7/5/23, spare +1.06% [+0.54, +1.61] 13/2/19.
Wirelength and area are costs: WL and CLBs move by about one percent or less for dup, and the spare arm's WL and CLB cost is Q-N5's (the packing), not duplication's.
Pre-route CPD (placement estimate) is NOT reported: the AP flat-recon flow prints no placement estimate (deviation).

## Strict verdict (rule of the plan, Holm over arms x metrics inside a setting)

* b vs stock: dup DISMISSED (geomean the wrong way, interval inside the 2 percent band); dup + spare DISMISSED.
* a vs stock: the rule returns POSSIBLY GOOD (dup) and USEFUL (spare). These two values are NOT accepted: the best round is selected on the same noisy post-route number it is then
  scored on (winner's curse; round 0 is one sample, the best round is the minimum of up to five). Evidence: dup a vs paired baseline +2.36%, the same netlist re-routed at fixed W +0.05%
  (INCONCLUSIVE by the rule, centred on zero). Registered as INCONCLUSIVE with this explanation.
* Paired view b: dup + spare vs its own baseline +1.06% (rule: USEFUL), but that baseline is the Q-N5 s = 2 packing, which is itself 1.4% slower than stock; duplication recovers about that
  loss and no more (vs stock -0.44%).

## Mechanism

* Copies and moves (setting a runs, 105 per arm): dup 180 copies + 115 plain moves, 77 runs with at least one candidate round, 36 runs where a later round beat round 0; stops: no candidate with
  estimated gain 35, guard (round not better than best) 68, VPR refused 1, rounds done 1. Spare 254 copies + 139 moves, 84 runs with a round, 35 improved; guard 78, no candidate 17, round-0
  failure 6, refused 4. So most runs stop because the first round does not improve the routed delay.
* How much the router keeps: the model-estimated gain per copy (0.02 to 0.3 ns) is below the per-run noise of the routed delay (round-0 / original ratios 0.70 to 1.24 per run), and the
  fresh re-route removes the apparent gain; that is what the a-to-b drop of 2.3 points shows.
* Near-critical endpoints rise rather than fall with duplication in setting a (more connections) and are flat at b.

## Deviations from the plan (all before looking at verdicts)

1. Target distance limit 3 was dropped (a probe on alu4 found no candidate with it); any clb tile with room qualifies, as in Schabas.
2. Congestion guard: replaced by "stop and keep the best when a round is not better" (Eq. 8 needs all connection criticalities, not exported).
3. Selection loop runs once per design, seed and arm under setting a; setting b re-routes the chosen result (and the baseline) at the fixed W, it does not repeat the loop.
4. Pre-route CPD not available in the flat-recon flow (not reported). Cost is the estimated timing gain with the distance tie-break (no annealer Eq. 6 offline).
5. The gate is approximate (above); the paired baseline is round 0.
6. Source-side copies only; LUT+FF BLEs not copied; 1000-path reports hold few paths on small designs (8 on alu4), limiting candidates.
7. The a-setting rule verdicts are overridden to INCONCLUSIVE in the register for the selection-bias reason above.

## Next step (if this line is continued)

Select by the placement-time model only (no routed number) or on one seed and score on the other two; add sink-side copies.
