# Q-N6: does logic duplication after placement buy speed on modern VPR? (Schabas part 2) (plan written 2026-10-30, before the runs)

This file is committed and pushed before any VPR run. It is not edited after the runs; results are appended below under their own dated heading.

## Plain-English summary

Peter (2026-10-30), verbatim: "Try the duplication after placement. That might be the end of norns". Q-N5 (nornsIII #39) tested the first half of Schabas and Brown
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
