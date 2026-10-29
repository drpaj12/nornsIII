# The critical heap: which constructs end up near-critical, and how the heap moves (data only)

Purpose: speed = critical + near-critical paths (hub purpose; Norns and Mimir speed RQs; measure: speed). Peter 2026-10-29: criticality is the main
focus of the packer, an HDL structure is a suggestion of what to pack together (probably at bit-path level); is there data on which HDL constructs
lead into "the critical heap" (the paths suspected critical that the greedy packer takes first), and does the heap persist, pushed down, to the end?
Data-first rule (Peter 10-26): this document measures and shows; it gives no verdict. Candidate hypotheses are listed at the end, untested.

## Plain-English summary

* The heap is small and concentrated. On the 15 Verilog designs of the keep sweep (45 runs: 3 seeds each; post-route), the 1000-path report reaches
  below crit 0.90 in every run, so the crit >= 0.90 heap is complete (no run is truncated at 0.90, 0.95 or 0.99). The heap holds a median
  4.6% of the atoms of a design and lives in a median of 14 register-bit cones
  (cone = fan-in of one register bit or output; 11% of the combinational atoms).
* Which constructs: with the operator-level labels, carry-chain adders are enriched only at the top of the heap (crit >= 0.99: median enrichment
  2.18 [1.17, 2.45], n=11 designs) and sit at about the baseline at crit >= 0.90 (1.05 [0.51, 1.37]).
  Multipliers are strongly enriched but exist in only 2 designs. Equality comparators are absent from the heap in
  most designs (median 0.00), muxes and relational operators are below baseline.
* Bit level: neither word bits nor carry-chain positions show an MSB effect. Heap rate by position quartile is flat (adder chains: 0.034, 0.044, 0.031, 0.034).
* Dynamics: the packer does take the pack-time heap earlier (Spearman between cluster number and pack-time crit: -0.35 [-0.43, -0.11]), but the heap does not stay put:
  only 0.23 [0.11, 0.45] of the pack-time heap (crit >= 0.90) is in the post-route heap, while 0.76 [0.31, 0.94] of the post-route heap was in the
  pack-time heap (0.24 [0.06, 0.69] are new arrivals with pack-time crit < 0.90).
* Floor: with wire delay removed (cell delays only) the slowest reported path would run at 0.40 [0.37, 0.44] of the real CPD; wire delay is
  0.63 [0.56, 0.65] of the delay of the near-critical paths. A heap always exists (crit is relative to the worst path) and the wire share is what the placement decides.
* HDL hints (Q6): construct kind and expression depth carry little signal for the post-route heap (leave-one-design-out AUC 0.49 [0.38, 0.60]),
  adding netlist depth and register/adder type gives 0.57 [0.44, 0.65];
  for the pack-time heap the netlist depth alone reaches 0.73 [0.63, 0.79].

## Method and data

* Post-route side: `norns-keep.db` (Mimir schema 7, read only), the 45 runs with kept timing: `timing_path` (crit of each of up to 1000 paths), `timing_path_node`
  (atoms, `cell_delay_ns`, `net_delay_in_ns`, word and bit), `timing_run`. Config E10 `base` (vpr_sa, K6, norns architecture), seeds 1, 2, 3. See `docs/plan/keep-sweep-2026-10-29.md`.
* Atom criticality rc(atom) = the largest crit of a reported path containing the atom (a lower bound; an atom in no reported path has rc <= last_crit, "unseen").
  The heap at threshold t = atoms with rc >= t. Atoms in `timing_path_node` are named like the packer's atoms (all 15 designs, 100% of the matched path atoms occur in the census).
* Constructs: `lane3-structures.db` (read only), structures of the 15 designs (`norns/<d>`), their `structure_member` atoms. Three views: operator
  (`granularity = operator`, HDL operators), block (`granularity = block`, always blocks and assigns) and detector (netlist detectors). Atom names are the same hash names in the keep
  netlists and the structure runs (not every keep atom is a member: `none` collects atoms in no structure of the view). An atom takes the kind of the smallest
  structure containing it. The structure runs and the keep runs are separate Odin III runs of the same base netlist; the overlap was not 100% (for example stereovision0 has no detector structures), so the `none` row mixes "no construct" and "not covered".
* Baseline: all logic atoms of the design (the census atoms, pads excluded: LUTs, flip-flops, adder bits, hard blocks), not the 1000 reported paths. Enrichment of kind k =
  (share of heap atoms in k) / (share of all atoms in k). The delay-weighted variant weights each heap atom by `cell_delay_ns + net_delay_in_ns` of its node on the most critical path through it, against the same atom-count baseline.
