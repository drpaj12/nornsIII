# Norns round 3 protocol (written 2026-10-24, before any round-3 measurement or VPR run)

This file is committed and pushed before any round-3 measurement. Its commit SHA is the
"rule provenance" of round 3 (quoted in the paper). A rule may change only by a NEW dated entry
at the end of this file that keeps the old rule; the paper then reports the result under both.

Peter (2026-10-24), verbatim for the paper's research-log appendix:

> For Norns, one question is does the clustering step of FPGA mapping become the problem - how
> is the initial seeding for an hdl construct get clustered? We might have to make our version of
> clustering for this information (how is it done - just with TVpack?). Second, if we map designs
> and have provenance (including the clustering) what do we learn from the placed (just by
> aneealing results) can we make some questions like (what is close to one another and using the
> provenance info (why are things close to one another?)

> Also, the outputs (words) and the inputs as words also provide hints of where the words are in
> norns. Let's build our own Norns based packer from scratch (include it in Norns as a
> copy/modification to Apack to allow us to our controlled experiements).

## Common definitions

* Designs: the 15 of rounds 1 and 2 (`nornlib.DESIGN_ORDER`). Pilot designs (beta grid only):
  ch_intrinsics, stereovision3, diffeq2, diffeq1 (the 4 smallest). Checkpoint set: the 8
  smallest (the pilot four plus mkPktMerge, raygentop, sha, boundtop).
* Flow: stock VPR default flow of rounds 1 and 2 (the analytical-placement flow, whose packer is
  APPack, AAPack's flat-placement-guided variant; VTR 3c9a4d23b2, `k6_frac_N10_frac_chain_mem32K_40nm`),
  `--seed s`. The Norns packer is a build of the same tree with an overlay (packer/). One VPR at
  a time under the heavy lock.
* Logic CLB: a CLB (cluster) holding at least one LUT or FF atom; pad blocks, mult_36 and memory
  blocks are excluded from purity and split-factor metrics.
* Label levels: module (Odin III provenance module path of the atom's BLIF name; every logic atom has
  one), word (round-2 word membership, `runs/<d>/words/members.json`; ~49% of LUTs have none),
  io (Stage 3). Atoms without a label at a level are ignored by that level's purity.
* Purity of a CLB at a level: plurality share = (labelled atoms in the plurality label) /
  (labelled atoms in the CLB); CLBs with no labelled atom are excluded. Strict purity: the CLB
  is pure if it has >= 2 labelled atoms and all share one label. Design purity = mean of the CLB
  plurality share (atom-count weighted, i.e. sum of plurality counts / sum of labelled atoms in
  CLBs with >= 2 labelled atoms) and the fraction of strictly pure CLBs.
* Split factor of a label (word or module) with n atoms in logic CLBs: spanned CLBs / ceil(n / m),
  m = the largest number of atoms in any logic CLB of that packing; 1.0 is the best possible. Design
  split factor = median over labels with n >= 4, atom-weighted median reported too.
* Null packing: the same atoms, randomly assigned to CLBs keeping the stock packing's CLB sizes
  (atoms of the same pb class pool: logic atoms only), 50 samples (>= 20 required).
* Statistics. The unit is the design. Per-design value of an arm = geometric mean over the 3
  VPR seeds of the ratio against the matched stock-packing arm (same start type, same seed).
  Tests: Wilcoxon signed-rank (scipy, two-sided unless stated) on per-design log ratios; Holm
  correction over the 3 affinity sources inside a hypothesis; alpha = 0.05. Intervals: 10000-resample
  bootstrap over designs, seed 20261024, percentile. Every claim is reported for n=15 and for n=11
  (without the 4 pilot designs); if the two statuses differ the paper's status is "inconclusive
  (pilot-sensitive)". If only the 8-design checkpoint exists, results are provisional and carry no
  status.
* Status words: supported / not supported / inconclusive. Anything not decided by the rule below is
  inconclusive.

## RQ-N8: does packing dilute HDL structure? (no VPR; round-1/2 stock packings)

Data: `runs/<d>/runs/baseline/final.flat_place` (atom to CLB), `words/members.json`. Metrics: word
and module purity and split factor of the stock packing and of the null (above).

H8: stock APPack purity is low and its split factor high compared with what a structure-aware
packing could reach (reference: purity 1.0, split 1.0).
* Supported iff the median over the 15 designs of the stock word plurality share is <= 0.80 AND the
  median word split factor is >= 1.5.
* Not supported iff the median word plurality share is > 0.80 AND the median word split factor
  is < 1.5.
* Otherwise inconclusive. Module-level numbers are reported, not decided.
Reported, not tested: stock minus null purity per design; how much of round 2's word coverage loss
is the front end (ABC) and how much is packing, defined as: of logic atoms, loss_abc = atoms with no
word (split by `ngroups`: >= 2 mixed spans vs 0 no match) and loss_pack = word atoms that are not
in a CLB passing the 1/3 rule with that word as the CLB's plurality word.

## Stage 2: the Norns packer and its control gate

Overlay on VTR 3c9a4d23b2 (packer/): new options `--norns_affinity <file>` (TSV: atom name, integer
group id; atoms absent have no group) and `--norns_affinity_weight <beta>` (default 0).
Gain term: during clustering the open cluster has a dominant group (plurality of the grouped atoms
packed so far, ties to the lower id). A candidate molecule gets + beta for every atom of the molecule
that is in the dominant group, added to the molecule gain; and, when the cluster has a dominant
group, up to feasible_block_array_size unclustered molecules of that group are added to the
candidate queue (so parallel bit-slices without a direct net can be proposed). Legality is
AAPack's legalizer, unchanged. Scale: stock per-atom gains lie in [0, 1] (connection and sharing
gain are divided by the pin count; timing gain in [0, 1]); beta is in those units.

