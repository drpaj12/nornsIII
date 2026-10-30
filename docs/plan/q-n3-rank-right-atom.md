# Q-N3: is there data in the circuit that ranks the right atom above the wrong pick? (plan written 2026-10-30, before the analysis)

This file is committed and pushed before any label, feature or number of this analysis is computed. It is not edited after the analysis;
results are appended below under their own dated heading. It is a MEASUREMENT (offline; no VPR run; no QoR claim).

## Plain-English summary

Peter (2026-10-30, framing doc `docs/plan/framing-2026-10-30.md`): "Currently, from a known ordering of seeds that recreates the "best"
clustering of the artificial circuit we ask, is there data in the circuit that would lead to that guess - if we can find that, then we have an
innovation for clustering question." Q-N2 found that 60 percent of the CLB gap is APPack adding an atom of another known cluster while a
legal atom of the seed's own known cluster was already waiting in its queue, with a strictly lower queue gain in 99.84 percent of those
picks (26,214 picks). So the data question is: is there something computable from the circuit, at the moment of the pick, that would have
ranked the right atom above the wrong pick? If yes, that is a candidate group-aware gain term (the clustering innovation). Offline only:
we replay the packer's decision log, compute candidate features at each pick from the cluster built so far and the netlist D', and measure
how often each feature (and a small combined score fitted on half of the designs) puts the right atom ahead of the pick, on the other half.

Purpose (hub docs/purpose.md): Norns, packing quality; path purpose "good centroids from the design via good packing". Measure: offline
ranking quality (pairwise AUC and top-1 of the right atom among the queue) on held-out designs. No area, speed or wirelength claim.

## Data (read only)

* `work/r9-out-v2/<design>/<own|foreign>/sh<k>/{census.tsv, affinity.tsv, design.blif, vatoms.json, run-*/stock.s1/design.net}`: the 264 packs
  of Q-N2 (33 designs, own and foreign C, shuffles 0 to 3); `build.json` (`cells_real`, `dummies`).
* `work/q2-out/runs5` (Q-N2 per-pack summaries) only as the cross-check of the b-pick counts (total 26,214). The raw labels are re-derived by
  the Q-N2 replay itself (`scripts/q2gap.py`, extended with a log-only callback; with no callback its output is unchanged, tested).
* `work/n1b-out`: Q-N1b oracle logs, for the seed comparison (step 4).

## Label set

Unit = a pick event of the Q-N2 replay: stock cluster s, c0 = known cluster of its seed, the packer adds molecule m.
* WRONG pick (b): m is of another known cluster although at least one free (not clustered, fits the free slots) member of c0 is in the
  candidate queue. The right atom(s) = those queued free members of c0. Same events as Q-N2 (b); the total must reproduce 26,214.
* RIGHT pick (control): m is a member of c0, at least one OTHER free member of c0 is queued (so that a rule could have chosen wrongly).
  Subsampled 1 in 3 by a fixed hash of (design, cons, shuffle, cluster, index), only to keep the file small. Used in the top-1 comparison
  over all decisions (below), because on the wrong picks alone VPR's own gain scores 0 by construction (the wrong pick was the maximum).
Per event kept: the cluster's atoms before the pick, every queued unclustered molecule with its queue-time VPR gain (Q record), the pick with
its gain, the right molecules.
Strata of the wrong picks (decided here, on pack-time data the packer had): the timing gain of a molecule at the pick = VPR's own term, the
largest pack-time criticality of a pin on a net joining its root atom to the cluster (recomputed from the `P` records and the netlist; checked
against the `A` record of the pick, agreement rate reported). TIMING-PULL pick: the pick's timing gain is strictly larger than the right
atom's (best of the right atoms). CONNECTIVITY pick: all the rest. The innovation target is the connectivity stratum; the timing-pull picks may be
deliberate speed choices (framing doc, "Why speed is outside the yardstick"). Both are reported; connectivity first.

## Features (C-free: computed from the netlist D' and the cluster built so far; C and its cluster ids are NEVER used)

