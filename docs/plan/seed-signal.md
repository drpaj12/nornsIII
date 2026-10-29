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
