# Seed signal: which cluster or atom to seed next, from the round 9 pilot (offline, data only)

Plan written 2026-10-29, before any feature was computed or any label was read from the pilot runs. This section is
not edited later; results are appended below under their own dated heading.

## Plain-English summary (plan)

A greedy packer builds one cluster at a time: it picks a seed atom, grows the cluster around it, closes it, and picks the
next seed. The question (Peter, 2026-10-29): is there a number, in the properties of a cluster of the known clustering C or
of its best atom, that tells us whether stock VPR will rebuild that cluster, so that a smarter seed order could be tried?
The round 9 pilot already holds the answer key (C) and what stock VPR did (3 designs x own/foreign x 3 shuffles). We compute
cluster-level and atom-level numbers from D' and C alone, then ask which of them separates the clusters VPR rebuilds exactly
from the ones it breaks (AUC) and which track how pure the VPR clusters are (Spearman). The baseline to beat is the maximum
pack-time criticality of the cluster, because that is what VPR's own seed order uses. No VPR is run. With 3 designs this is a
pointer for the next experiment (a forced seed list in the packer overlay), not a verdict.

Purpose (hub docs/purpose.md): Norns N Q1.6, room in the packer; measure: area (CLBs), with atom choice measured by purity,
reproduction and cut against C. Source of the question: Peter 2026-10-29, "is there a number that hints at this in the
properties of that cluster"; "minimum number of clusters sure, but it's the atom choice".

## Hypothesis

H-seed-signal: some property of a cluster of C (or of its best atom), measurable from D' and C alone, predicts whether stock
VPR reproduces that cluster exactly (and its purity), better than the maximum pack-time criticality of the cluster.
Register row: MEASUREMENT (3 designs, no pooled claim). It is falsified, for this data, if no feature has an AUC interval
that lies above the AUC interval of max criticality, or if every feature that does is a construction artefact.

## Data and units

* Input: `data/r9/<design>/{own,foreign}.build.json` (committed) and, read only, `work/r9-out/<design>/{own,foreign}/` of the
  three pilot designs (ch_intrinsics, diffeq1, mkPktMerge): `struct.json` (vertices, nets of H*, cluster of each vertex),
  `sh<s>/design.blif`, `sh<s>/affinity.tsv` (atom -> cluster of C), `sh<s>/vatoms.json` (vertex -> atoms),
  `sh<s>/run-<sha>/stock.s<v>/design.net` (the stock packing). Pilot directories are read only after checking that no file in
  them changed in the last 30 minutes.
* Unit of analysis: a cluster of C in one (design, construction, shuffle) build. The graph is identical across shuffles
  (names and order differ), so a cluster's features are computed once per (design, construction) and the three shuffles give
  three labels for it. The stock `.net` is checked to be byte-identical across VPR seeds 1 to 3 for each build; if so one is
  used per build, else all three are used and the label is averaged.
* Dummy vertices are the vertices added in Step B (indices after the real cells, before the macros); constant generators
  (`gnd`, `vcc`, kind K) have no nets and are excluded from the real set. "Real" = not dummy and not constant generator.

## Labels (stock arm)

* exact: the stock packing has a cluster whose atoms are exactly the atoms of c (the `exact_clusters` rule of `r9run.py`,
  counted over all atoms including dummies).
* purity: the largest share of c's atoms that sit in one stock cluster.
* stock rank: the position (0 = first) of the stock cluster holding most of c, in the order of the clusters in the stock
  `.net`. The pilot stock runs were made without the pack census, so the census seed order is not available; the `.net` order
  is the cluster creation order of the packer and is used as the rank, and this is said wherever the rank is used.

## Features

Cluster features, each on real atoms only and on real plus dummy atoms (both reported):
pin pressure = distinct external input nets / 40; tightness = external nets / internal nets; real fill = real weight / 10;
neighbour count = clusters sharing a logic net; chain present; size of the largest connected component of the cluster's
internal graph (vertices joined by a net with two pins inside); max and mean pack-time criticality; max input count of a
member. Nets to pads, hard blocks and the clock count as external; constants are ignored.
Atom features (per real vertex, the best = maximum in the cluster): loyalty = internal nets / all nets of the vertex;
internal degree; closeness centrality in the internal graph; input count; fan-out.
Pack-time criticality: the pilot has no census, so it is a proxy computed from D' alone: unit-style static timing on the
vertex graph (a net hop = 1.338 ns, the pre-pack delay VPR used on diffeq1; a LUT 0.261 ns; a carry hop 0.1 ns; flip-flop
outputs and pads are start points, flip-flop inputs and pads are end points), criticality of a vertex = 1 - slack / longest
path, taken as the maximum over its pins, which is what VPR's timing seed gain does. It is a proxy, labelled as such; if the
census of a pilot run turns out to match the current files it is used to check the proxy.

