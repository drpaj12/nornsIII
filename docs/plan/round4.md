# Norns round 4 protocol (written 2026-10-25, before any round-4 measurement or VPR run)

This file is committed and pushed before any round-4 measurement. Its commit SHA is the "rule provenance" of
round 4 (quoted in the paper). A rule may change only by a NEW dated entry at the end of this file that keeps the
old rule; the paper then reports the result under both.

Order of work. Nothing was built, changed or run for round 4 before this commit (no packer edit, no gate run, no
VPR run): the packer fixes and the Stage-1 gate runs follow it. The gate runs are not measurements of the
experiment (they compare `.net` bytes) and may use the data of rounds 1 to 3. Every rule below is stated before
any round-4 result exists; the round-3 data exist and were read by the lane (they fix design sizes and the
round-3 headline), the Stage-2 to Stage-5 outcomes were not.

Peter (2026-10-24), verbatim for the paper's research-log appendix:

> "Queue those as round 4 after round 3 finishes - we're trying to make these better - I like the
> Loki ideas so yes (especially the idea of patterns from our data (what about the bigger designs,
> do they provide other insights of patterns). Norns I like, but I'm not sure this machine can
> handle the big designs. Also, I feel as the design gets bigger it's inevitable that the size of
> the chip is related to hierarchy in the hdl. So, I would like to see how the new clustering
> methods impact results. AND getting some knowns from the dataset we have."

Peter (2026-10-25), verbatim:

> "So for Norns in the clustering packing phase is there a statement of what gets clustered that
> could be stated from what the packer does (the provinance) and what the starting design was (this
> is an answer to the heuristic approach that currently exists in the VTR packer (my hypothesis is
> that due to the pin width there is some sharing especially of certain paths, but there is also two
> orthoganal paths (or more) that should be packed together)) - note there might be a group of these
> statements where 10% are of this type, 75% are of this type and 15% are the leftovers that are
> non-critical - again the criticalness of the choices is a big factor, and the multi-near critical
> paths impacts the algorithm. What can we say about that? In both cases is there data on a
> perbenchmark setting using the provenance information? For loki, I'm wondering if we could have
> sentences such as why I can't recover this since we know we map it, there has to be some step that
> fools the unmapping - what are those steps and back it up with data."

Framing question (Peter): what in the design tells us where to put it on the chip to communicate minimally
(wirelength / channel width) and quickly (critical path)? The first item agreed with Peter on 2026-10-25 is the
packing census (RQ-N17).

## Common definitions

* Designs: the 15 of rounds 1 to 3 (`nornlib.DESIGN_ORDER`). Checkpoint set for Stage 5: the 8 smallest
  (ch_intrinsics, stereovision3, diffeq2, diffeq1, mkPktMerge, raygentop, sha, boundtop).
* Flow: VTR 3c9a4d23b2, `k6_frac_N10_frac_chain_mem32K_40nm`, the default analytical-placement flow of rounds 1 to 3
  (APPack inside it), `--seed s`; one VPR at a time under the heavy lock (`/tmp/claude-1000/odin3-heavy.lock`),
  lock per run or per design chunk, never across designs. The Norns packer is the round-3 overlay (`packer/`) with
  the round-4 changes of Stage 1.
* Norns headline configuration (carried from round 3): affinity source `word`, beta 4, `--norns_proposal_count
  queued` (the fixed counting of Stage 1). Reason: round 3 chose beta 4 for all sources (the largest beta of its
  list); `word` was the source whose purity gain was supported (H9a) with the largest gain (+0.111) and equals
  `word+io` on routed WL (H10b not supported). The round-3 behaviour (`--norns_proposal_count attempted`) is run
  as a labelled census arm only.
* Logic CLB, label levels, purity, split factor, null packing: as `docs/plan/round3.md` (null: 50 samples,
  exactly; a null sample keeps the stock packing's logic-CLB sizes and assigns the same logic atoms at random).
* Members: LUT (`.names`), FF (`.latch`) and adder atoms of logic CLBs. Pads, `mult_36` and memory blocks and
  their CLBs are not members. A pair is an unordered pair of members in the same logic CLB; a CLB with one member
  has no pair.
* Nets: BLIF nets other than clock nets (a net that drives a `.latch` clock pin). Fanout = sink pin count.
  A net is local if its fanout is <= 32 (as H11), a broadcast net if its fanout is > 32.
* Pack-time criticality of an input pin: VPR's `setup_pin_criticality` from the pre-cluster timing analysis the
  packer itself uses (recorded by the census, Stage 1). Pack-time criticality of an atom = the maximum over its
  non-clock input pins. theta_c = 0.5 is the critical threshold.
* Statistics: the unit is the design. Wilcoxon signed-rank (scipy, `zero_method` default, zero differences dropped,
  needs >= 6 non-zero differences else p = NaN counts as 1.0); alpha = 0.05; Holm correction over the tests named
  in each hypothesis (m = the number named, NaN counts as 1.0). Bootstrap: 10000 resamples over designs, seed
  20261025, percentile interval. Per-design value of an arm = geometric mean over the 3 VPR seeds of the ratio
  against the matched reference (same start type, same seed). Every claim is computed on all designs with data
  (n stated) and, labelled, on the 11 designs without the 4 smallest. The literal rule on the n actually available
  is the status. If a design drops out of a comparison (a run failed), the rule's counts "of 15" become the
  stated fraction "ceil(0.8 n)" and the paper says so; if n < 12 the status is "inconclusive (n < 12)".
* Status words: supported / not supported / inconclusive. Anything not decided by the rule is inconclusive.
* Class definitions must not be empty by construction and must not depend on the arm they judge: the shares
  below are therefore compared between packers only on classes that do not use the affinity labels (H17b).

## RQ-N17: what gets clustered, and why (Stage 2)

Packings. Pack-and-place runs without routing (`--analytical_place`; the packing that the routed experiments use is
APPack inside this flow and cannot be isolated from it), seed 1, 15 designs, with the census on (Stage 1, log-only):
arm `stock` (the Norns binary, option absent: byte-identical to stock, Stage-1 gate), arm `r3` (word, beta 4,
proposal count `attempted`, the round-3 behaviour), arm `r4` (word, beta 4, count `queued`, the headline). 45
census runs. Seeds do not change packing: checked on the Stage-5 runs, where the SHA-256 of the `.net` of every
(design, packing) is compared across the 3 VPR seeds; the paper states the outcome.

Pair classes. Each pair (a, b) of a logic CLB falls in exactly one class by the first rule that applies:
1. SC series-critical: a net n, local, driven by one of the two atoms and with the other among its sinks, where the
   pack-time criticality of that sink pin is >= theta_c (0.5).
2. SN series-noncritical: the same direct local net with pack-time criticality < 0.5.
3. SI shared-input: not 1 or 2; the two atoms are sinks of one common local net (fan-in sharing: the pin-width
   sharing of Peter's hypothesis).
4. OR orthogonal: not 1 to 3; the two atoms have the same round-2 word label, or are sinks of one common broadcast
   net (control-only sharing: enable, reset, select).
5. FL filler: none of the above.
The classes are exhaustive and disjoint by the precedence. None is empty by construction: SC, SN, SI need a net
and a criticality that the packer does not force; OR needs a word or a broadcast net; FL is what unrelated
clustering and leftovers give. Shares are over pairs (unweighted: primary). Reported weightings: (w1) pair weight
= min(pack-time atom criticality of a, of b); (w2) pair weight = min(rho_a, rho_b) with rho = the post-route
criticality of an atom: the maximum over the attributed paths containing it of arrival_ns / arrival_ns of path 1
(0 for atoms on no reported path). The words are 49% of LUTs only (round 2), so OR is a lower bound for the word
part; the broadcast part is label-free. Peter's illustration maps to: series-critical = SC; shared-input and
orthogonal = SI + OR; "filler / non-critical" = SN + FL. The same shares are also computed on 50 null packings
(Common definitions) for context.

Post-route data. The routed runs of the analytic start for `stock` and the headline (Stage 5, seeds 1 to 3, run
first, "Stage 2b") are given the Odin III attribution (see "Odin III attribution" below). Their `.net` SHA-256 must
equal that of the census run of the same packing, else the census join for that design is marked "packing differs"
and is not used for the routed weighting.

Near-critical paths. From the VPR setup report of the routed run (`--timing_report_npaths 1000`; the number the
report holds is recorded, and a design is marked "capped" when the report holds 1000 paths and the last is still
within the margin): a path is near-critical at margin m when arrival_ns >= (1 - m) * arrival_ns of path 1; m = 5% and
10% (both reported; 10% is the one the hypotheses use). k = their count per design. A path is split across CLBs if it
has at least one pair of consecutive path nodes that are both members and sit in different logic CLBs; its
crossings = the number of such pairs; the split fraction = crossings / member-member hops. Reasons for a crossing
(a in CLB X, b in CLB Y, C = the one of X, Y whose cluster was started first, u = the atom in the other): R1 u's
molecule was offered to C's cluster and failed the legalizer (pin feasibility `FEASIBLE` or intra-cluster routing
`ROUTE`), R2 u's molecule entered C's candidate queue and was not taken before C closed, R3 u's molecule was never
proposed to C, R0 no census record. First reason that applies in the order R1, R2, R3, R0.

H17a (Peter's 10 / 75 / 15), stock packing, seed 1, pair shares per design (unweighted), medians over the 15 designs
of the SC share s, of the SI + OR share t and of the SN + FL share f.
* Shape supported iff median s <= 0.25 AND median t >= 0.50 AND median s < median f < median t AND s < t on at
  least 12 of 15 designs.
* Shape not supported iff median t < 0.40 OR median s > 0.30.
* Numbers (his illustration literally): supported iff |median s - 0.10| <= 0.10 AND |median t - 0.75| <= 0.10 AND
  |median f - 0.15| <= 0.10; not supported iff any is further than 0.20 from its illustration value.
* Otherwise inconclusive. Both statuses are reported; "shape" is the primary one, "numbers" is the literal one.

H17b (does the headline packer change the series-critical share): per design d = SC share of `r4` minus `stock`;
two-sided Wilcoxon on d, plus the same for the SI share (Holm over the 2). Neither uses a word label.
* Supported (a change; the sign is reported) iff |median d| >= 0.02 and the Holm-adjusted p < 0.05 for SC.
* Not supported iff the 90% bootstrap interval of the mean d for SC lies inside [-0.01, 0.01].
* Otherwise inconclusive.

H17c (are near-critical edges kept together more than edges in general), stock packing: per design, crossing rate on
the member-member hops of the near-critical (10%) paths (crossings / hops, hops pooled) divided by the crossing
rate of all member-member net edges of the design (local nets, driver to sink atoms in different logic CLBs /
all such edges). Wilcoxon one-sided (ratio < 1) over designs with at least 20 hops.
* Supported iff the median ratio <= 0.80 and p < 0.05.
* Not supported iff the median ratio >= 1.00.
* Otherwise inconclusive.

H17d (does the packer do more than chance), stock packing: per design, (SC + SN share) minus the mean (SC + SN)
share of the 50 null packings. Wilcoxon one-sided (> 0).
* Supported iff median >= 0.05, p < 0.05 and positive on at least 12 of 15 designs.
* Not supported iff median < 0.01.
* Otherwise inconclusive.

Reported, not tested: class shares of `r3`, `r4` and the null; shares under w1 and w2; for each census arm the
fraction of molecules added by source (seed, connectivity and timing, affinity group, transitive, high fanout,
attraction group, RAM, unrelated), the mean gain terms by source, rejections per cluster by status, and the
round-3 versus fixed proposal hit rate; near-critical counts k and split counts per design at both margins with the
reason table; per-design sentence: "X% shared-input, Y% series-critical, Z% filler; k near-critical paths, m split
across CLBs".

## Stage 1 fixes and gates (before any experiment run)

Proposal counting: `add_molecule_to_pb_stats_candidates` returns whether the molecule was queued; the cap
(`feasible_block_array_size`, 30) counts queued molecules (new default); `--norns_proposal_count attempted` selects
the round-3 behaviour. Affinity join for mkDelayWorker32B (38 of 1620 word entries matched): cause found, fix in the
affinity builder or the reader, matched fraction before and after for all 15 designs and the 3 sources. Census
instrumentation (`--norns_pack_census <file>`), log-only.
Gates, heavy lock, seed 1, 15 designs, all byte comparisons of the `.net`:
(a) stock `vpr --pack` against the Norns `vpr --pack` with the option absent and with beta 0 (word file given);
(b) census on against census off, `--pack` and `--analytical_place`, for the stock arm and the headline arm;
(c) `--norns_proposal_count attempted` against the round-3 Stage-4 packing: the round-3 runs kept no `.net`, so the
reference is the previous binary (saved `/tmp/claude-1000/nr4-w/vpr-r3`, the round-3 fix binary) on the 45 headline
configs (3 sources, beta 4, seed 1, `--analytical_place`), `.net` and flat placement. No experiment run before all
pass; any failure is a stop-and-fix.

## RQ-N12: knowns from the dataset (Stage 3; no new VPR)

A relation is a "known" iff it holds in at least k = 12 of the 15 designs, and in every seed where the data have
several (no design counted if its sign flips between seeds), and beats its null at p < 0.05 (the test named per
relation), on data produced before Stage 5 or by the Stage-2b routed runs. Candidates (fixed here):
K1 module coherence: d_module (round 3 n11, same-module CLBs closer than net connectivity predicts) < 0 on all 3
seeds, Wilcoxon one-sided over designs where the relation is defined. K2 word coherence, the same for words.
K3 stock packing dilutes words: word plurality share <= 0.80 (H8 data) in >= 12 designs, null: the null packing's
share (the stock share exceeds the null's in all 15). K4 neighbour stability: the Jaccard of 4 nearest neighbours
across seed pairs exceeds the permuted null in >= 12 designs. K5 packing does not depend on the VPR seed: `.net`
identical across seeds in all counted designs (no test). K6 grid size is set by logic CLBs: the block type with the
highest `Device Utilization` in the final grid is the logic type in >= 12 designs (descriptive). K7 critical-path
constructs (Stage-2b attribution): the share of critical-path delay on adder, multiplier and memory atoms exceeds
their share of the design's atoms (Wilcoxon one-sided). K8 CPD tracks WL: Spearman between WL and CPD across seeds
within design is > 0 in >= 12 designs (descriptive). A relation that cannot be computed from the data present is
listed as "not evaluable" with the reason; no relation is added after the data are read except as a dated entry.
Output: a knowns table (relation, holds in n of N designs, seeds, null, p, known yes/no).

## RQ-N13: hierarchy versus chip size (Stage 4)

Hierarchy measures per design from the provenance module paths of the logic atoms: M = number of distinct module
instance paths, D = depth (maximum path length), A_med = median atoms per module, and a per-level Rent exponent p_l
(least squares of log(external nets) on log(atoms) over the modules of one hierarchy level, levels with >= 4
modules; designs with a single module have none). Size measures: grid area (width x height), logic CLB count,
minimum channel width W (VPR's), for `stock` and `r4` packings, analytic start, mean over seeds. Also the design
size S = number of logic atoms. n = 15 small designs (the paper says so); a medium VTR design is not added unless
the peak RSS measured on the current runs extrapolates below 60% of the 23 GB VM, in which case it is a labelled
extra and not part of the tests. Tests (Spearman, two-sided, alpha 0.05, Holm over the 2 packings x 3 size
measures = 6 tests, within H13a; likewise for H13b):
H13a: log M correlates with log grid area: supported iff rho >= 0.6 and Holm p < 0.05 for the grid area under both
packings; not supported iff rho < 0.3 under both; otherwise inconclusive.
H13b: hierarchy relates to chip size beyond design size: the partial Spearman of log M and log grid area controlling
for log S (rank residuals of each on log S): supported iff |rho_partial| >= 0.5 and p < 0.05 under both packings;
not supported iff |rho_partial| < 0.3 under both; otherwise inconclusive.
H13c (packer effect): the grid area ratio `r4` / `stock` is related to M: Spearman of the ratio with log M;
supported iff |rho| >= 0.5 and p < 0.05; not supported iff |rho| < 0.3; otherwise inconclusive.
Designs with M = 1 stay in H13a, H13b (their M = 1) and are excluded from per-level Rent statistics (reported).

## RQ-N14, N15, N16 with CPD everywhere (Stage 5)

Arms per design: packing in {`stock`, `norns` = headline} x start in {`analytic`, `wordseed`, `stagebit`}; VPR
seeds 1, 2, 3; 18 runs per design, 270 in all (the analytic arms are Stage 2b and run first). `wordseed` = the round-2
`words_partial` seed rebuilt on the packing and flat placement of the analytic run of the same packing and seed
(round-3 procedure). Metrics: routed WL, minimum channel width, CPD (VPR's `Final critical path delay`, and the
attribution's `cpd_ns`; they must agree), logic CLB count, grid, pack and flow runtime. A run's report is
`report_timing.setup.rpt` with 1000 paths. Failed runs are listed and not replaced.

N16 stage x bit seed (`stagebit`), construction. Inputs: the packing's `.net` flat placement
(`final.flat_place`: atom to CLB) and the analytic run's `initial.place` (slots, positions). Partial like `words_partial`:
only CLBs that get a position below are moved; every other CLB keeps its analytic position.
1. Graph: nodes are the atoms of the BLIF; an edge goes from a net's driver to each sink; clock nets excluded.
2. Stage: back edges are removed by a depth-first search that starts from the primary inputs in BLIF order (then
the remaining atoms in BLIF order) following nets in BLIF order; stage(v) = max over in-edges (u, v) of
stage(u) + 1 if u is an FF, else stage(u); primary inputs and atoms without in-edges have stage 0.
3. CLB stage = the lower median of the stages of its member atoms. CLB bit = the lower median of the word bits of
its member atoms that have a round-2 word bit (`words/members.json` `bit`), if at least 1/3 of the members have
one; otherwise the CLB has no bit.
4. Control CLBs: logic CLBs that hold the driver of a broadcast net (fanout > 32).
5. Targets. Let S = the maximum CLB stage, B = the maximum CLB bit over the design, X and Y the sorted lists of
x and y coordinates of the logic slots of the grid. A CLB with a stage and a bit goes to column X[round(stage/S
(nx-1))] and row Y[round(bit/B (ny-1))] (S or B zero: the middle index); a control CLB goes to the grid centre (the
middle column and row); CLBs without a bit and not control are not moved.
6. Legalisation: moved CLBs in order (stage, bit, CLB name) each take the nearest free logic slot by Manhattan
distance to the target (ties: lower x, then y, then sub-block); the slots freed by the moved CLBs and not taken go
to nothing; the unmoved CLBs keep their slot unless a moved CLB took it, in which case they take the nearest free
logic slot to it by the same rule.
Fallback: if S = 0 or fewer than 8 CLBs have a stage and a bit, the design has no `stagebit` arm (listed; the rule
for H16 then runs on the designs that have one).

H14 (clustering impact with CPD): `norns` against `stock`, analytic start. Per design and metric in {WL, channel
width, CPD}: geometric mean over seeds of the ratio. Per metric:
* Supported (better) iff the geomean ratio <= 0.99 and one-sided (ratio < 1) Wilcoxon p < 0.05 after Holm over the 3
  metrics.
* Not supported iff the geomean ratio >= 1.00 or the 90% bootstrap interval lies inside [0.98, 1.02].
* Otherwise inconclusive. Round 3 saw a worse WL (1.03) for the word source, so "not supported" is the expected
  outcome for WL; this is stated before the data.

H16 (stage x bit floorplan seed): `stagebit` against `analytic`, within each packing; metric in {WL, channel width,
CPD}; 6 tests (2 packings x 3 metrics), Holm over the 6, otherwise the H14 rule. Reported, not tested: `stagebit`
against `wordseed`; `wordseed` against `analytic` (H9c replication on the stock and the headline packing).

H15 (timing from provenance), Stage-2b runs, stock packing, analytic start, seed 1, attribution `spans`. RTL-level
depth estimate per HDL statement (labelled heuristic, text only): for the source line of a span, d_own = the sum
over the operator tokens of its right-hand side of weights (+, -: 2; *: 4; <<, >>: 1; &, |, ^, ~^, ~, !, &&, ||: 1;
comparisons ==, !=, <, >, <=, >= and ?: : 1; concatenation and selects: 0), and d_chain = d_own + max d_chain over
the combinational (`assign` or blocking `=`) statements in the same file that assign an identifier on its right-hand
side (depth-first, a statement already on the stack contributes 0; registers `<=` end a chain). The estimate is
a text heuristic, not the Odin III netlist; its limit is stated in the paper. For each design: Spearman rho between
d_chain and the span's `critical_delay_ns` over the spans on the reported paths (>= 8 spans required, else the design is
dropped from the test), and the overlap of the top-5 spans by d_chain with the top-5 by `critical_delay_ns`
(compared with the expected overlap 25 / n_spans).
* Supported iff the median rho >= 0.30, the one-sided (rho > 0) Wilcoxon p < 0.05 and rho > 0 on at least 80% of the
  designs with data.
* Not supported iff the median rho < 0.10.
* Otherwise inconclusive.

Wall-time guard: the estimate is made from round-3 `flow_s` (4.2 h for 900 runs, about 17 s per run on average) before
the batch; if the estimated VPR time of Stage 5 exceeds 8 h, the 8 checkpoint designs run first, are committed,
checkpointed in the Result, and then the rest follow (no scope trimmed for time).

## Odin III attribution (dependency)

The attribution is the Odin III V1.1.1 tool (`tools/flow/timing_attr.py`, odin3 main 0b90fff9). It joins VPR atoms to
the provenance names through a pair of BLIFs (a short-name BLIF that VPR reads and a provenance-name BLIF) and
an optional `write_json --odin3` netlist. The Norns BLIFs already carry provenance names (VPR atoms are named by
them), so `odin3-timing` cannot be called on a Norns run directory as is (it needs the pair and
`timing/inputs.json`). Workaround, labelled, in `scripts/timing4.py` only: the script builds the name map from the
Norns BLIF itself (every provenance-named net maps to its own hierarchy, file, line), reads VPR's
`report_timing.setup.rpt`, and calls the V1.1.1 library functions (`build_report`, `Resolver`) unchanged. It does
not use the JSON netlist (port-named atoms stay "unmatched" or "port"). Coverage is reported. The odin3 checkout is
never edited. What the tool cannot do is listed in the Result.

## Entries after this point

### Entry 2026-10-25 (after the affinity-join check, before any gate, census or arm result): construction details

No rule above is changed; these fix what the text above leaves open, found while writing the code. Timing: the join check
(`round4.py join`, pack-only runs that read the `Norns affinity:` matched count) ran before this entry; it measured
matched fractions only. No gate result, no census and no arm run existed when this entry was written.

* N16, items 5 and 6 (the old text stays; this is what the code does): the moved CLBs are the logic CLBs that are not in
  a carry chain and that have a stage and a bit (or are control). They permute among the slots they occupy in the analytic
  placement (their own slot pool), so the placement stays legal without touching any other CLB; X and Y are the sorted
  distinct x and y of that pool (not of the whole grid). Carry-chain CLBs never move (VPR places chains as macros).
  Each moved CLB, in the order (stage, bit, name), takes the free pool slot nearest (Manhattan) to its target; ties go to
  the lower (x, y, sub-block, layer). A CLB with a stage but no bit and not control is not moved (as written).
* The affinity files of round 4 (`runs/<d>/r4/affinity/`) list the same atoms as round 3's minus buffer LUTs that VPR
  absorbs (one input, table `1 1`, including the ones in front of a primary output); group ids come from the full round-3
  label set, so they are unchanged. Stage-1 gate (c) also compares the packing with the round-3 file against the one with
  the round-4 file. The join result (before and after, 15 designs, 3 sources) is `data/analysis/r4-join.json`.
* Runs: census runs are `--analytical_place --seed 1` (no route) with `--write_flat_place`; arm runs are the default
  routed flow with `--timing_report_npaths 1000` (a report option; the stock arm's WL, W and CPD must equal round 3's
  stock values at the same seed, which is checked and reported). The stock arm of Stage 5 runs the stock `vpr`.
* Stage 5 starts `wordseed` and `stagebit` are built from the analytic run of the same packing and seed, so Stage 2b (the
  analytic runs) comes first. All run records are `data/<d>/r4runs.jsonl`.