* Summary across designs: per design the mean over its 3 seeds, then the median over designs with a 90% percentile bootstrap (2000 resamples of designs). A design counts for a kind with >= 5 atoms of
  the kind and >= 10 heap atoms. Seed spread (mean standard deviation of the ratio over the 3 seeds, median over kinds) is 0.27 at the operator view, 0.90.
* Pack side: new beta-0 census runs (`scripts/heap_census.py`): the Norns VPR binary, E10 `base` flags except `--pack` only (packing does not depend on later stages), `--norns_pack_census`, seeds 1 to 3, all 15 designs, under the Norns VPR lock, RLIMIT_AS 14 GB.
  Gate: the `.net` of every census run is byte-identical to the `.net` of the sweep run (45 of 45, rc 0). The census runs live in `work/heap-out` (outside the worktree). Pack-time criticality pc(atom) = the largest `P` value over
  the atom's input pins at the moment its molecule was added (VPR's pre-cluster timing, which VPR updates as clusters close, so pc is "the heap as the packer saw it then"). Pack order = cluster number of the final (closed) cluster; the pack-time heap = pc >= 0.90.
  Existing round-4 censuses (`work/norns-exp/data/<d>/r4census.json`, `scripts/r4census.py`) were not reused: they come from other flags (round-4 analytic arms) and the new runs cover all 15 designs on exactly the sweep flags.
* New store: none needed (`work/mimir-data/heap.db` was not created); derived tables are `data/analysis/heap-q*.json`, rebuilt by `scripts/heap_analyze.py` from the stores read-only, the census files and the BLIFs.
* Scripts: `heap_census.py`, `heap_data.py` (loader), `heap_lib.py` (join, ratio, bootstrap, Spearman, census parser, netlist levels and cones), `heap_analyze.py`, `heap_figs.py`, `heap_doc.py` (this file). Tests: `python3 tests/test_heap.py` (16 tests: innermost-kind join, ratio, bootstrap, Spearman, census parser, levels, cones, carry chains).

## Q1. Construct enrichment

Median (90% bootstrap) over designs of the per-design enrichment; n = designs that count for the kind. A ratio of 1 = the kind is in the heap in proportion to its atoms.

### Operator view

| kind | atoms, crit >= 0.90 | crit >= 0.95 | crit >= 0.99 | delay-weighted, 0.90 | designs with 0 heap atoms (0.90) |
|---|---|---|---|---|---|
| multiplier | 4.60 [0.96, 8.23] (n=2) | 6.00 [1.33, 10.67] (n=2) | 0.75 [0.00, 1.50] (n=2) | 14.81 [6.77, 22.86] | 0 |
| adder | 1.05 [0.51, 1.37] (n=13) | 1.18 [0.24, 1.82] (n=13) | 2.18 [1.17, 2.45] (n=11) | 0.53 [0.21, 1.01] | 3 |
| none | 0.94 [0.86, 1.13] (n=13) | 0.92 [0.75, 1.13] (n=13) | 0.51 [0.45, 0.71] (n=11) | 0.45 [0.25, 1.10] | 0 |
| relational | 0.37 [0.00, 7.78] (n=6) | 0.37 [0.00, 7.73] (n=6) | 0.16 [0.00, 8.45] (n=6) | 0.59 [0.00, 12.55] | 3 |
| mux | 0.36 [0.00, 1.48] (n=6) | 0.32 [0.00, 1.48] (n=6) | 0.24 [0.10, 0.96] (n=4) | 0.49 [0.00, 1.45] | 2 |
| equality | 0.00 [0.00, 0.51] (n=10) | 0.00 [0.00, 0.56] (n=10) | 0.00 [0.00, 0.68] (n=8) | 0.00 [0.00, 0.89] | 6 |

### Block view

