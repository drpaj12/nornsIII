# Norns round 7 data protocol: the placement corpus and hindsight clustering (written 2026-10-26 13:50 EDT, before any round-7 run)

This file is committed and pushed before any round-7 VPR run. Its commit SHA is the "rule provenance" of round 7 (quoted in
the paper). A rule changes only by a NEW dated entry at the end of this file that keeps the old rule. There are no
hypotheses with statuses in this round. The ONE quantity defined in advance is the hindsight gap per design (below). Every other
analysis is exploratory, is dated when it is added, and changes nothing that is defined here.

Truthful state at the time of writing. Rounds 1 to 6 data exist and were read: they fix the architecture, the flow, the run
speeds (the time estimate below) and the census tooling. The Odin III main checkout (2d521f09, ABI 7, `libodin3.so.1.1.1`
built 2026-10-26 13:35) loads under `scripts/env.sh` with the default `ODIN3_PLUGIN` (checked: `import odin3; odin3.Odin3()`
succeeds); the round-6 ABI-6 override is dropped. Round 7 re-uses the synthesised BLIFs of rounds 1 to 5 (`runs/<d>/netlist/<d>.blif`,
Odin III provenance names) and does NOT re-synthesise. Before this commit one probe was run, and only to verify two VPR
options and the memory use of the largest design: a single ch_intrinsics run with `--route_file /dev/null` and one stereovision2
run under `/usr/bin/time -v` (outputs in a scratch directory, not data of this round). No other round-7 run exists.

Purpose (hub docs/purpose.md): Norns, questions **N Q2.4** (mined from many placements linked to the HDL: which HDL
relations, such as word, bit index, statement and module, predict which atoms sit together in good placements, and where
stock packing disagrees) and **N Q1.7** (on real designs, how far is the VPR packer from a best-known clustering made with
hindsight from good placements, and how much would LUT duplication add). Measures: area (CLB count, minimum channel width),
speed (critical-path delay, CPD), wirelength (WL).

Peter (2026-10-26), verbatim for the research-log appendix: "In the Norns questions, I really think we should have a bunch of
VTR placements that generate data that we then analyze with the qeustion what might be better clustering and intitialization -
every idea we've had is in the other direction - hypothesis, test, not really better - it's like my data mining Journal paper
with Gharibian, Shannon and Wilton". (His spelling kept. The paper is Gharibian, Shannon and Jamieson, TRETS 2013, and FPL
2014; the author list is checked against `docs/paper/joined.bib` and the primary source in Stage 4.)

Why this round is different: rounds 1 to 6 each tested an idea and found little. Round 7 tests nothing in advance. It builds a
corpus, measures one yardstick, and reports what the data shows.

## Common definitions

* Architecture and flow: VTR 3c9a4d23b2 (`packer/VTR_COMMIT`), `k6_frac_N10_frac_chain_mem32K_40nm`. In this VTR the default
  flow (no `--pack/--place/--route` stage flag) is analytical placement (`lp-b2b`, APPack as the full legalizer), then the
  annealing refinement, then routing with the minimum-channel-width search; the logs say `Analytical Placement took`. Flags of
  every run: `--seed s --timing_report_npaths 200 --write_initial_place_file ... --write_flat_place ...` plus
  `--route_file /dev/null` only if the probe shows it works (the choice and the probe result are in the Stage-1 entry). The
  binary is the Norns VPR (`$NORNS_VPR`); with no affinity file and beta 0 its `.net` equals the stock VPR `.net` (round-3 gate
  and round-4 gate (b), both passed), so "stock" runs use it too and write the packer census (`--norns_pack_census`, log-only,
  round-4 gate (b)). VPR's analytical placement is the default flow, so the "analytical-placement hindsight start" the brief
  mentions is the stock start itself; there is no separate arm (APPack clusters from atom positions already, and its
  clustering is the stock clustering).
* Logic CLB, member atoms (LUT, FF, adder), pads, hard blocks: as round 4. Atoms are the VPR atoms of the BLIF
  (`affinity.logic_atoms(design, True)`: buffers absorbed and dead logic swept as VPR does).
