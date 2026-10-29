# H-refresh: refresh pre-cluster criticality while packing (plan written before the runs, 2026-10-29)

Purpose: speed = critical + near-critical paths (Norns packing RQs). Measures: post-route CPD and the
near-critical endpoint counts; costs: WL and CLBs. Evidence: `docs/plan/heap-picking.md` P1, 81% [63%, 91%]
(n=15) of the picks made on pack-time crit >= 0.90 hold no atom of the post-route heap. In the VTR
commit 3c9a4d23b2 default flow `PreClusterTimingManager::update_timing_info` is called only from
`analytical_place/global_placement/global_placer.cpp`, so the packer works on one criticality computed
before packing, with one inter-cluster delay on every net.

## Hypothesis

H-refresh: refreshing the pre-cluster criticality while packing (after each closed cluster, or every k
clusters), with connections that became intra-cluster given an intra-cluster delay estimate and
connections cut by a closed cluster given the inter-cluster estimate, lowers post-route CPD against stock
without raising CLBs or WL by more than 2%.

## Overlay change (design, before writing the code)

* Option `--norns_refresh_crit <k>` (default 0 = off). k > 0: after every k-th cluster closes, the arcs of
  the nets touched by the clusters closed since the last refresh are set and `update_timing_info()` runs.
* Arc delays. VPR's pre-cluster model has one delay per sink pin (`timing_arc_delays_`, initial value
  `approximate_inter_cluster_delay`, constant for all pins). Inside one molecule the delay calculator already
  uses the pb_graph path delay (`calc_intra_molecule_delay`), and for molecules of one chain the estimator
  `calc_inter_molecule_chain_delay` (intra-cluster routing out to the cluster boundary plus in from the
  boundary). Reused here: a connection whose driver and sink atoms are in the same closed cluster gets
  `calc_inter_molecule_chain_delay(driver pin, sink pin)` (VPR's own estimate of intra-cluster routing
  between pins of different molecules); a connection cut by a closed cluster (driver and sink in different
  clusters, at least one closed) keeps or gets the inter-cluster estimate (the value stored at
  construction, now kept in `inter_cluster_delay_`). Connections to unpacked atoms keep the inter estimate.
  Touched nets = nets of the input and output pins of the atoms of the clusters closed since the last refresh.
* Incremental timing: edges of the changed sink pins are invalidated (`invalidate_delay`) when the update
  type is incremental, as the global placer does (it invalidates all edges; here only the changed arcs).
* Readers. The candidate selector reads `setup_pin_criticality` live (`update_timing_gain_values`, per call):
  no cache. The seed selector computes atom criticalities and the seed order once in its constructor (upstream
  TODO "update_seed_gains"): a refresh would not reach the seed picks (74% of the pack-heap seeds leave the heap
  in P1). The overlay therefore adds `refresh_seed_gains()`, which recomputes the seed gains with the same
  `get_seed_gain` and stable-sorts the not-yet-proposed part of the seed list (RAM seeds first, as in the
  constructor). Queue-time gains of molecules already in a candidate queue are not refreshed (that is stock
  behaviour, heap-picking P4). The seed refresh is part of the arm; it is not a separate arm.
* The log gets one line `Norns refresh: k=<k> refreshes=<n> time=<s> s` when packing ends; with k = 0 nothing is printed
  and no code path differs from stock.

## Gate (before the sweep)

`--norns_refresh_crit 0` gives a `.net` byte-identical (sha256) to the stock sweep `.net` of the same design and
seed (the `norns-keep-sweep-out` runs, stock binary of the shared Norns tree) on every design. 35 designs x seed 1
(all seeds of the small designs). If it fails, stop and fix.

## Arms and runs

* stock (k = 0, the new binary, no option), refresh k = 1, refresh k = 8 (cost control).
* Beta 0 (no affinity file), E10 `base` flags (`vpr_sa`, K6 Norns architecture, default ABC netlists from the
  keep sweep), `NORNS_KEEP_TIMING` on (1000-path report kept and attributed). 35 designs (15 VTR Verilog + 20 MCNC),
  VPR seeds 1, 2, 3, smallest first (LUT count). 315 runs. VPR only under the Norns VPR lock
  (`/tmp/claude-1000/norns-vpr.lock`), memory cap 14 GB. Mimir import into a new store
  `work/mimir-data/refresh.db`.
* Measures per run: CPD, `n_endpoints_090/095/099` (endpoints with criticality >= 0.90, 0.95, 0.99 in the kept
  report; for MCNC designs the endpoints of the report file), WL, CLBs, pack time, total VPR time.

## Statistics and the verdict rule (said before the runs)

