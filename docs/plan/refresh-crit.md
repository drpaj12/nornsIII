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