For candidate molecule M (all its atoms) and the cluster Cl before the pick. Nets with more than 32 sinks are ignored (the packer does
too). Sign = the expected direction, fixed now; AUC below 0.5 means the opposite sign, and is not flipped.
1. `shared_nets` (+): distinct nets with a pin in M and a pin in Cl.
2. `common_nbrs` (+): atoms outside M and Cl adjacent to both (two-hop link count).
3. `members_2hop` (+): atoms of Cl within two hops of M.
4. `absorbed` (+): nets that become fully internal to Cl+M by the add and had a pin in M.
5. `d_pins` (-): increase of distinct external input nets of Cl+M over Cl (pin pressure); the score is the negative.
6. `fanout` (-): number of sinks of the root's output net (the score is the negative).
7. `seq_gap` (-): |sequential level of M minus mean sequential level of Cl| (score negative); sequential level = fewest flip-flops on a
   path from a primary input (0-1 BFS on D').
8. `nearcrit_shared` (+): near-critical edges (pack-time pin criticality >= 0.90) between M and Cl.
9. `bitslice_word`: NOT AVAILABLE. Atom and net names of D' are opaque random tokens (round 9, Step D) and no map back to D is stored
   (seed-signal, same limit), so word and bit-slice membership cannot be computed. Said, not guessed.
Baseline: VPR's own queue gain (Q record).
Construction-sensitive features and the artefact check (as seed-signal did): dummy atoms (Step B padding: vertices after `cells_real`,
count `dummies`, via `vatoms.json`) are known, Step C fill nets are not identifiable. Every result is reported (i) on all events and (ii) on
the "real view": events where neither the pick nor any right atom nor any other queued candidate under comparison is a dummy and with
dummies deleted from the cluster state and from the nets (features recomputed). A feature whose AUC changes by more than 0.05 between (i)
and (ii), or that is a function of dummies, is called construction-dependent. Step C fill nets (which tie LUT inputs to nets inside a
cluster, so shared and absorbed nets are higher inside C by construction) cannot be removed: features 1 to 4 and 7 are marked
construction-sensitive in advance. Own against foreign C is reported separately: a feature that works on own C but not foreign C may only read
VPR's own authorship of C.

## Split (by design, fixed here, before any label is read)

Designs ordered by SHA-256 of "q-n3:" + name; the first 16 are TEST, the other 17 TUNE. Own and foreign C of a design are on the same side.
* TEST (16): bigkey, boundtop, ch_intrinsics, diffeq, diffeq1, dsip, elliptic, ex1010, frisc, mkPktMerge, or1200, pdc, s38584.1, seq, sha, tseng.
* TUNE (17): alu4, apex2, apex4, blob_merge, clma, des, diffeq2, ex5p, misex3, mkDelayWorker32B, mkSMAdapter4B, raygentop, s298, s38417,
  spla, stereovision1, stereovision3.

## Measures and the rule

* Pairwise AUC (right vs pick): per wrong pick, 1 if the feature of the (best) right molecule is higher than the pick's, 0.5 on a tie, 0 if
  lower; the mean over events. Event-level, not pooled across events (feature scales differ between clusters). Per design mean first
  (all events of a design, equal weight per design), then the mean over the TEST designs; 90 percent percentile bootstrap over TEST designs
  (10000 resamples, seed 20261030).
* Top-1: the share of events in which the molecule with the highest score in the whole queue (the pick plus all queued candidates) is a
  right molecule; ties share the credit equally. On wrong picks alone VPR's gain scores about 0 (selection effect, said in the results). The
  honest comparison is top-1 over ALL decisions (wrong + sampled right picks, weighted back by 3 for the sampling): the share in which the
  top-scored queued molecule is a member of c0. VPR gain on that set = the share of correct picks.
* Combined score: logistic regression on the feature differences (right minus pick, standardised on TUNE), no intercept, L2 = 1, fitted on
  TUNE wrong picks of the connectivity stratum with the right picks as contrast (for the all-decisions set the score of a candidate = w . its standardised
  feature vector, VPR gain among the features in one variant, left out in the other). Two variants: C-free features only (A) and A plus the
  VPR gain (B). Evaluated on TEST as above. No tuning on TEST.
* Multiplicity: Benjamini-Hochberg over the 8 features x 2 strata x {own, foreign} two-sided bootstrap p values of AUC against 0.5.
* Decision wording: a feature "ranks" if its TEST AUC lower bound (90 percent) is above 0.55 in the connectivity stratum, with the same sign
  on own and foreign, BH q < 0.05, and not construction-dependent. Else it does not. The combined score "helps" only if its top-1 over all
  decisions on TEST exceeds VPR's by a bootstrap interval that excludes 0. The verdict word is MEASUREMENT; candidate gain terms are listed
  as UNTESTED ideas.

## Step 4: are oracle seeds special? (Peter: "is the seed node the most important node of the cluster?")

From the Q-N1b logs (`NORNS_ORACLE` lines, the winning seed per known cluster) compare, on the same netlist-only features (fan-in, pack-time
criticality, centrality in the cluster-internal graph, sequential level, fan-out): the winning seed against the stock seed of that cluster and
against a random member of the cluster (mean over all members), as pairwise AUC per cluster with a design-level bootstrap. Only the clusters
rebuilt exactly (exact=1) have a meaningful winning seed; reported for those and for all.

## What this cannot show

The census logs one stock run; it does not say what the packer would have done after a different pick (needs a run; none is made). Features
are measured on D', whose fill and padding shape nets inside the known clusters. The queue-time gain is VPR's own; the right atom's legality
is judged by free slots and the logged refusals. Distance attenuation of APPack is not measured. Offline ranking is necessary, not sufficient,
for a better packer: only a downstream run (not part of this entry) can show QoR.