## Statistics

* AUC of each feature for exact (Mann-Whitney, ties half) and Spearman of each feature against purity, pooled over all rows
  and per design, own and foreign also separately. Sign: AUC reported as given (above 0.5 = higher feature, more likely
  exact); the ranking uses |AUC - 0.5|.
* Intervals: 90 percent percentile bootstrap, 10000 resamples, seed 20261029. Brief asks for resampling over designs: with 3
  designs there are only 27 distinct resamples, so that interval is printed but is almost uninformative; the interval used for
  ranking is a cluster-level bootstrap (clusters resampled within design and construction, all of a cluster's shuffle rows
  kept together). Both are reported and the difference is said.
* Construction artefact check: Spearman of every feature with the number of dummies in the cluster, with cluster demand
  before padding, and with the eviction count if recorded. A feature is called an artefact if |rho| >= 0.7 with dummies, or if
  it is a function of dummies by definition (real fill = 1 - dummies / 10 exactly). AUC of real-only against with-dummy view
  is compared. Own and foreign are compared: a feature that works only on own may only be reading VPR's authorship of C.
* Recommendation rule: the 2 to 3 features with the highest lower interval bound on |AUC - 0.5| that are not artefacts, not
  collinear (|rho| < 0.8 between chosen features), and whose sign agrees on own and foreign.

## Scope limits, said now

3 designs and about 75 clusters per construction; clusters in a build are not independent (they share nets and a packer
state); shuffles of one build are not independent for features. Exact-reproduction is a stringent label (a cluster is exact
only if all 10 slots match). Criticality is a proxy. None of this tests the effect of changing the seed order; that is the
step-2 probe.

## Amendment 2026-10-29 (a): mine every Mimir metric on local regions, at cluster and LUT level (written before the analysis was run)

The controller's two brief amendments (Peter 2026-10-29) widen the work from a handful of hand-picked features to data-first
mining: "the other properties of Mimir about the circuits might correlate to the right choice"; "this is at the LUT level too". The
plan above is kept; the following is added. Still no VPR, still the 3 pilot designs.

1. Extractor `scripts/seed_features.py`, imports the Mimir code from `~/odin3-ws/mimir` (`mimir.hutton.characterise`, `levels`,
   `seq_levels`, `mimir.rent.fit`), copies none of it. The pilot BLIF is turned into a Mimir `Netlist` with one node per atom (an adder
   is two nodes, a hard block one node). A region is a sub-netlist (inside nodes keep their kind, fan-ins from outside become PIs).
   Regions for a cluster: R1 (real atoms, and with dummies), R2 fan-in cone depth 1, 2, 4, R3 fan-out cone depth 1, 2, 4 (through
   combinational nodes, stopping at flip-flops, hard blocks and pads), R4 ball of k = 1, 2 hops (undirected, not through nets of more
   than 32 sinks). Every scalar row of `characterise` is a feature (histogram bins are not). Local Rent: terminals against nodes on
   growing balls (radius 1 to 4) fitted with Mimir's own `rent.fit`; four radii give at most 4 points, so the measurer's
   low-confidence flag (points < 5) is always set and is kept as a column, small regions are reported not dropped. `rent.measure`
   (recursive bisection) needs 512 nodes and `pymetis`; it is not run on regions this small.
2. Per atom (and per cluster as max and mean over real members): fan-in and fan-out cone size at depth 4, reconvergence excess of the
   fan-in cone (edges - nodes + 1 inside the cone; 0 for a tree), comb level, level / design depth, sequential level (absolute and
   / depth), level spread of the cluster, and the timing-proxy criticality.
3. Per LUT (one row per LUT x build x shuffle, dummies flagged): own fan-in and fan-out cones of depth 1, 2, 4 with the same Mimir
   calls, level, sequential level, used inputs (the inputs the truth table depends on), fan-out, drives-FF, chain-adjacent
   (reads a carry or drives an adder), function class from the truth table (constant, buffer/inverter, XOR/parity-like,
   AND/OR-like, MUX-like, other), share of dummies in its cones.
4. Labels per LUT: share of its C-cluster mates (other atoms of the same cluster of C) that stock puts in the same stock cluster;
   "whole" = that share is 1. "Used as seed" and "seed cluster equals its C cluster" need the pack census, which the pilot stock
   runs do not have: the code reads `sh<s>/census.tsv` if present and the pilot columns are empty; this is reported, not guessed.
