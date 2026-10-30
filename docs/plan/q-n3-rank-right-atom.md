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

## Results, 2026-10-30 (measurement; offline; no VPR run was made)

Command: `python scripts/q3feat.py <r9 root> <out>` (labels and features, 264 packs, 15 s), `python scripts/q3stats.py` (statistics), `python scripts/q3table.py`
(tables in `data/q3/tables.md`, numbers in `data/q3/summary.json`), `python scripts/q3seed.py` (step 4). Tests: `tests/test_q3.py`.

### Plain English

Is there something in the circuit that would have told the packer to take the right atom instead of the wrong one? A little, but not robustly. Of the
Q-N2 wrong picks (26,214 per shuffle, the count reproduces), about 9,800 were picks where connectivity, not a timing pull, decided (37 percent) and about 16,400
had a timing pull (63 percent; the pick's timing gain beat the right atom's). On the 16 held-out TEST designs, counting nets that the right atom shares with
the cluster, the number of cluster atoms within two hops, the pin pressure and the common neighbours each put the right atom ahead of the pick in 61 to 69 percent
of the connectivity picks (VPR's own gain does so in 0.3 percent, by construction: the wrong pick was its maximum). A combined score fitted on the TUNE designs
reaches 0.69, and on all decisions (wrong and right picks together) its best-scored queued atom is a member of the seed's own known cluster in 84 percent of the
decisions against 77 percent for VPR's gain (+6.8 points, interval 5.5 to 8.2). But most of this signal depends on the dummy cells that the round 9 construction adds
to fill clusters (Step B): with the dummies deleted from the cluster and the nets, the single features fall to 0.53 to 0.61, the combined score falls to 0.59, and
on the connectivity decisions it no longer beats VPR (-5.2 points for the C-free score, +0.1 for the score that also uses VPR's gain). By the rule written above, **no
feature ranks the right atom robustly**: none of the eight passes (four are construction-dependent, the other four have a lower bound under 0.55). What remains after deleting the
dummies is a weak group-connectivity signal (best: cluster atoms within two hops, AUC 0.61, 0.58 to 0.65) that this benchmark cannot separate from the
construction (the Step C fill nets cannot be removed). The candidate gain terms below are UNTESTED ideas; nothing here is a QoR claim.

### Labels (Step 1)

Events reconstructed by the Q-N2 replay (`q2gap.analyse_run`, extended with a log-only callback; unchanged without it, tested). Total wrong picks 104,855 over
the 4 shuffles = 26,214 per shuffle (Q-N2: 26,214). Strata by recomputed pack-time timing gain (agrees with the logged `A` record of the pick in 386 of 386 picks
of the smoke test, alu4 own sh0). Counts (summed over the 4 shuffles):

| side | C | connectivity picks | timing-pull picks | right picks (sampled 1 in 3) |
|---|---|---|---|---|
| TUNE (17 designs) | own | 10,873 | 19,685 | 19,305 |
| TUNE | foreign | 9,261 | 15,722 | 21,851 |
| TEST (16 designs) | own | 10,506 | 16,310 | 9,272 |
| TEST | foreign | 8,640 | 13,858 | 10,789 |

Per shuffle (mean): 9,820 connectivity (37.5 percent) and 16,394 timing-pull (62.5 percent).

### Features on the TEST designs (Steps 2 and 3)

Pairwise AUC (right vs pick), mean over TEST designs, 90 percent bootstrap interval over designs; top-1 and the full tables are in `data/q3/tables.md`.
Connectivity stratum first. "real" = dummy atoms of Step B deleted from the cluster state, the nets and the candidates, features recomputed.

| feature | connectivity, all | own C | foreign C | real view | timing-pull, all | rule |
|---|---|---|---|---|---|---|
| members_2hop (cluster atoms within 2 hops) | 0.687 (0.662 to 0.711) | 0.681 | 0.701 | 0.612 (0.581 to 0.646) | 0.596 | construction-dependent (0.075 drop) |
| shared_nets | 0.675 (0.643 to 0.711) | 0.682 | 0.672 | 0.577 (0.543 to 0.616) | 0.595 | construction-dependent (0.098 drop) |
| common_nbrs | 0.633 (0.600 to 0.665) | 0.688 | 0.579 | 0.582 | 0.637 | construction-dependent |
| d_pins (pin pressure, lower better) | 0.610 (0.579 to 0.643) | 0.618 | 0.605 | 0.526 | 0.670 | construction-dependent |
| absorbed | 0.563 (0.540 to 0.590) | 0.539 | 0.597 | 0.562 | 0.730 | lower bound 0.54 |
| seq_gap | 0.554 (0.532 to 0.575) | 0.571 | 0.534 | 0.497 | 0.662 | lower bound, construction |
| nearcrit_shared | 0.541 (0.519 to 0.565) | 0.550 | 0.530 | 0.527 | 0.439 (opposite sign) | lower bound 0.52 |
| fanout (lower better) | 0.531 (0.505 to 0.557) | 0.538 | 0.530 | 0.557 | 0.749 | lower bound 0.51 |
| VPR gain (baseline) | 0.003 | 0.002 | 0.005 | 0.004 | 0.000 | selection effect |
| combined A (C-free features, fitted on TUNE) | 0.686 (0.655 to 0.720) | 0.683 | 0.694 | 0.593 (0.555 to 0.632) | 0.628 | - |

BH q (32 tests) is below 0.05 for every feature in both strata (largest 0.049, `common_nbrs` foreign connectivity), so q does not decide the rule; the lower bound and the artefact check do. Own and
foreign C agree in sign for all features. Top-1 on the wrong picks (the best-scored queued molecule is a right one): combined A 0.509 (0.461 to 0.567) on the
connectivity stratum (0.373 real), best single feature `shared_nets` 0.449; VPR gain 0.002. Because VPR's gain scores about zero on wrong picks by
construction, the fair comparison is top-1 over ALL decisions of the connectivity set (wrong picks plus sampled right picks, weighted back): VPR 0.774 (0.742 to 0.806),
combined A 0.842 (0.816 to 0.870), difference +0.068 (0.055 to 0.082); combined B (adds VPR gain) 0.839, +0.065. In the real view the same differences are
-0.052 (-0.075 to -0.030) for A and +0.001 (-0.004 to 0.006) for B (the models are refitted on the real-view features of TUNE). Over all picks including the timing-pull
ones, B reaches +0.140 (full) and +0.048 (0.040 to 0.057, real) over VPR; these include picks that may be deliberate speed choices.

Construction artefact check, said plainly. The dummies added in Step B are in the stock clusters and their inputs come from nets inside the same known cluster, so
a dummy in the cluster state probably leaks which known cluster it belongs to (the drop in AUC when they are deleted is consistent with this; not isolated further); deleting them is the nearest view to the real design D (D itself is not recoverable, as in
seed-signal). Step C fill nets cannot be separated and the five connectivity features (1 to 4 and 7) were marked construction-sensitive in advance. Word and
bit-slice membership could not be measured at all (names of D' are opaque). The model weights (standardised, TUNE): `members_2hop` +0.69, `shared_nets` +1.23,
`common_nbrs` -1.11 (collinear with the first two), `d_pins` +0.67 in the full view; `shared_nets` +0.65, `common_nbrs` -1.49, `d_pins` +0.52 in the real view
(`data/q3/summary.json`).

### Are oracle seeds special? (Step 4)

The Q-N1b log does not name the winning seed. For the 1,291 exactly rebuilt clusters (25.5 percent of 5,071, own C, ordered shuffle sh0) the winner is
reconstructed as the `trials`-th molecule of the cluster in ascending root-atom statement order of `design.blif`; the reconstruction is checked by the number
of molecules of the cluster equalling the logged `candidates` (1,291 of 1,291). Not verified against an explicit seed log. In 1,099 of them (85 percent)
`trials` = 1: the first molecule in file order already rebuilds the cluster, so for most clusters there is no distinctive winner. Pairwise AUC (winner
higher than the other members, mean over 32 designs, 90 percent interval): fan-in 0.508 (0.504 to 0.513), pack-time criticality 0.510 (0.467 to 0.549),
closeness in the cluster 0.493 (0.470 to 0.517), sequential level 0.491 (0.484 to 0.499), fan-out 0.582 (0.550 to 0.617); with dummies left out 0.512, 0.475,
0.510, 0.501, 0.556. Against the stock seed of the same known cluster (261 winners are the stock seed itself; the rest compared, 26 to 32 designs):
fan-out 0.730 (0.658 to 0.800), fan-in 0.544, sequential level 0.524, criticality 0.443 (0.348 to 0.537), closeness 0.450. On the 192 clusters where an
earlier candidate failed (`trials` > 1) the winner is LESS critical than the stock seed (AUC 0.257, 0.163 to 0.359) and than the members (0.398, 0.318 to
0.479) and has higher fan-out than the stock seed (0.725, 0.645 to 0.806). Answer to Peter's question "is the seed node the most important node of the
cluster?": on these features no. The winning seed is not the most critical, not the most central and not the best-connected member; it is mostly an arbitrary
member, and where a choice mattered it was a less critical atom with a larger fan-out than the one VPR picks. Caveat: with 85 percent `trials` = 1 the
winner mostly reflects file order, not a ranking by quality, so this is a negative result for "special", not a positive result for the fan-out hint.

### Candidate gain terms (UNTESTED ideas)

1. A group-aware term in the candidate gain: the number of cluster atoms within two hops of the candidate (the best feature that survives deleting the dummies).
2. The same with the pin-pressure term (new input pins the candidate adds).
3. A tie-aware rule that discounts a pure timing pull when the timing-pull candidate adds many pins.
Each needs a downstream run on D' and on real designs (speed, wirelength, area), and a test on a benchmark without dummy padding; none is started.

### Verdict and limits

MEASUREMENT. By the rule fixed in the plan no feature ranks the right atom robustly and the combined score does not help on the connectivity decisions once dummies
are deleted; a weak group-connectivity signal (AUC 0.58 to 0.61) remains that this benchmark cannot separate from its construction. Limits: the right atom's
legality is judged by slots and refusals, not trial packing; the queue-time gain is VPR's own and includes APPack's distance attenuation, which was not logged;
the decisions are from one stock run (a different pick would change the rest of the packing; no counterfactual run); the stratum threshold (strictly larger timing
gain) is one definition and puts 63 percent of the picks in the timing stratum (Q-N2 counted timing pull differently: pick timing gain >= 0.9, 17 percent);
the real view also drops events involving dummies, so part of the change in AUC is a change of population; 16 TEST designs, shuffles of one design are not independent.
Q-N4 and the VPR arms are not started.