CONTROL GATE (must pass before any experiment run): for all 15 designs, with the option absent and with
`--norns_affinity_weight 0` (affinity file given), the Norns `vpr` writes a `.net` byte-identical
to stock `vpr`'s (same arch, args, `--seed 1`) in (i) `--pack` and (ii) the default analytical flow
(`--analytical_place`, no route). Any difference, in any design, blocks Stage 4. A difference that
is only an id or time stamp may be handled by a documented canonicalisation, reported in the paper.

## RQ-N10: I/O words (Stage 3)

Definition: a top-level input or output bus `name[i]` is an io-word `io:<dir>:<name>` (inputs and outputs
separate). Propagation inward along bitwise-parallel paths: BFS from the pad bit through LUT and FF
atoms only (not hard blocks), toward the core (backward from output pads, forward from input pads), k = 2
atom hops, through nets of fanout <= 16. An atom with no round-2 word gets the io-word iff it is reached
from exactly one bit of that io-word, and from no bit of another io-word (conflicts: unlabelled). Atoms
with a word keep it. Coverage: LUT and FF atoms with a word, with an io-word, and the union.

H10a: io-words cover part of the LUTs round 2 left without a word.
* Supported iff the median over the 15 designs of (word+io LUT coverage minus word LUT coverage) is
  >= 0.05 and the gain is > 0 on >= 12 designs.
* Not supported iff the median gain is < 0.01.
* Otherwise inconclusive.

H10b: affinity source word+io beats word-only: geometric mean WL ratio (word+io arm over word arm
at the same beta index, analytic start, 3 seeds) < 1 with Wilcoxon two-sided p < 0.05 and CLB count
within the H9a margin.
* Supported iff geomean ratio <= 0.99 and p < 0.05 at the headline beta.
* Not supported iff the geomean ratio >= 1.00 or the 90% bootstrap interval lies inside [0.98, 1.02].
* Otherwise inconclusive.

## RQ-N9: controlled packing experiments (Stage 4)