5. Mining discipline. Effect sizes: AUC for the binary label (cluster: exact; LUT: whole), Spearman for the continuous label
   (cluster: purity; LUT: mates kept), each pooled raw and stratified (feature replaced by its percentile within the build).
   Resampling unit: the cluster (all its shuffle rows together, stratified by build); 1000 resamples give a two-sided bootstrap p
   per feature, Benjamini-Hochberg FDR over all features of a level, 10000 resamples and Holm for the top 40, design-level bootstrap
   (3 designs: 27 distinct resamples, nearly uninformative) beside it. Best feature per family (size, connectivity, level,
   fan-out, reconvergence, cone, Rent, timing proxy, function) and per region. Missing feature values are replaced by the column
   median; a feature with more than 30 percent missing or no variation is dropped. The ranking key is |AUC - 0.5| + |rho| / 2
   (stratified). Baseline: the stratified AUC and Spearman of the max-criticality proxy.
6. Artefact checks: Spearman of each feature with the number of dummies of the cluster (|rho| >= 0.7 flags it), the same feature on
   the real-only and the with-dummies view (D' with dummies deleted is the nearest we can get to D: the original D is not
   recoverable from the pilot outputs because D' atom names are random tokens and no map back to D is stored; this is a limit of
   the data, said in the results), own against foreign signs, and the dummy share in a LUT's cones. Whether the LUT-level and
   cluster-level signals agree: Spearman across the Mimir metrics both levels measure (the cone metrics) of their signed effects,
   and the best feature per family at both levels side by side.
7. The script takes any list of build directories; the controller reruns it on the round 9 full set.

## Results 2026-10-29 (pilot, 3 designs: a pointer, not a verdict; register row MEASUREMENT)

Command: `$NR_PY scripts/seed_signal.py <6 build dirs> --out-json data/analysis/seed-signal.json --out-prefix data/analysis/seed-features-pilot`
(about 5 minutes). The same command on any list of build dirs reruns it on the round 9 full set. Data: 151 cluster instances in
6 builds (426 rows after dropping the clusters below), 3 shuffles each; 1093 real LUTs (3279 rows); 202 dummy LUTs flagged and not
mined. In all 18 builds-by-shuffle the stock `.net` is byte-identical across VPR seeds 1 to 3, so one was used. Exact rate of stock
per build: ch_intrinsics own 0.50 / foreign 0.25, diffeq1 0.19 / 0.07, mkPktMerge 0.73 / 0.62.

### Plain English

* The numbers Peter asked about, the ones the plan named, mostly carry no signal about whether stock VPR rebuilds a cluster: pin
  pressure, tightness, neighbour count, loyalty, largest internal component, input count, chain present and the maximum or mean
  pack-time criticality have stratified AUC 0.43 to 0.58 and do not pass FDR (chain: q = 0.35 for AUC, 0.07 for purity). The maximum
  criticality, VPR's own seed basis, is at AUC 0.51 (q = 0.84), pooled raw 0.42 only because ch_intrinsics (AUC 0.28) differs from
  the others (a between-design effect, removed by the stratification). Two atom features of the plan do pass: the largest member
  fan-out (AUC 0.34, q = 0.013) and the best member centrality (0.36, q = 0.013): the higher, the less often the cluster is rebuilt.
* What does show a signal after Benjamini-Hochberg are Mimir structural metrics of regions around the cluster, mostly the
  sequential level (how many flip-flops sit between the primary inputs and the region), plus the width and constant content of the
  neighbouring logic. Clusters whose surroundings are deeper in sequential levels are more often rebuilt exactly (AUC 0.70 for the
  largest sequential level in the fan-out cone, depth 4, 90% cluster-bootstrap interval 0.64 to 0.76). It is not an artefact of
  dummies (Spearman with the dummy count -0.04), it has the same sign on own and foreign C (0.63 / 0.70), but it flips sign on
  mkPktMerge (per-design AUC 0.69, 0.55, 0.40 for ch_intrinsics, diffeq1, mkPktMerge) and the design-level interval touches 0.5
  from below. A pointer, not a finding.
* At the LUT level (does stock keep a LUT with all of its C-cluster mates) the same families appear: sequential level of the LUT
  (AUC 0.69), constants and unreached logic in its fan-in cone, fan-in width. Cluster level and LUT level agree on direction for
  the level, fan-out, reconvergence and Rent families (same sign of the best feature) but not on the individual features: across
  the 76 cone metrics both levels measure, the rank correlation of the signed effects is 0.23 and the same-sign share is 0.57, so
  weakly agreeing at best.