| kind | atoms, crit >= 0.90 | crit >= 0.95 | crit >= 0.99 | delay-weighted, 0.90 | designs with 0 heap atoms (0.90) |
|---|---|---|---|---|---|
| mux | 1.13 [0.33, 2.49] (n=8) | 1.16 [0.41, 2.44] (n=8) | 1.67 [0.00, 15.80] (n=6) | 1.58 [0.18, 2.64] | 1 |
| register_word | 1.00 [0.53, 1.07] (n=12) | 0.95 [0.24, 1.02] (n=12) | 0.86 [0.44, 1.03] (n=10) | 0.94 [0.01, 1.12] | 2 |
| none | 0.64 [0.00, 2.07] (n=5) | 0.52 [0.00, 1.82] (n=5) | 0.00 [0.00, 2.22] (n=3) | 0.99 [0.00, 2.73] | 2 |
| counter | 0.50 [0.00, 9.15] (n=4) | 0.50 [0.00, 5.76] (n=4) | 1.15 [0.00, 2.34] (n=3) | 0.00 [0.00, 0.95] | 2 |
| adder | 0.29 [0.00, 3.35] (n=6) | 0.00 [0.00, 4.59] (n=6) | 0.00 [0.00, 10.45] (n=5) | 0.17 [0.00, 3.17] | 3 |
| logic | 0.03 [0.00, 0.81] (n=6) | 0.00 [0.00, 1.47] (n=6) | 0.00 [0.00, 2.46] (n=5) | 0.03 [0.00, 0.95] | 3 |
| equality | 0.00 [0.00, 0.27] (n=3) | 0.00 [0.00, 0.00] (n=3) | 0.00 [0.00, 0.00] (n=3) | 0.00 [0.00, 0.61] | 2 |
| fsm | 0.00 [0.00, 1.66] (n=7) | 0.00 [0.00, 1.58] (n=7) | 0.00 [0.00, 0.98] (n=7) | 0.00 [0.00, 0.78] | 4 |

### Detector view (netlist detectors; stereovision0 to 2 have none)

| kind | atoms, crit >= 0.90 | crit >= 0.95 | crit >= 0.99 | delay-weighted, 0.90 | designs with 0 heap atoms (0.90) |
|---|---|---|---|---|---|
| mux | 20.49 [0.00, 40.98] (n=2) | 21.01 [0.00, 42.01] (n=2) | 0.00 [0.00, 0.00] (n=2) | 16.95 [0.00, 33.91] | 1 |
| equality | 12.61 [12.61, 12.61] (n=1) | 12.23 [12.23, 12.23] (n=1) | - | 13.20 [13.20, 13.20] | 0 |
| none | 1.01 [1.00, 1.42] (n=13) | 1.00 [1.00, 1.45] (n=13) | 1.05 [1.00, 1.40] (n=11) | 1.06 [1.00, 1.51] | 0 |
| register_word | 0.51 [0.05, 0.71] (n=9) | 0.44 [0.11, 0.61] (n=9) | 0.42 [0.06, 0.72] (n=7) | 0.40 [0.01, 0.45] | 2 |

Figure: `docs/figures/critical-heap/q1-enrichment.png`.

Controller first cut (pooled delay, baseline = reported paths) said adder 2.16, multiplier 1.66, mux 0.29, relational 0.40, equality 0.15. Reproduced properly the picture changes in two ways: with the
whole-design baseline and designs as replicates the adder ratio at 0.90 is about 1 (it reaches 2 only at 0.99), and the multiplier value rests on 2 designs.
The low mux, relational and equality values do reproduce.

### By HDL line (for Wyrd)
Top lines by heap atoms (crit >= 0.90, seed 1; enrichment = line's heap share / line's atom share). All designs are in `data/analysis/heap-q1-lines.json` (top 8 each).

| design | line | heap atoms | atoms on the line | enrichment |
|---|---|---|---|---|
| sha | sha.v:127 | 42 | 1739 | 0.44 |
| sha | sha.v:138 | 31 | 132 | 4.30 |
| sha | sha.v:148 | 30 | 359 | 1.53 |
| sha | sha.v:2089 | 30 | 33 | 16.66 |
| diffeq1 | diffeq1.v:42 | 60 | 134 | 1.89 |
| diffeq1 | diffeq1.v:40 | 32 | 230 | 0.59 |
| diffeq1 | diffeq1.v:23 | 32 | 97 | 1.39 |
| diffeq1 | diffeq1.v:19 | 1 | 1 | 4.22 |
| or1200 | or1200.v:3643 | 77 | 139 | 7.64 |
| or1200 | or1200.v:3693 | 39 | 71 | 7.58 |
| or1200 | or1200.v:3365 | 38 | 349 | 1.50 |
| or1200 | or1200.v:3362 | 31 | 66 | 6.48 |
| raygentop | raygentop.v:333 | 38 | 144 | 8.17 |
| raygentop | raygentop.v:2726 | 17 | 38 | 13.85 |
| raygentop | raygentop.v:2723 | 8 | 59 | 4.20 |
| raygentop | raygentop.v:2711 | 5 | 32 | 4.84 |
| stereovision3 | stereovision3.v:144 | 9 | 52 | 1.79 |
| stereovision3 | stereovision3.v:102 | 8 | 10 | 8.26 |
| stereovision3 | stereovision3.v:83 | 7 | 98 | 0.74 |
| stereovision3 | stereovision3.v:1029 | 3 | 35 | 0.88 |