* Per design and metric: ratio refresh/stock per seed (same seed), geometric mean over the 3 seeds. Pooled: geometric
  mean over designs (n = 35; also per suite: 20 MCNC, 15 Norns), 90% percentile bootstrap over designs (10000 resamples,
  seed 20261029). Ratio below 1 is better for every metric.
* p-value per test: two-sided percentile-bootstrap p of H0 geomean = 1. Holm adjustment over the family of 12 tests
  (2 arms x CPD, n_endpoints_090, 095, 099, WL, CLBs). Times are descriptive (ratio and interval, no test).
* Verdict per arm for H-refresh (the CPD claim with the cost clause):
  * USEFUL: CPD pooled upper 90% bound < 1.000, Holm p < 0.05, CPD geomean < 1 in both suites, and the point estimates of CLBs and WL
    <= 1.02.
  * POSSIBLY GOOD: CPD pooled upper 90% bound < 1.000 and CLB and WL point estimates <= 1.02, but Holm p >= 0.05 or one suite
    has CPD geomean >= 1 (narrow or fragile).
  * DISMISSED: the CPD interval lies wholly inside [0.98, 1.02] (no effect beyond 2%) or wholly above 1.000 (worse), or a
    CLB or WL point estimate > 1.02 together with a CPD point estimate that is not below 0.98 (cost without gain); a CPD gain
    with a CLB or WL point estimate > 1.02 is INCONCLUSIVE with the cost stated (the hypothesis' clause fails).
  * INCONCLUSIVE: anything else.
  The near-critical counts, WL, CLBs, times are reported with the same ratios and intervals and decide nothing alone.
* Failed runs (non-zero exit, unroutable) are counted and listed; a design with a failed run in an arm leaves that
  design out of that arm's pooled ratios (stated).

## Mechanism check (census)

The 15 Verilog designs x seeds 1-3 of every arm run with `--norns_pack_census` (log-only, `.net` unchanged, gate (b) of round 4)
in the full run, and P1 of `heap-picking.md` (`scripts/heappick_lib.py`, `heappick_run.py`) is recomputed per arm: the
share of heap picks (pack-time crit >= 0.90) that leave the post-route heap, for the arm's own pack-time criticality and
post-route report. Change of P1 against stock is the check that the mechanism moved.

---

# Results (2026-10-29)

Plan commit 6618513 (written before the runs); overlay and gate commit 59dcb64. Tool: nornsIII `exp/refresh-crit`, VPR 3c9a4d23b2 with the overlay, private tree
(`packer/build.sh`, `NORNS_VTR` outside `external/`). Code: `packer/vpr/src/{pack,timing}`, `scripts/refresh_gate.py`, `refresh_stats.py`, `refresh_p1.py`, configs `rc1` and `rc8`
in `scripts/e10_main.py`. Data: `data/analysis/refresh-gate.json`, `refresh-crit-stats.json` (per-run measures and all ratios), `refresh-crit-p1.json`.

## Gate

`--norns_refresh_crit 0`: `.net` byte-identical (sha256) to the stock keep-sweep `.net` on 35 of 35 designs x 3 seeds (105 of 105, pack only); with the option absent, 35 of 35 (seed 1).
The refresh code is inert at k = 0 (no refresh line, no changed path). Also verified: k = 1 and k = 8 `.net` differ from stock (they act), and the census run's `.net`
equals the full run's `.net` for every arm (45 of 45 per arm).

## Sweep

315 runs (35 designs x seeds 1-3 x 3 arms: stock = new binary at k = 0, k = 1, k = 8), E10 `base` flags, beta 0, kept timing on, all `rc 0` and routed, 0 failed. VPR under the Norns VPR
lock (round 9 ran under it; the lock queued my runs per run). Refreshes: k = 1: 46,218 over 105 runs (305 s in the refresh code in total); k = 8: 5,727 (39 s). A refresh happens at
every k-th closed cluster including io and hard-block clusters (diffeq1: 294 clusters = 258 io + 31 clb + 5 mult). Kept timing imported into the new store `work/mimir-data/refresh.db`
(Mimir schema 7, 315 run records, 0 refused; 135 runs with attribution, 180 report-only MCNC runs; not committed; n_endpoints_* of the store equal those of `refresh_stats.py`).
The kept-inputs store is the keep sweep's (`netlists/base/_keep-inputs`, content addressed, same inputs; the run root's `netlists` is a symlink to the keep-sweep netlists).

## Pooled ratios refresh / stock

Per design the geometric mean over the 3 seeds of the same-seed ratio; pooled the geometric mean over 35 designs; 90% percentile bootstrap over designs (10,000 resamples, seed 20261029); Holm
p over the family of 12 tests (2 arms x CPD, n_endpoints_090/095/099, WL, CLBs). Below 1 is better. n_endpoints is floored at 1 for the ratio (no design had 0).