* Two things about D' came out of the extraction. (1) D' contains combinational loops: 1, 0, 69, 54, 35 and 43 back edges had to be
  cut (ch_intrinsics foreign / own, diffeq1 foreign / own, mkPktMerge foreign / own) for Mimir's level computation, none of them at a
  dummy; the cleaned D has none (checked with `mimir.hutton.levels`). They come from Step C (fill or doubling reading the net of a
  cell without a flip-flop) and are a construction artefact of the benchmark worth fixing before the full run. (2) The clusters
  holding the `gnd` or `vcc` generator (9 clusters, 34 more hold a carry chain) behave differently: VPR instantiates those LUT atoms
  itself and never rebuilds the cluster (exact rate 0 against 0.36), which made `has_const_generator` the top "feature" until the
  clusters were excluded from the mining (kept in the CSV).

### Method as run (and what was added to the plan)

* Added to the plan: (i) clusters with a constant generator excluded from mining; (ii) near-constant features dropped (commonest
  value over 95 percent of rows), because two or three clusters can then decide an AUC (it happened: fan-in width and closeness
  with 141 of 142 clusters at one value); (iii) identical columns reached through two regions or views kept once, aliases listed in
  the JSON; (iv) a second pass without the 34 chain clusters, because chain and constant content drive several cone metrics (the sign
  of `n_const` in the LUT-level fan-in cone flips between "all" and "no chain": AUC 0.28 with chain clusters, 0.72 without);
  (v) the ranking and the labels are the stratified ones (percentile of the feature within its build).
* Seed rank: the pilot stock runs have no pack census, so the rank is the position in the `.net` (cluster creation order) and the
  seed-atom labels ("stock used it as a seed", "its seed cluster equals its C cluster") are empty; the code reads
  `sh<s>/census.tsv` where one exists. The census file under the pilot (`ch_intrinsics/own/sh1/t_x/census.tsv`) is an earlier
  exploratory run and was not used.
* Criticality is the proxy of the plan (no census). Rent: `rent.measure` needs 512 nodes and `pymetis` (not in the venv); the local
  Rent is the growing-ball terminal count fitted with Mimir's `rent.fit`; its exponent is missing for most clusters (the Mimir fit
  window 4 <= B <= N/32 is empty for designs this small), so only `rent_points` and `rent_T_over_B` enter; the low-confidence flag
  is always set.
* The original D cannot be recovered: D' atom names are random tokens and no map back is stored. The D-against-D' check is therefore
  the real-only view (dummies deleted) against the with-dummies view of D', plus Spearman of each feature with the dummy count.
  Features that depend on Step C fill edges (all LUT-level level, edge-length and fan-in features: the fill ties LUT inputs to random
  nets of the cluster) cannot be separated from the real structure with these files; they are marked construction-sensitive below.
* Statistics as planned: AUC and Spearman, 1000 cluster-bootstrap resamples for the p of every feature (BH over 430 cluster-level and
  166 LUT-level features), 10000 for the top 40 with Holm, design-level bootstrap printed beside it. With 3 designs and 1000
  resamples the smallest possible p is 0.001, so q-values bottom out near 0.01; the interval widths matter more than the q.

### Top cluster-level features (exact: AUC, purity: Spearman; stratified; 90% cluster-bootstrap interval)

| feature | family | AUC exact | interval | rho purity | interval | q (BH) | per design AUC (ch, diffeq1, mkPkt) | own / foreign AUC |
|---|---|---|---|---|---|---|---|---|
| a:R3d4.seq_levels (max sequential level, fan-out cone depth 4) | level | 0.700 | 0.64 to 0.76 | 0.32 | 0.22 to 0.42 | 0.013 | 0.69, 0.55, 0.40 | 0.63 / 0.70 |
| a:R1.seq_levels (the cluster itself) | level | 0.697 | 0.64 to 0.75 | 0.31 | 0.21 to 0.41 | 0.013 | 0.69, 0.55, 0.35 | 0.63 / 0.71 |
| r:R2d2.fanin_max (widest LUT in fan-in cone depth 2) | size | 0.342 | 0.28 to 0.40 | -0.27 | -0.37 to -0.18 | 0.013 | 0.50, 0.70, 0.50 | 0.35 / 0.28 |
| r:R1.seq_unreached | level | 0.313 | 0.26 to 0.37 | -0.21 | -0.30 to -0.12 | 0.013 | 0.50, 0.60, 0.29 | 0.31 / 0.26 |
| a:R3d4.n_latch (FFs in fan-out cone depth 4) | cone | 0.365 | 0.31 to 0.43 | -0.29 | -0.40 to -0.18 | 0.013 | 0.27, 0.35, 0.33 | 0.29 / 0.44 |
| r:closeness_max (best member centrality) | connectivity | 0.362 | | -0.21 | | 0.013 | | same sign |
| r:fanout_max (largest member fan-out) | fanout | 0.337 | | -0.22 | | 0.013 | | same sign |
| r:R4k2.reconv_R (ball k = 2) | reconvergence | 0.369 | | -0.18 | | 0.013 / 0.054 | | same sign |
| baseline r:crit_max (VPR seed basis, proxy) | timing proxy | 0.51 | | 0.03 | | 0.84 | 0.28, 0.59, 0.58 | |