## Q2. Bit level

Words of >= 8 bits. Word kind = the most common operator-view kind (else block view) of the word's atoms. The Odin III attribution gives word and bit only for atoms in a reported path and only for flip-flops, hard blocks and some
LUTs; adder bits have none, so adders use the position along the carry chain (netlist) instead. Heap rate = share of the bits (or chain positions) with rc >= 0.90, by quartile of the relative position (0 = LSB / chain head).

| word kind | words | bits seen | mean Spearman(bit, crit) | Q0 (LSB) | Q1 | Q2 | Q3 (MSB) |
|---|---|---|---|---|---|---|---|
| adder carry chain | 0 | 12858 | - | 0.034 | 0.044 | 0.031 | 0.034 |
| fsm | 25 | 551 | -0.064 | 0.113 | 0.085 | 0.085 | 0.088 |
| logic | 3 | 36 | -0.068 | 0.000 | 0.000 | 0.000 | 0.000 |
| mux | 27 | 779 | 0.026 | 0.087 | 0.098 | 0.113 | 0.089 |
| none | 45 | 3320 | -0.001 | 0.034 | 0.023 | 0.029 | 0.026 |
| register_word | 55 | 1442 | -0.001 | 0.075 | 0.090 | 0.085 | 0.073 |

Figure: `docs/figures/critical-heap/q2-bit-position.png`. No multiplier word appears (multiplier atoms carry no word attribution). There is no MSB-heavy pattern in these data; the adder chains (12,858 atoms in chains of >= 8 across the 45 runs) show a flat 3 to 4% heap rate over the four quartiles.

## Q3. Heap size and shape (seed 1; seeds 2 and 3 in `data/analysis/heap-q3.json`)