| metric | k = 1 | Holm p | k = 8 | Holm p |
|---|---|---|---|---|
| CPD | 1.005 [0.990, 1.021] | 1.000 | 1.007 [0.997, 1.018] | 1.000 |
| n_endpoints_090 | 0.879 [0.776, 0.995] | 0.942 | 0.840 [0.736, 0.953] | 0.199 |
| n_endpoints_095 | 0.859 [0.725, 1.009] | 0.978 | 0.841 [0.705, 1.000] | 0.942 |
| n_endpoints_099 | 0.862 [0.743, 0.994] | 0.942 | 0.988 [0.878, 1.119] | 1.000 |
| WL | 1.003 [0.997, 1.009] | 1.000 | 1.004 [0.995, 1.014] | 1.000 |
| CLBs | 1.002 [0.997, 1.007] | 1.000 | 1.005 [1.000, 1.010] | 0.978 |
| pack time | 1.865 [1.620, 2.172] | n/a | 1.147 [1.104, 1.196] | n/a |
| total VPR time | 1.155 [1.119, 1.194] | n/a | 1.038 [1.019, 1.057] | n/a |

By suite (point estimates): CPD k = 1 Norns15 1.006, MCNC20 1.004; k = 8 Norns15 1.001, MCNC20 1.012. Full intervals in `refresh-crit-stats.json`.

## Verdicts (rule as written in the plan, applied unchanged)

* k = 1: **INCONCLUSIVE**. CPD 1.005 [0.990, 1.021]: no gain (upper bound above 1.000), and the interval is not wholly inside [0.98, 1.02] (its upper bound 1.0205 is just outside), so the rule does not reach DISMISSED.
  Costs are within 2% (CLBs 1.002, WL 1.003). The near-critical endpoint counts fall (0.88, 0.86, 0.86; the 90% intervals mostly exclude 1) but no test survives Holm (p >= 0.94) and CPD does not move.
* k = 8: **DISMISSED**. CPD 1.007 [0.997, 1.018], wholly inside [0.98, 1.02]: no effect beyond 2% on CPD. n_endpoints_090 0.84 (Holm p 0.20) and 095 0.84 are not significant after Holm.
* H-refresh (CPD lower without raising CLBs or WL by more than 2%): not supported at either k. Refreshing the criticality did not lower post-route CPD; the CPD interval is centred on 1.

## Mechanism check: P1 recomputed on the 15 Verilog designs (3 seeds, pack census)

Method in `refresh_p1.py` (the P1 definition of `heap-picking.md`: a heap pick = a molecule with an atom of pack-time crit >= 0.90; it leaves when no atom of it has post-route crit >= 0.90 in the arm's own
1000-path report). Median over 15 designs with 90% bootstrap (2000 resamples):

| arm | heap picks that leave the post-route heap | change against stock (paired, median of per-design difference) | share of all picks that are heap picks |
|---|---|---|---|
| stock | 81% [63%, 91%] (reproduces heap-picking.md: 81% [63%, 91%]) | n/a | 7.7% [4.0%, 15.8%] |
| k = 1 | 88% [69%, 91%] | +3.6 points [0.0, +8.0] | 15.8% [8.4%, 23.1%] |
| k = 8 | 79% [73%, 93%] | +0.5 points [-1.4, +2.9] | 15.8% [8.3%, 23.0%] |

The mechanism moved, but not the way the hypothesis needs: the refresh doubles the share of picks made on crit >= 0.90 (the criticality computed with the intra-cluster estimate rises as the packed
part of the design looks faster, so more picks are classed critical), while the share of those picks that leave the post-route heap does not fall (k = 1: up 3.6 points, interval touching 0; k = 8: no change).
So the packer sees a moving heap now, but the picks it makes from it are no better matched to the post-route heap. This is the likely reason CPD does not move.

## Not met / limits

* Verdicts are INCONCLUSIVE (k = 1) and DISMISSED (k = 8); H-refresh is not supported. No CPD gain to report.
* The seed refresh is part of both arms (the seed order is recomputed at each refresh); the effect of the candidate-side refresh alone was not separated (not in the plan's arms).
* The intra-cluster estimate is VPR's chain-molecule estimator (out to the boundary and back in), which overestimates a pure crossbar hop; a smaller estimate was not tried.
* Gains of molecules already in a candidate queue are stock (queue-time gains), so the refresh reaches candidates only when they are queued after the refresh.
* Pack time rises 1.87x at k = 1 (every closed cluster, including io clusters, runs a full incremental STA): the cost is stated, not optimised.
* Mimir store `refresh.db` is local (`work/mimir-data/`), not committed.