* Seeds: VPR `--seed` 1 to 10 for every arm and design. Designs are run smallest first (by logic CLBs in the stock seed-1 run
  of earlier rounds).
* Objective of a run: `WL x CPD` (routed total wirelength times the final critical-path delay, both from the VPR log, WL in
  routing-segment units as the log reports it). A lower value is better. The best run of a set of runs is the one with the lowest
  objective, ties to the lowest seed.
* Pair classes: the N17 classes of round 4 (SC series-critical, SN series-noncritical, SI shared-input, OR orthogonal, FL
  filler) from `r4census.classify` (series nets of fanout <= 32, `THETA_C` = 0.5, criticality = the pack-time criticality of
  the census, `P` records of the stock seed-1 census); definitions in `docs/plan/round4.md`. They are class labels of a pair,
  computed once per design from the BLIF and the seed-1 stock census.
* HDL relations of an atom pair (a, b), from the provenance name `path/leaf@file:line` and the word file
  `runs/<d>/words/members.json` (round 2):
  * `same_word`: both have a word and the words are equal;
  * `same_bit`: both have a bit index and the indices are equal (any word);
  * `same_word_bit`: same word and same bit index (a bit slice of one word);
  * `bit_delta`: `|bit_a - bit_b|` when the words are equal, else undefined;
  * `same_stmt`: equal `file:line` (the construct the atom came from; file reduced to its base name);
  * `same_inst_d` for depth d = 1, 2, 3, ...: the first d components of the provenance path (the instance path) are equal and
    both paths have >= d components; `same_inst_full` = the whole path is equal. The provenance path is an instance path, so
    "module" in rounds 3 and 4 is `same_inst_full`; module type names are not recorded in the BLIF names (stated limit);
  * `carry_nb`: adder atoms joined by a carry link (cout to cin) in the BLIF.
* Statistics: bootstrap = 10000 resamples of the unit stated, seed 20261026, percentile 95% interval; designs are the unit
  across designs, seeds the unit within a design. No hypothesis tests with statuses.

## Stage 1: corpus

Design set (22 + 12). Main set: the 15 VTR Verilog benchmarks of rounds 1 to 4, ordered by `nornlib.DESIGN_ORDER`:
ch_intrinsics, stereovision3, diffeq2, diffeq1, mkPktMerge, raygentop, sha, boundtop, mkSMAdapter4B, or1200, stereovision0,
stereovision1, mkDelayWorker32B, stereovision2, blob_merge (the list in `scripts/nornlib.py`; the earlier round scripts list
no others; the `runs/` directories blob_merge ... stereovision3 are exactly these). Calibration set (known optimum, round 5):
the netlist-level constructions `n5_<topology>_<style>_<B>` for topology in {mesh, tree}, style in {dp, ctl}, B in {16, 64, 256}
(12 designs, those that round 5 KEPT; if one was not kept it is listed and dropped). Chain and random topologies are not used
(round 5 found no gap there). Calibration designs have no Verilog; their labels are the block index of round 5.

Arms and runs, per design and per seed s = 1..10:
* `stock`: Norns VPR, no affinity file, census on. 10 runs.
* `known` (calibration designs only): the round-5 known arm, affinity file = the block of each atom, `--norns_affinity_weight 100
  --norns_proposal_count queued` (exactly `r5.aff_flags(design, "known")`). 10 runs.
* `h1`, `h2`, ... (up to `h5`): the hindsight arms of Stage 2, same flags as `stock` plus the affinity file of the round's
  clustering (weight 100, `queued`) and no census. 10 runs per round.