`paths` = paths in the 1000-path report; `paths >= t` counts reported paths; `endpoints` = `n_endpoints_090/095/099` of `timing_run`. `last crit` = crit of the last reported path (stereovision3 reports all 201 of its paths; its stored
last_crit of 1.00 is the store's value). Truncation flags (`trunc_090/095/099`) are 0 in all 45 runs: the report always reached below 0.90 before the 1000-path cap.

| design | CPD ns | paths | paths >= .90 | paths >= .99 | endpoints .90/.95/.99 | last crit | crit p10/p50/p90 | atoms | heap atoms .90/.95/.99 |
|---|---|---|---|---|---|---|---|---|---|
| blob_merge | 14.67 | 636 | 3 | 1 | 3 / 2 / 1 | 0.03 | 0.12 / 0.31 / 0.41 | 10074 | 81 / 79 / 35 |
| boundtop | 3.06 | 758 | 22 | 2 | 22 / 10 / 2 | 0.14 | 0.26 / 0.57 / 0.80 | 947 | 25 / 13 / 5 |
| ch_intrinsics | 2.12 | 163 | 5 | 1 | 5 / 1 / 1 | 0.10 | 0.14 / 0.43 / 0.56 | 187 | 5 / 1 / 1 |
| diffeq1 | 17.20 | 289 | 32 | 7 | 32 / 31 / 7 | 0.03 | 0.04 / 0.25 / 0.96 | 626 | 125 / 122 / 57 |
| diffeq2 | 13.55 | 192 | 31 | 7 | 31 / 30 / 7 | 0.05 | 0.06 / 0.24 / 0.97 | 433 | 100 / 96 / 48 |
| mkDelayWorker32B | 6.82 | 1000 | 1 | 1 | 1 / 1 / 1 | 0.21 | 0.22 / 0.29 / 0.44 | 1876 | 6 / 6 / 6 |
| mkPktMerge | 4.10 | 1000 | 20 | 3 | 20 / 4 / 3 | 0.45 | 0.46 / 0.49 / 0.83 | 678 | 60 / 12 / 9 |
| mkSMAdapter4B | 6.20 | 1000 | 5 | 1 | 5 / 1 / 1 | 0.21 | 0.25 / 0.50 / 0.73 | 2162 | 26 / 7 / 7 |
| or1200 | 8.75 | 1000 | 56 | 2 | 56 / 8 / 2 | 0.68 | 0.68 / 0.74 / 0.86 | 3649 | 250 / 90 / 29 |
| raygentop | 5.43 | 1000 | 42 | 4 | 42 / 13 / 4 | 0.25 | 0.28 / 0.47 / 0.85 | 2474 | 74 / 17 / 8 |
| sha | 9.86 | 929 | 29 | 4 | 29 / 19 / 4 | 0.04 | 0.25 / 0.31 / 0.37 | 2494 | 134 / 105 / 51 |
| stereovision0 | 3.83 | 1000 | 54 | 7 | 54 / 34 / 7 | 0.50 | 0.52 / 0.58 / 0.86 | 21001 | 132 / 78 / 24 |
| stereovision1 | 5.73 | 1000 | 161 | 9 | 161 / 27 / 9 | 0.83 | 0.83 / 0.85 / 0.90 | 18996 | 202 / 35 / 11 |
| stereovision2 | 13.26 | 1000 | 419 | 25 | 419 / 150 / 25 | 0.79 | 0.82 / 0.88 / 0.96 | 36524 | 2559 / 1005 / 188 |
| stereovision3 | 2.63 | 201 | 19 | 16 | 13 / 12 / 10 | 1.00 | 0.22 / 0.50 / 0.86 | 319 | 32 / 31 / 23 |

Figure: `docs/figures/critical-heap/q3-wall.png`. The wall: the number of paths within 0.01 of the worst ranges from 1 (mkDelayWorker32B, blob_merge) to 25 (stereovision2); the heap at 0.90 holds 1 to 419 reported paths.

## Q4. Heap dynamics through the flow

Per design (seed 1; medians over designs with intervals in the summary below). `pack heap` = atoms with pc >= 0.90; `route heap` = atoms with rc >= 0.90; `stay` = share of the pack heap in the route heap; `from pack` = share of the route heap that was in the pack heap;
`new` = share of the route heap with pc < 0.90; `unseen` = share of the pack heap in no reported path; `rho` = Spearman(cluster number, pc); `Q1 share` = share of the pack heap packed in the first quarter of clusters (0.25 if no order effect);
`floor` = (largest cell-delay sum of a reported path) / CPD; `wire` = net share of the near-critical path delay.

| design | atoms | pack heap | route heap | stay | from pack | new | unseen | rho | Q1 share | floor | wire |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blob_merge | 10072 | 216 | 81 | 0.36 | 0.95 | 0.05 | 0.62 | -0.65 | 0.17 | 0.48 | 0.52 |
| boundtop | 945 | 86 | 25 | 0.28 | 0.96 | 0.04 | 0.00 | -0.22 | 0.00 | 0.48 | 0.71 |
| ch_intrinsics | 185 | 13 | 5 | 0.00 | 0.00 | 1.00 | 0.38 | -0.08 | 0.69 | 0.58 | 0.36 |
| diffeq1 | 624 | 163 | 125 | 0.77 | 1.00 | 0.00 | 0.23 | -0.37 | 0.37 | 0.39 | 0.62 |
| diffeq2 | 431 | 163 | 100 | 0.61 | 1.00 | 0.00 | 0.37 | -0.38 | 0.36 | 0.38 | 0.63 |
| mkDelayWorker32B | 1874 | 377 | 6 | 0.01 | 0.83 | 0.17 | 0.99 | 0.78 | 0.00 | 0.36 | 0.64 |
| mkPktMerge | 676 | 33 | 60 | 0.00 | 0.00 | 1.00 | 0.45 | 0.13 | 0.00 | 0.36 | 0.55 |
| mkSMAdapter4B | 2160 | 62 | 26 | 0.08 | 0.19 | 0.81 | 0.40 | 0.20 | 0.65 | 0.43 | 0.58 |
| or1200 | 3647 | 529 | 250 | 0.15 | 0.32 | 0.68 | 0.36 | -0.18 | 0.63 | 0.39 | 0.60 |
| raygentop | 2472 | 142 | 74 | 0.15 | 0.30 | 0.70 | 0.20 | -0.43 | 0.80 | 0.40 | 0.68 |
| sha | 2492 | 279 | 134 | 0.47 | 0.98 | 0.02 | 0.51 | -0.57 | 0.82 | 0.43 | 0.58 |
| stereovision0 | 20999 | 673 | 132 | 0.17 | 0.85 | 0.15 | 0.19 | -0.35 | 0.04 | 0.36 | 0.64 |
| stereovision1 | 18994 | 120 | 202 | 0.00 | 0.00 | 1.00 | 1.00 | -0.11 | 0.90 | 0.29 | 0.68 |
| stereovision2 | 36522 | 3636 | 2559 | 0.53 | 0.76 | 0.24 | 0.33 | -0.53 | 0.55 | 0.43 | 0.56 |
| stereovision3 | 317 | 58 | 32 | 0.43 | 0.78 | 0.22 | 0.50 | -0.50 | 0.43 | 0.42 | 0.65 |

Summary over the 15 designs (median [90% bootstrap]; per design the mean of 3 seeds):

| measure | value |
|---|---|
| floor_ratio | 0.405 [0.371, 0.437] |
| from_pack_heap | 0.759 [0.311, 0.936] |
| logic_heap_recall_of_route | 0.889 [0.780, 0.969] |
| logic_vs_route_jaccard | 0.657 [0.131, 0.818] |
| near_median_cell_over_cpd | 0.356 [0.342, 0.415] |
| near_net_share | 0.628 [0.562, 0.650] |
| new_arrival_pc_lt_050 | 0.050 [0.012, 0.066] |
| new_arrival_pc_lt_090 | 0.241 [0.064, 0.689] |
| pack_heap_in_first_quartile | 0.431 [0.167, 0.645] |
| pack_heap_unseen | 0.385 [0.323, 0.424] |
| rho_crank_pc | -0.353 [-0.425, -0.108] |
| rho_pc_rc_seen | 0.663 [0.599, 0.730] |
| rho_seq_pc | -0.353 [-0.426, -0.108] |
| stay | 0.226 [0.109, 0.448] |

Transition of atoms from pack-time criticality (rows) to post-route criticality (columns), row-normalised, all 45 runs pooled (pack-time rows below 0.50 pooled):

| pack-time crit | atoms | >=0.99 | 0.90-0.99 | 0.50-0.90 | <0.50 | unseen |
|---|---|---|---|---|---|---|
| <0.50 | 218679 | 0.000 | 0.001 | 0.031 | 0.081 | 0.887 |
| 0.50-0.90 | 68901 | 0.004 | 0.050 | 0.287 | 0.037 | 0.622 |
| 0.90-0.99 | 6636 | 0.019 | 0.179 | 0.518 | 0.000 | 0.284 |
| >=0.99 | 13014 | 0.067 | 0.425 | 0.079 | 0.001 | 0.428 |

* Pack order against criticality: the correlation is negative in 12 of 15 designs (seed 1): the greedy seed selection and the timing gain take higher-pc atoms in earlier clusters, moderately (-0.35 [-0.43, -0.11]). Exceptions are the designs
  dominated by hard blocks (mkDelayWorker32B, rho +0.78).
* The first-quarter share of the pack heap is 0.43 [0.17, 0.65] (0.25 = no order effect).
* The floor measurement: the heap exists after routing in every run (crit is relative), and its member paths are 0.63 [0.56, 0.65] wire by delay. The cell-only logic-depth ordering of the reported paths (paths with cell sum >= 0.9 of the
  largest) shares 0.66 [0.13, 0.82] Jaccard with the routed heap and covers 0.89 [0.78, 0.97] of the routed heap's paths. Only the 1000 reported paths enter, so a deeper but unreported path could raise the largest cell sum.

Figure: `docs/figures/critical-heap/q4-dynamics.png`.

## Q5. What is not in the heap

Per view and kind (crit >= 0.90): designs where the kind counts, designs where it has zero heap atoms, median enrichment.

| view | kind | designs | designs with 0 heap atoms | median enrichment |
|---|---|---|---|---|
| op | adder | 13 | 3 | 1.05 |
| op | equality | 10 | 6 | 0.00 |
| op | multiplier | 2 | 0 | 4.60 |
| op | mux | 6 | 2 | 0.36 |
| op | none | 13 | 0 | 0.94 |
| op | relational | 6 | 3 | 0.37 |
| blk | adder | 6 | 3 | 0.29 |
| blk | counter | 4 | 2 | 0.50 |
| blk | equality | 3 | 2 | 0.00 |
| blk | fsm | 7 | 4 | 0.00 |
| blk | logic | 6 | 3 | 0.03 |
| blk | mux | 8 | 1 | 1.13 |
| blk | none | 5 | 2 | 0.64 |
| blk | register_word | 12 | 2 | 1.00 |
| det | equality | 1 | 0 | 12.61 |
| det | mux | 2 | 1 | 20.49 |
| det | none | 13 | 0 | 1.01 |
| det | register_word | 9 | 2 | 0.51 |

Share of atoms (all 45 runs pooled, operator view) that are in no reported path at all, with the atom count:

| kind | share unseen | atoms |
|---|---|---|
| adder | 0.82 | 78906 |
| equality | 0.42 | 6789 |
| multiplier | 0.86 | 1455 |
| mux | 0.31 | 11175 |
| none | 0.83 | 198339 |
| relational | 0.67 | 10656 |

Equality comparators and FSM blocks are the constructs most often absent (equality: 6 of 10 designs, fsm: 4 of 7 in the block view). No kind is absent from the heap in all designs; the kinds with structure rows but too few atoms to count (shifter, memory, unknown) cannot be judged.

## Q6. Do HDL hints known before packing predict the heap?

Atoms: all logic atoms of the 45 runs. Targets: (route) rc >= 0.90 from the keep store; (pack) pc >= 0.90 from the census. Features are computed from HDL / Odin III data and the BLIF only, never from VPR timing:
(a) construct kind (operator view, else block view, else none); (b) operator depth = number of BINARY/UNARY/TERNARY/CONCAT nodes in the structure's `construct_chain` (`structure.construct_chain` of lane3-structures, from the Odin III AST provenance),
and width proxy = log2 of the member count of the innermost structure (word width itself exists only for atoms in a reported path, see Q2); (c) mux depth = number of IF, CASE and TERNARY nodes in the same chain (case/if nesting of the source line; source: `construct_chain`, the AST provenance);
(d) combinational depth = LUT levels from the nearest register / primary input / hard block, on the BLIF (a carry chain counts once; single-input buffers are absorbed as VPR does); (e) bit index within a word: see the bit-position table
(Odin III word attribution; only for atoms in a reported path, so those rates condition on being in the report; adder bits use carry-chain position).
Model: L2-regularised logistic regression (numpy Newton), standardised features, each design weighted equally, **leave-one-design-out** (train on 14 designs, test on the held-out one, all 3 seeds); AUC per held-out design,
then median [90% bootstrap] over the 15 designs. 0.5 = no signal.

### AUC by feature set

| features | route heap AUC | pack heap AUC |
|---|---|---|
| kind | 0.47 [0.38, 0.62] | 0.70 [0.60, 0.76] |
| kind+ops | 0.49 [0.38, 0.60] | 0.63 [0.50, 0.76] |
| kind+ops+netlist | 0.57 [0.44, 0.65] | 0.67 [0.52, 0.74] |
| netlist only | 0.56 [0.52, 0.63] | 0.73 [0.63, 0.79] |

Univariate AUC of a numeric feature (no model; per design, median [90%]); route heap first, pack heap second:

| feature | route heap | pack heap |
|---|---|---|
| comb level | 0.51 [0.35, 0.65] | 0.68 [0.45, 0.79] |
| log2 structure size | 0.48 [0.43, 0.60] | 0.37 [0.25, 0.48] |
| mux depth | 0.49 [0.46, 0.55] | 0.52 [0.48, 0.59] |
| op depth | 0.48 [0.47, 0.54] | 0.67 [0.51, 0.75] |

### Heap-membership rate by mux depth (per-design rate, median over designs with >= 5 atoms at that depth)

| mux depth | route heap rate | pack heap rate | designs |
|---|---|---|---|
| 0 | 0.03 [0.02, 0.10] | 0.122 [0.031, 0.190] | 15 |
| 1 | 0.04 [0.03, 0.13] | 0.202 [0.000, 0.440] | 11 |
| 2 | 0.00 [0.00, 0.03] | 0.007 [0.000, 0.087] | 10 |
| 3 | 0.00 [0.00, 0.00] | 0.000 [0.000, 0.348] | 10 |
| 4+ | 0.00 [0.00, 0.00] | 0.000 [0.000, 0.120] | 6 |

### Heap-membership rate by bit position

| position | route heap rate | designs |
|---|---|---|
| adder chain position quartile 0 | 0.000 [0.000, 0.067] | 11 |
| adder chain position quartile 1 | 0.000 [0.000, 0.519] | 11 |
| adder chain position quartile 2 | 0.000 [0.000, 0.160] | 11 |
| adder chain position quartile 3 | 0.000 [0.000, 0.103] | 11 |
| word bit quartile 0 (atoms in a reported path) | 0.018 [0.000, 0.128] | 13 |
| word bit quartile 1 (atoms in a reported path) | 0.013 [0.000, 0.140] | 13 |
| word bit quartile 2 (atoms in a reported path) | 0.034 [0.000, 0.101] | 13 |
| word bit quartile 3 (atoms in a reported path) | 0.023 [0.000, 0.095] | 13 |

### One combinational bit-path group per register bit
Group = fan-in cone of one register bit (latch) or primary output, back to registers, PIs and hard blocks. Each combinational atom is assigned to the cone of its highest-hint endpoint; hint = combinational depth of the endpoint's driver
(ties by name). Per run, summarised as median [90%] over designs:

| measure | value |
|---|---|
| comb_share_in_heap_groups | 0.112 [0.036, 0.234] |
| groups | 574.000 [114.000, 887.000] |
| groups_holding_heap | 14.333 [4.000, 32.000] |
| heap_atoms_staying | 0.569 [0.399, 0.730] |
| paths_inside_one_group | 0.108 [0.031, 0.656] |
| size_max | 52.000 [32.000, 130.000] |
| size_mean | 2.082 [1.746, 2.667] |
| size_p50 | 1.000 [1.000, 1.000] |
| size_p90 | 3.000 [1.000, 5.000] |

Group-size distribution (median over designs): half the groups hold 1 atom, 90% hold at most 3, the largest holds 52. `paths_inside_one_group` = share of the near-critical paths (crit >= 0.90) all of whose combinational
atoms are assigned to the group of the path's own endpoint; `heap_atoms_staying` = share of heap combinational atoms for which every near-critical path through them ends in their own group. The first is low because shared logic is assigned to one
deepest endpoint, not to each cone that contains it: a bit-path group by exclusive assignment covers a near-critical path completely only for a minority of paths, the heap atoms mostly remain within one group. Figure: `docs/figures/critical-heap/q6-auc.png`.

## Not measured, and why

* The pack-time heap at the start of packing (before the first cluster): the census logs pin criticality when each molecule is added, not the initial table; `pre_pack.report_timing.setup.rpt` exists in the run directories and could be parsed (not done).
* Word width and bit index for atoms outside the reported paths: the Odin III attribution covers only atoms in the reported paths (Q2, Q6 e).
* Multiplier bits: no word attribution; two designs hold multipliers.
* Delay-weighted baseline: the baseline is atom counts (there is no per-atom delay for atoms in no path).
* Crit-versus-lines for MCNC designs: the 20 MCNC designs have no attribution (blif input, `norns-keep.db`: 0 imported), so the study covers the 15 Verilog designs only.
* Hard-block (memory, multiplier) connectivity is cut at the block boundary in the cone and level computation.

## Candidate hypotheses (not tested; for Peter to choose)

* H1 Bit-path affinity from HDL hints. Group the atoms of each register bit's fan-in cone (exclusive assignment to the deepest endpoint, as measured in Q6) and give the packer that grouping as the affinity file.
  Arms (written, not run): A0 stock (beta 0); A1 cone groups, `--norns_affinity <cones> --norns_affinity_weight beta` for beta in {1, 4, 16, 100}; A2 cones restricted to the groups the hint model ranks highest (top 5% by depth);
  A3 null: the same group-size distribution assigned at random among atoms of the same module; A4 cones plus the block-membership file of round 5 for comparison. Measures per arm: CPD, number of atoms with rc >= 0.90 and >= 0.99, wirelength; 15 designs x 3 seeds; the verdict
  rule (effect size, interval, designs improved of 15) fixed before the run.
* H2 Heap floor = logic depth. The routed heap cannot fall below the cell-delay sum of the slowest path; measured here the cell-only share of the CPD is about 0.4, so the floor would only matter for placements far better than VPR's.
* H3 Carry-chain adders enter the heap only at the very top (crit >= 0.99): packing a carry chain with its LUT consumers could matter at 0.99 but not for the broad 0.90 heap.
* H4 The pack-time heap is wide and short-lived: most of the pack heap does not remain post-route, and about a quarter of the post-route heap was not in the pack heap; packing by pre-cluster criticality is a weak proxy for the final heap.
* H5 Netlist depth beats HDL constructs as an early predictor of the pack-time heap (AUC 0.73 against 0.70 for construct kind).