Arms per design: `stock` (stock vpr); `norns-<source>-<beta>` with source in {module, word, wordio} and 3
betas per source. Start in {`analytic` (the default flow), `seed` (round-2 best family words_partial,
rebuilt on that run's own packing from its analytic run's initial.place and flat placement; the same
1/3-atoms rule and fixed rules as round 2)}. VPR seeds 1, 2, 3.
Pilot (beta grid; packing only, no routed WL is read): beta list B = {0.05, 0.1, 0.2, 0.5, 1, 2, 4},
the 4 pilot designs, `--analytical_place` runs, seed 1. Per source, beta_m = the largest beta in B whose
median CLB-count growth over the pilot designs is <= +5%; if none, 0.05. The final grid for that source
= {B[i-1], B[i], B[i+1]} around beta_m (clipped to the list ends, shifting inward). The headline
configuration of a source is (source, beta_m). Choice of beta uses only purity and CLB count; the
four pilot designs are also reported excluded (n=11).
Metrics: purity at the source's label level (module for module; word for word and wordio), split factor,
CLB count, FPGA grid size, routed WL, minimum channel width, critical path, pack + place runtime.

H9a: affinity packing raises purity with CLB count growth within a stated margin.
* Per source at its headline beta, per design: purity gain = arm minus stock (plurality share at the
  source's level), CLB growth = arm CLBs / stock CLBs - 1.
* Supported iff the median purity gain >= 0.05, Wilcoxon (one-sided, gain > 0, Holm over sources)
  p < 0.05, median CLB growth <= +5% and no design above +15%.
* Not supported iff the median purity gain < 0.02, or the median CLB growth > +5% with a purity gain
  below 0.05.
* Otherwise inconclusive.

H9b: affinity packing alone (analytic start) changes routed WL against stock packing (two-sided).
* Supported (a change; the sign is reported) iff |ln geomean ratio| >= ln(1.01) and Wilcoxon
  two-sided Holm-adjusted p < 0.05 at the headline beta.
* Not supported iff the 90% bootstrap interval of the geomean ratio lies inside [0.98, 1.02].
* Otherwise inconclusive.

H9c: affinity packing + word seed beats stock packing + word seed on routed WL.
* Supported iff geomean ratio <= 0.99 and Wilcoxon one-sided (ratio < 1) Holm-adjusted p < 0.05.
* Not supported iff the geomean ratio >= 1.00.
* Otherwise inconclusive.

Wall-time guard: runs per design = 60 (stock 3 + 27 analytic Norns + stock-seed 3 + 27 seeded Norns); if
the estimated VPR time exceeds ~8 h the 8 smallest designs run first, are committed and reported as
a checkpoint (no status), then the rest.

## RQ-N11: what does the annealed placement say? (Stage 5; stock packing, analytic start, seeds 1-3)

CLB-level pair relations (logic CLBs): same word (both CLBs have a plurality word under the 1/3 rule and
it is equal), same module (plurality module equal), same HDL statement (file:line of the plurality
atom's name equal), net-connected (share >= 1 net of fanout <= 32), io-word (same io-word),
none. Distance: Manhattan CLB distance in the final placement. Null: positions permuted among logic
CLBs (200 permutations) keeping the net structure fixed. Direct net count n_ij (distinct shared nets
of fanout <= 32), strata 0, 1, 2-3, >= 4.

H11: same-word and same-module pairs are closer than net connectivity alone predicts. For each
relation r in {same word, same module} and design: d_r = stratified mean distance difference (related
minus unrelated within each n_ij stratum, weighted by the number of related pairs per stratum), as a
fraction of the mean distance of the unrelated pairs, averaged over the 3 seeds; permutation p
over relation labels within strata (1000 permutations, pooled over designs).
* Supported (per relation) iff the median over designs of d_r <= -0.05, the Wilcoxon one-sided (d_r < 0)
  p < 0.05 and the sign is negative on >= 2 of the 3 seeds in >= 12 of the 15 designs.
* Not supported iff the median d_r > -0.01.
* Otherwise inconclusive. The paper reports H11 as supported only if both relations are.
Reported, not tested: neighbour stability (mean Jaccard of each CLB's 4 nearest neighbours between seed pairs,
and the same for a seed-permuted null); a top-pairs "why are these neighbours" table per design
(direct nets, shared high-fanout net, carry chain, timing-critical path; the last is "not
available" when VPR's log does not give it).

## Round-2 T0 confound

Round 2's seeds also changed the annealer's start temperature (3.1 to 9.2x). Round 3 does not remove
that confound (the annealing schedule is VPR's default for every arm, and a seeded start still carries
its own start temperature), but H9b uses the analytic start, where start temperature differs only through the
packing itself; the paper states this.