Estimate (made from round-4 `flow_s` of seed 1; Norns packer census adds < 5%): the 15 main designs sum to about 245 s of VPR per seed
and arm (stereovision2 108 s of it), so one 10-seed arm costs about 41 min, the stock arm plus up to five hindsight rounds about
4.1 h. The 12 calibration designs sum to about 22 s per seed and arm: 7 arms x 10 seeds = 26 min. Total at most about 4.6 h
of VPR, below the 12 h bound, so no design is cut. If the observed time makes the total pass 12 h the largest design(s) are
cut, the cut is committed and stated. Disk and memory (probe, 2026-10-26 13:55 EDT, one stereovision2 run, seed 1, the flags above plus the census): wall 113 s, peak
RSS 1.30 GB (bound 13.8 GB, so no design is cut for memory), raw output of the run directory 237 MB (census 53 MB, `.net` 94 MB,
`.net.post_routing` 94 MB, timing reports 6 MB). `--route_file /dev/null` works (probe on ch_intrinsics: rc 0, no `.route`, same
WL 1461 as the round-4 run). Sixty stereovision2 runs would write 14 GB raw, and VPR offers no switch for `.net.post_routing`, so
the raw VPR working directories are placed in a scratch directory `/tmp/claude-1000/nr7-XXXX` (a fresh `mktemp -d`; its path is written
to `runs/r7/scratch_path.txt`) and stay there (nothing is deleted); `runs/r7` receives, per run, only the kept files: the `.net` and
`final.flat_place` as `.gz`, `<d>.place`, `vpr.out`, `metrics.json`, the parsed timing report (`paths.json.gz`), the parsed census
(`pincrit.tsv.gz`, stock arm), so `runs/r7` is far below the 15 GB bound (expected < 3 GB) while the raw outputs remain on disk in
scratch (expected 25 GB on the 857 GB free disk; stated in the Result).