Without the chain clusters (333 rows): level `a:R1.seq_levels` AUC 0.71 (0.64 to 0.78), rho 0.40; `n_const` in the fan-in cone
0.71; `intdeg_max` / `closeness_max` 0.33 (rho -0.45); `fanout_max` 0.36 (rho -0.30); `R2d1.reconv_R` 0.64; crit_max 0.47.
Best per family (all clusters): level 0.70, cone 0.365, size 0.34, fan-out 0.34, connectivity 0.36, reconvergence 0.37, function
(`max_inputs`) 0.43 (n.s.), Rent 0.54 (n.s., q = 0.50), timing proxy 0.57 (n.s.). The full table is `data/analysis/seed-signal.json`.
Design-level 90% intervals (27 distinct resamples) for the top features: seq_levels 0.54 to 0.71, fan-out width 0.30 to 0.56.

### LUT level (whole = all C-cluster mates kept; 3279 rows of real LUTs; mean share of mates kept 0.66, dummies 0.68)

Top: `L2d2.seq_unreached` AUC 0.275 (0.23 to 0.33), `L2d1.n_const` 0.278, `seq_level` 0.69 (0.64 to 0.75), `L3d1.fanin_max` 0.32,
`fn_class=xor_like` 0.63 (best function feature), best per family otherwise as in the JSON; `crit_lut` 0.56 (q = 0.12). Without the chain
clusters: `seq_level` 0.71 (0.66 to 0.77), `L2d4.n_const` 0.69, fan-in width 0.34 (dummy share Spearman -0.40, partly a
construction effect), `fn_class=xor_like` 0.67. Function class mostly reads which LUTs received Step C fill: construction-sensitive.

### Which are construction artefacts, and the recommendation

* Artefact (excluded or flagged): `has_const_generator` (and `a:real_fill`, its alias), anything whose value is decided by 2 to 3 clusters
  (fan-in width and closeness in the first run, now dropped), `real_fill` (equals 1 - dummies / 10 by construction; mined, AUC 0.48),
  fan-in width of cones (Spearman -0.29 to -0.41 with the dummy count or dummy share: construction-sensitive), LUT function
  class and LUT edge-length metrics (Step C fill), `n_const` and `seq_unreached` (carry-chain constants: sign flips without chain
  clusters).
* Not artefacts by the checks available (|rho| with dummies < 0.1): sequential level position (cluster R1/R3, LUT), `fanout_max`,
  `closeness_max`, `reconv_R` of the fan-in cone depth 1. Same sign on own and foreign for all of them.
* Recommended for the step-2 seed probe (forced seed list in the packer overlay, after round 9) and for the round 9 full data,
  as candidates to test, not as results: (1) sequential level position of the cluster or seed atom (`seq_levels` of R1 and R3d4; LUT
  `seq_level`); candidate why: stock's seed order uses a flat criticality (AUC 0.51), the pipeline stage is a stronger separator of
  clusters that VPR will keep together, so seeding by stage may close each stage before moving to the next; (2) largest member
  fan-out and best member centrality (`fanout_max`, `closeness_max`; negative: high-fan-out members pull neighbours into several
  clusters, candidate why for seeding them last or never); (3) reconvergence of the fan-in cone at depth 1 (`R2d1.reconv_R`;
  positive in the no-chain pass, negative in the all pass: test with chains excluded). Keep `crit_max` as the control arm.
  For the full set also log the pack census in the stock arm (`--norns_pack_census`), so the seed-atom labels exist.
* The larger caveat: three designs, `seq_levels` flips sign on mkPktMerge, and 430 + 166 features were tried. Treat the above as a list of
  what to rerun on the 35 designs, where the design-level bootstrap becomes informative.