Per-run record (`runs/r7/<d>/<arm>.s<seed>/`, files `vpr.out`, `<d>.net.gz`, `<d>.place`, `final.flat_place.gz`, `paths.json.gz`, `pincrit.tsv.gz`, `metrics.json`;
the stdlib+numpy parsed forms below are built from these by `scripts/r7corpus.py`; numpy 1.x/2.x of the Loki venv `$NR_PY`,
no pandas, no matplotlib, the paper figures are drawn as TikZ/pgfplots from data files by `write_round7.py`):
* per atom (`atoms.tsv.gz`, one row per VPR atom of logic CLBs, plus pad/hard-block atoms with `clb = -1`): atom id (index in
  the design's atom table `atoms.tsv`), CLB id of the run, x, y, pack-time criticality (the maximum `P` criticality over the
  atom's input pins, stock arm only, else blank), post-route criticality `pcrit` (below), post-route slack of the worst
  reported path through the atom, blank if no reported path goes through the atom. The design atom table (`runs/r7/<d>/atoms.tsv`)
  holds, per atom: operator kind (lut, ff, adder), the provenance chain split into `construct` (`file:line`), the instance path
  (`/`-joined components), `word`, `bit`, `bus`, `leaf`, and the N17 relations' inputs.
* per pair (`pairs.npz` per design, built once from all runs of the design): the pair universe = (i) every pair of atoms that
  share a logic CLB in any run of the design, (ii) every pair connected by a net of fanout <= 32 (series or shared input) that
  never shared a CLB, taken as a fixed-seed random sample of at most 1 000 000 such pairs, (iii) a fixed-seed uniform random
  sample of 200 000 atom pairs (seed 20261026). Columns: atom ids a < b, N17 class, the HDL relations above, `n_co_stock` =
  number of the 10 stock runs in which the pair shares a CLB, `dist_stock[10]` = Manhattan distance in CLB coordinates in each
  stock run, `co_h[round]` = co-CLB flag in the hindsight run of the same seed per round, `co_hind` = co-CLB in the best
  hindsight run, `sampled` = which of (i)-(iii) it came from. Universe (i) and (iii) are exact for the first part, sampled for
  the rest; the sample sizes are written to `data/r7/corpus.json`.
* per net (`nets.npz`): net id, driver atom, fanout, for each stock run the number of distinct CLBs holding its pins and the
  post-route criticality of the driver, and `dup_cand` = 1 if the driver is a single-LUT driver in the Stage-2 sense.

Path parsing and criticality. `report_timing.setup.rpt` lists the worst 200 paths of the run. A node line is
`<atom name>.<port>[<index>] (<type>)  <incr>  <path>`; the atom is the text before the last `.`. For a path p, `arrival(p)` is its
`data arrival time`. Post-route criticality of an atom: `pcrit = max over reported paths through the atom of arrival(p) / CPD`
(CPD = the max arrival over the reported paths = the run's CPD); atoms on no reported path get `pcrit = 0`. The coverage (share of
logic atoms on at least one reported path) is written per run. Net criticality for weighting = `pcrit` of the net's driver atom.
This is path based and is an under-approximation of true criticality for nets off the 200 reported paths (they get 0); stated.

Atlas export (for the Wyrd placement atlas lane), `runs/r7/<d>/atlas/<arm>.s<seed>.json.gz`, one JSON per run:
`{"design", "arm", "seed", "grid": [w, h], "cpd_ns", "wirelength", "chan_width", "clbs": [{"id", "type": "clb|io|mem|mult",
"x", "y", "atoms": [index into "atoms"]}], "atoms": [{"name" (base-name form), "kind", "class" (N17 class of the atom's strongest
pair partner within the CLB, SC>SN>SI>OR>FL), "construct", "inst", "word", "bit", "crit" (pack-time), "pcrit" (post-route)}]}`.
A copy for ch_intrinsics, diffeq1, stereovision3 (seed 1, stock and the best hindsight round) is committed under
`data/r7/atlas/`; the rest stay in `runs/`.

## Stage 2: hindsight clustering (N Q1.7)

Procedure, exactly. Input: a design, the 10 stock runs. Let C0 be the stock clustering (a different one per seed; "stock" is
always the seed-matched stock run).
1. Round k = 1: take the best stock run (lowest objective, ties lowest seed); call its placement P1 (`final.flat_place`, CLB
   coordinates, hard blocks and pads included) and its path criticalities `pcrit`.
2. Re-cluster (`r7lib.recluster`): units are molecules = a LUT with the FF it alone drives (the FF's only input is the LUT's
   output and the LUT drives only that FF), lone LUTs and lone FFs; adders, hard blocks, pads and every CLB that holds an adder
   stay as they are (frozen: their atoms are not moved and nothing is moved into them). The CLB coordinates of P1 are fixed. The
   cost of an assignment is `sum over nets n (fanout <= 32, clock excluded) of w_n * HPWL(n)`, `HPWL` = half perimeter of the
   bounding box of the pins' CLB coordinates (pads and hard blocks at their P1 coordinates; two pins in one CLB at the same
   point), `w_n = 1 + 4 * pcrit(driver of n)` (so a critical net counts up to 5 times; the constant 4 is fixed here). Local
   search (deterministic, seed 20261026): repeat sweeps over the units in a fixed random order; for each unit try to move it to each
   non-frozen logic CLB within Manhattan distance <= 2 of its CLB in P1 that has capacity, and (if the target is full) to swap it
   with one unit there; apply the move or swap with the largest cost decrease if the decrease is > 1e-9; stop when a sweep makes no
   move or after 30 sweeps. Capacity (an approximation of the architecture's CLB legality, checked by VPR below): per CLB
   <= 10 LUTs, <= 20 FFs, <= 40 distinct nets entering from outside, <= 20 nets leaving to other CLBs or pads; a move that
   breaks any of these in the target (or breaks them further in the source) is not allowed. The result is a clustering C1.
3. C1 is written as an affinity file (atom, group id; frozen CLBs keep their group) and handed to the same Norns VPR with weight 100
   and `queued` (the round-5 known mechanism, which makes the packer pull the labelled atoms together without writing a `.net`
   by hand; VPR's packer is the legality check, so every hindsight clustering is a legal `.net` by construction). The clustering
   VPR actually produces is read back from `final.flat_place` and is what is measured and reported ("realised"). The fidelity is
   the share of C1's groups of >= 2 atoms whose atoms the packer put into one CLB; it is reported per design and round, and a
   fidelity < 0.5 on a design is stated next to its gap.
4. Run the 10 seeds of the arm `h1` (same placer, same router, same seeds, same flags as `stock`).
5. Round k+1: take the best run among the 10 runs of arm `h<k>` (lowest objective), re-cluster from its placement as in step 2
   with its realised clustering as the start, and run `h<k+1>`. Stop after round K = 5, or earlier when the median over the 10
   seeds of the objective of `h<k+1>` is not at least 1% lower than the median of the best earlier arm (stock included); the
   stopping arm is not used as the answer when it is worse. The fixed point = the arm with the lowest median objective
   (stock, h1, ... ), called the hindsight arm `H`. If `H` = stock the design shows no gap by this procedure.

The hindsight gap per design (the one number fixed in advance). For metric m in {WL, CPD, CLB, W} (CLB = the number of
logic CLBs of the run, W = minimum routed channel width) and seed s: `gap_m(s) = m(stock, s) / m(H, s)` (so > 1 means stock is
worse). Per design: the geometric mean over the 10 seeds and its bootstrap 95% interval over the seeds. Also reported:
the same gap for the first round `h1` only (less selected), the fidelity, and the objective gap. Bias stated in
advance: `H` and the source run are chosen by the same objective on the same seeds, and the source seed's own stock run is one of
the ten, so the gap is a best-known gap (optimistic by selection), not an unbiased estimate; the `h1` gap, which has no round
selection, is reported beside it, and seed 1..10 stock runs are not used for anything else after being used for the choice.

Calibration on the constructions. For each calibration design compute the same procedure, and the `known` arm. Recovery per
metric m (WL, CPD, CLB): `(ln m(stock) - ln m(H)) / (ln m(stock) - ln m(known))` per seed, the median over seeds and its
bootstrap interval, per design and pooled by cell (mesh/tree, dp/ctl). A cell whose known arm is not better than stock (denominator
< 0.01) is reported "no gap to recover" and not given a recovery. Round 5 found about 22% WL, 7% CLB and 9% CPD gap on mesh
and tree; the table reports the measured stock-versus-known gap of this round next to the recovery.

LUT duplication (after Schabas and Brown, FPGA 2003; reference to be added to `docs/paper/joined.bib` and checked against the
primary source in Stage 4; nothing is built). Per design and per run, in the stock arm and in `H`: a duplication candidate is a
LUT atom (kind lut, not an adder, FF, or hard block) whose output net has sinks in at least two distinct CLBs (the CLB of the driver
counts when it holds a sink). Counted: the number of candidates, their share of all LUTs of the design, the share whose driver
has `pcrit >= 0.95` (near-critical at 5% of CPD) and `>= 0.90` (10%), the number of reported paths that contain a hop out of a
candidate to a different CLB, and an upper estimate of the delay a copy could save: for each reported path p, `arr'(p) = arr(p) -
(sum of the incr delays of the hops of p that leave a candidate to a sink in another CLB)` (the hops become free: a deliberately
optimistic bound), and `CPD'` = the maximum of `arr'(p)` over the reported paths and the smallest reported arrival (the
bound for paths beyond the report); saved = CPD - CPD'. Per design the table gives the median over the stock seeds and the
value for `H`. If saved/CPD is large on near-critical paths the paper says duplication is worth building; it is not built.

## Stage 3: first mining (exploratory, all labelled so)

Every analysis below is exploratory, dated, and changes nothing above. Every "found" association has a null: the same statistic
with the HDL labels shuffled within the design (200 shuffles for the per-design statistics, 20 for the model fits; the shuffle
permutes the atom to (word, bit, construct, instance) assignment over the design's atoms, so the label frequencies and net
structure are kept). Results are given with the null's mean and 95% range and the observed value's rank in it.
* (a) Prediction of co-location. Target 1: the pair shares a CLB in the best hindsight run `H` (seed of the source run). Target 2:
  mean Manhattan CLB distance over the 5 best stock runs (lowest objective). Models: logistic regression (target 1) and ridge
  regression (target 2), scikit-learn from the Loki venv, features standardised. Baseline features (no HDL): log(1+number of shared
  nets), series flag, series criticality, shared-input flag, `pcrit` of the two atoms (min and max), fanout of the shared nets
  (min), kind pair (lut/ff/adder). Full model: baseline plus the HDL relations. Held-out designs: leave one DESIGN out (train on
  the other 14 designs' pairs, subsampled to <= 200 000 per design with a fixed seed), report AUC (target 1) and R2 (target 2) per
  held-out design, the paired difference full minus baseline, its bootstrap interval over designs, and the null difference (labels
  shuffled in the held-out and training designs).
* (b) Disagreement pairs: pairs co-CLB in `H` and not in the seed-matched stock run (and the reverse). Per HDL relation: the share of
  disagreement pairs that have the relation against the share among pairs of the universe, with the label-shuffled null.
* (c) Stability across seeds: for each pair of the universe, the fraction of the 10 stock seeds in which it shares a CLB;
  distribution per HDL relation and per N17 class (the stable "knowns", N Q2.2).
* (d) Bit-level hint: does `same_bit` or `carry_nb` (or `same_word_bit`) raise the log-odds of hindsight co-location beyond the
  baseline features (coefficient with bootstrap interval over designs, and the AUC gain, each against its shuffled null).
* (e) Table XI check (round 3 H11 `tab:r3status`): the statistic of H11 recomputed on the round-7 stock runs for each relation and
  level of the chain (`same_word`, `same_bit`, `same_word_bit`, `same_stmt`, `same_inst_d` for d = 1, 2, 3, `same_inst_full`):
  `d_r` = the stratified mean distance difference (related minus unrelated pairs within each strata of the direct net count
  n_ij in {0, 1, 2-3, >= 4}, weighted by the related pairs per stratum), as a fraction of the mean distance of the unrelated
  pairs, averaged over the 10 stock seeds; the null as above. Reported per level: median over designs, the number of designs with
  `d_r < 0`, and whether the earlier "closer than nets predict" result holds at that level. Pairs are the universe above, not the
  round-3 CLB-pair sample (stated); a level with a relation that covers >= 95% of the sampled pairs in a design is reported "relation
  undefined" for that design.
* Static figures for the paper (TikZ/pgfplots in `norns.tex`, data files under `docs/paper/`): class shares per design (N17 shares of
  co-CLB pairs in stock and `H`); distance distribution per HDL relation; the gap per design.

## Summaries the paper reports (all generated by `scripts/write_round7.py`, no hand-typed numbers)

Corpus table (designs, seeds, runs, failures, committed and local disk); hindsight gap table (WL, CPD, CLB, W gap with intervals,
rounds used, fidelity); calibration table (stock-versus-known and recovery); duplication table; the mining results (a) to (e) with
their nulls; what the round can and cannot claim (best-known, not optimal; one architecture; VTR designs only; the AP/APPack
default flow). A research-log entry with Peter's quote; the RQ table rows for N Q1.7 and N Q2.4.

## Stop rules and failures

* One VPR at a time, the heavy lock (`flock -x /tmp/claude-1000/odin3-heavy.lock`) taken PER RUN. Never kill a job; wait for the lock.
* A run that fails (rc != 0 or the 7200 s timeout) is recorded with its error and is not retried more than once; a design with fewer
  than 8 of 10 successful stock seeds is dropped from the gap table and listed; for hindsight arms the same rule applies to the arm.
* A design whose clustering fidelity is < 0.5 in every round is reported with its gap marked "not realised".
* Stop the batch and report if the total VPR time would pass 12 h (cut the largest designs first), if runs/r7 would pass 15 GB, or
  if the lock cannot be taken for more than 6 h.
* No files are deleted by any script of this round (no rm, no rmtree, no unlink); the scripts only add files. The run directories of
  a failed attempt stay in `runs/r7/`.
* Round-7 data live in `runs/r7/` (not committed). Committed: this file, the scripts, the tests, `data/r7/*.json` summaries, the
  committed atlas examples, the paper. The committed data size is stated in the Result.

## Entries after the first commit

(none yet)

