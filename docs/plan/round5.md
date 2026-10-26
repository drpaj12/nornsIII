# Norns round 5 protocol: known-optimal clustering benchmarks (written 2026-10-26, before any round-5 benchmark or run)

This file is committed and pushed before any benchmark is generated and before any VPR run of round 5. Its commit
SHA is the "rule provenance" of round 5 (quoted in the paper). A rule may change only by a NEW dated entry at the
end of this file that keeps the old rule; the paper then reports the result under both. Nothing was generated,
synthesised or run for round 5 before this commit; the round-5 code (generator, runner, statistics) is written
after it. The rules below were fixed without any round-5 data. Rounds 1 to 4 data exist and were read; they fix the
architecture, the flow, the run speed (for the time estimate) and the round-4 headline configuration.

Purpose (hub docs/purpose.md): Norns N3 (does clustering by higher-level ideas improve placement) and N1, question
**N Q1.6**: on designs with a known optimal clustering, how far are the VPR packer and the Norns HDL-aware packer
from it, and how does the gap grow with size? Measures: area (CLB count, grid, minimum channel width), speed
(critical-path delay, CPD), wirelength (WL).

Peter (2026-10-25/26), verbatim for the paper's research-log appendix:

> "Tpeko tells us what is still possible, so from a clustering perspective it's an interesting approach."

> "So, the rose and Thomas just taught me stuff. We could build it again, but it's just insight."

Background: Cong, Romesis and Xie, "Optimality and Stability Study of Timing-Driven Placement Algorithms", ICCAD 2003
(`Cong03tpeko`): placement problems with a known optimal answer, to measure how far placers are from it. Rounds 3 and 4
found that HDL structure is visible (purity 0.63 against a null of 0.20) but that HDL-aware packing did not beat stock
VPR (WL 1.033, CPD 0.996). Without a known optimum we cannot tell "no room on these designs" from "a weak idea".
Round 5 builds the yardstick. Reasoning: `~/odin3-ws/claude_thoughts.md`, section of 2026-10-25 and its addenda.

What "optimal" means here, and its limits (stated in the paper): the optimum is a CLUSTERING optimum by construction.
Each generated block fills exactly one CLB (all 10 logic elements of the architecture) and has a designed, small set of
external nets. The block partition therefore reaches the CLB-count lower bound exactly and has a known cut (number of
nets that leave a block). It is NOT a proven minimum-cut partition, NOT a proven placement optimum, and not a proven
timing optimum. The "known-optimum arm" below is the clustering handed to the same placer and router; its WL, W and CPD
are what VPR achieves from that clustering, not a bound. Gaps are therefore gaps to a good, known reference, and a
packer can in principle beat the reference in cut, WL or CPD (the ratios may fall below 1; every status below can
come out either way).

## Common definitions

* Architecture and flow: VTR 3c9a4d23b2 (`packer/VTR_COMMIT`), `k6_frac_N10_frac_chain_mem32K_40nm` (as rounds 1 to
  4). Read from the architecture file (`<pb_type name="clb">`): N = 10 fracturable logic elements, each with one 6-LUT
  (or two 5-LUTs with shared inputs) and 2 flip-flops; K = 6; 40 cluster input pins, 20 cluster output pins, 1 clock.
  Default (analytical-placement) flow, `--seed s`, minimum channel width search (no `--route_chan_width`), exactly the
  flag set of round 4 `arm_run` (`--timing_report_npaths 100`, `--write_initial_place_file`, `--write_flat_place`).
  One VPR at a time under the heavy lock, the lock taken per run.
* Synthesis: the Odin III script of rounds 1 to 4 (`nornlib.odin_script`: `read_verilog --nolatches --vtr-compat;
  proc; fsm; opt; flatten; opt -full; wreduce; hardmap; lower; abc --lut 6; write_blif --vtr --lut-k 6 --name-style
  provenance`), Odin III main (v1.1.1) unchanged.
* Logic CLB, member atoms (LUT, FF, adder), pads: as round 4. A cluster is a logic CLB; each pad (input, output) is
  its own cluster.
* Cut of a clustering: the number of non-clock nets (BLIF nets, driver to sinks, constants excluded) whose pins lie in
  more than one cluster. The designed cut is computed from the generator's spec; the measured cut of the generator's
  blocks from the synthesised BLIF and the block labels; the cut of a packing from `final.flat_place` (atom to CLB).
* Block label of an atom: the first path component of its provenance name (`b<k>/leaf@file:line`) that has the form
  `b<k>`; atoms without one are unlabeled.
* Purity against the known blocks: sum over logic CLBs of (the largest count of one block's atoms in the CLB) divided by
  the number of labelled member atoms in logic CLBs. Exact block: a known block whose labelled atoms (10 LUTs and 10
  FFs) all lie in one logic CLB that holds no other block's atom. Null purity: 50 random packings, each keeping the
  packing's logic-CLB sizes and assigning the same labelled atoms at random (as round 3), mean purity.
* Statistics: the unit is the design. Wilcoxon signed-rank (scipy, zero differences dropped, needs >= 6 non-zero
  differences else p = NaN counted as 1.0); alpha = 0.05; Holm correction over the tests named in each hypothesis (NaN
  counts as 1.0). Bootstrap: 10000 resamples over the unit stated, seed 20261026, percentile interval. Per-design
  value of an arm = geometric mean over the 3 VPR seeds of the ratio against the matched reference (same seed).
  Every claim is on all kept designs (n stated) and, labelled, on the sizes B >= 32 only. The literal rule on the n
  actually available is the status. If n < 12 designs (or < 6 cells for slope tests) the status is "inconclusive
  (n too small)".
* Status words: supported / not supported / inconclusive. Anything not decided by the rule is inconclusive.
  Primary rule = the literal rule; variants are labelled "variant" and change no status.
* Post-data analyses are dated exploratory entries at the end of this file and change no status.

## Stage 1: the generator (`gen/r5gen.py`)

Deterministic from a seed (the integer 20261026 and the design's parameters; Python `random.Random`, no global state),
pure Python, no network. Output: one Verilog file per design (`top` module plus one module `b<k>` per block, instance
`b<k>`, module name = instance name so the provenance path is `b<k>` either way) and a record
`data/r5/designs.json` (parameters, designed block graph, designed cut, SHA-256 of the Verilog).

Block. 10 flip-flops r0..r9 (clocked, no reset). Flip-flop i is fed by a 6-input combinational function f_i of six
distinct signals; the function is chosen so that it depends on all six inputs (checked by truth table in the generator;
a candidate that does not is redrawn), so one 6-LUT implements it and ABC cannot shrink it. f_i always reads r_i
(self feedback), so every flip-flop is consumed locally and cannot be swept. Four of its six inputs, or more, are other
local flip-flops (dense internal connection); at most two inputs of any function are external (a pad or another
block's flip-flop). A block is 10 LUTs + 10 FFs = 10 logic elements = exactly one CLB (all 6-LUT logic elements; FFs
need 10 of the 20 flip-flop sites). Block inputs <= 18 distinct external nets (limit 40), outputs <= 8 (limit 20).
Block styles (the two styles differ in what the HDL exposes, which matters for the Norns packer):
* `dp` (datapath slice): the registers are one vector `reg [9:0] r` and the block output is the bus `q`; f_i reads
  r[(i+o) mod 10] for the offsets o in (0, +1, +2, +3, -1, -2) (a bit-sliced neighbourhood) with XOR-heavy functions
  (parity mixed with one AND/OR), so the HDL has a word and bit order.
* `ctl` (control/random logic): the registers are ten scalars `r0..r9`; f_i reads r_i plus five other signals drawn at
  random without repetition from the block's ten flip-flops; the function is a random expression tree over AND, OR,
  XOR and NOT. The HDL exposes no word.
External signal slots: an external input slot s of a block replaces local input number (s div 10 + 1) of the function of
flip-flop (s mod 10) (a block has at most 18 slots).

Topologies. Edge = a directed link u -> v of width w = 2: two distinct flip-flops of u drive two distinct external
slots of v. The output flip-flops of u are assigned in edge order (flip-flops 2j and 2j+1 for the j-th outgoing edge,
so at most 4 outgoing edges), and a flip-flop that is an output of no edge is local only.
* `chain`: k -> k+1 for k = 0..B-2.
* `mesh`: rows R = 2^floor(log2(B)/2), columns B/R; right/left/up/down neighbours, both directions (B a power of 2).
* `tree`: complete binary tree in heap order (parent of i is (i-1) div 2), both directions on every tree edge.
* `rand`: a random Hamiltonian path order (edges between consecutive blocks of a seeded shuffle) plus B further random
  directed edges (no self edge, no repeated edge), each block limited to 4 outgoing and 4 incoming edges (redraw on
  violation; if a draw fails 1000 times the generator stops with an error, it never relaxes the cap).
Fixed I/O: the same for every size, 8 primary inputs `pi[7:0]` and 8 primary outputs `po[7:0]` plus `clk`. Primary input
p feeds the external slot after the edge slots of block floor(p * B / 8); primary output p is flip-flop 9 of block
floor(p * B / 8) (so flip-flop 9 may be a local-only flip-flop elsewhere). For B < 8 several pads share a block.

Parameters and sizes. B in {4, 8, 16, 32, 64, 128, 256, 512, 1024} (nine log-spaced sizes, smallest first), topology in
{chain, mesh, tree, rand}, style in {dp, ctl}: 72 designs. Names `r5_<topology>_<style>_<B>`. One instance per
(topology, style, B). The cell is a (topology, style) pair: 8 cells of 9 sizes. The largest size has 10240 LUTs and the
same order of CLBs as the largest round-4 runs (stereovision2: 2479 CLBs ran in 110 s), so memory is not a limit (< 5 GB
expected); a design whose VPR run exceeds the 7200 s timeout is listed as failed.

Designed bounds. Cells of a design = 10 B LUTs and 10 B FFs. CLB count >= ceil(LUTs / 10) = B (exact: the block
partition reaches it; also valid as a bound, since one logic element holds one 6-LUT and a 6-LUT cannot share). Designed
cut = (number of distinct external nets) = (distinct driving flip-flops used by another block or by a primary output) +
8 (primary input nets) as computed from the spec; it is exact for the block partition (this is a cut of a given
partition, not a minimum), and the CLB bound is exact for the clustering but not a bound on WL or CPD.

Synthesis check ("the optimum is by construction only if synthesis keeps it"). After Odin III and ABC, per design,
from the BLIF and the block labels: LUT and FF atoms per block, distinct external input nets per block, measured cut
of the block partition against the designed cut. A design is KEPT iff all of:
(k1) total LUTs = 10 B and total FFs = 10 B (the CLB bound is exact);
(k2) every block has <= 10 LUTs and <= 10 FFs (no block over capacity) and <= 40 distinct input nets;
(k3) >= 99% of LUT and FF atoms carry a block label;
(k4) |measured cut - designed cut| <= 10% of the designed cut.
A design that is not KEPT is reported with the failing item and EXCLUDED from every hypothesis (it is still counted in
H18). A design that is KEPT but whose cut differs from the designed one reports the drift; the known cut used in all
tables is the MEASURED cut of the blocks. The rule is fixed here; no per-design judgement.

## Stage 2: measurement

Arms (3 VPR seeds each, 1, 2, 3; heavy lock; one VPR at a time; designs smallest B first, then topology order chain,
mesh, tree, rand, then style dp, ctl):
* `stock`: the stock `vpr` ($VPR).
* `norns`: the Norns packer $NORNS_VPR, round-4 headline configuration (affinity source `word`, beta 4,
  `--norns_proposal_count queued`), the affinity file built from the design's own provenance and Odin III word
  recovery exactly as round 4 (`affinity.write(design, "word", "r5")`; the word builder runs on the generated
  design's Verilog). The words are not derived from the block labels. State plainly (paper): in style `dp` the HDL
  has a vector `r` per block so the word finder is expected to find (nearly) the blocks, which is the situation in
  which HDL-aware packing should work if it ever does; in style `ctl` there are no vectors and the words are
  expected to be absent (few or no labelled atoms). Both outcomes are measured (the label coverage of the word file is
  reported per design), none is assumed.
* `known` (known-optimum clustering): the same Norns binary with an affinity file that gives every labelled atom its
  block's group id, `--norns_affinity_weight 100`, `--norns_proposal_count queued`. Beta 100 is two orders above the
  scale of a connected atom's gain ([0,1]) so the block membership dominates the molecule gain; the legalizer is
  AAPack's, untouched. Verification: from the `.net`/`final.flat_place` of every `known` run, purity against the known
  blocks and the number of exact blocks. Reproduction rate = exact blocks / B. Everything after packing (global
  placement of the flow, annealing, routing, W search) is stock.
  Contingency K2, fixed here: if the reproduction rate of `known` is < 1.0 on a KEPT design, the design is re-run with
  `--pack` only (not the analytical flow) once with the same affinity file and beta to see whether the analytical
  flow's distance threshold is the cause; if that also fails, `known` is labelled "closest mechanism" for that design
  and stays in the tests with the achieved reproduction rate reported per design (the gap is then to the achieved
  clustering). A design with reproduction rate < 0.9 is excluded from H19 to H23 (kept in H24 as a failure).
Run count: 72 designs x 3 arms x 3 seeds = 648 runs. Packing does not depend on the VPR seed (round 4, K5), so the three
`.net` files of a (design, arm) are compared by SHA-256 and the paper states the outcome.

Metrics per run: logic CLB count and gap to the bound (CLBs / B), the grid, purity and exact-block count against the
known blocks (and the null purity), measured cut of the packing and its ratio to the known cut, routed WL, minimum
channel width W, CPD (VPR's `Final critical path delay`; the Odin III attribution `cpd_ns` must agree within 0.5%, the
count of disagreements is reported), pack and flow runtime. Failed runs are listed, not replaced.
Odin III attribution: as round 4 (`scripts/timing4.py`, the V1.1.1 library functions through the workaround labelled
in the round-4 protocol), for the CPD cross-check and the share of critical-path hops that cross CLBs.

Time estimate (made from round-4 `flow_s` before any round-5 run): round 4 ran 2479 CLBs in 110 s, 630 CLBs in 15 s,
1034 CLBs in 12 s; bounding 0.05 s per CLB per run: sum over sizes of B x 8 designs x 9 runs x 0.05 s = 2047 x 72 x 0.05
= 7370 s (about 2 h), plus synthesis and word building (about 72 x 1 min), plus attribution. Well under the 8 h limit,
so no size is cut. If the measured time of the first 5 sizes extrapolates above 8 h in total, the two largest sizes are
cut, the cut is committed, and the paper says so.

## Hypotheses and decision rules

Ratios r = arm / `known` of the same design and seed, geometric mean over seeds per design. Metrics: CLB = logic CLB
count, WL, CPD (primary); W and cut (reported, not tested).

H18 (the yardstick works: synthesis keeps the construction). Over all 72 designs.
* Supported iff >= 90% of designs are KEPT and every cell has >= 6 KEPT designs.
* Not supported iff < 70% of designs are KEPT.
* Otherwise inconclusive.

H24 (the known-optimum arm reproduces the blocks). Over KEPT designs.
* Supported iff the reproduction rate is 1.0 on >= 90% of KEPT designs and the mean over KEPT designs is >= 0.99.
* Not supported iff the mean reproduction rate is < 0.90.
* Otherwise inconclusive. (Every outcome is reachable: the packer can fail to force a block, e.g. because of the
  distance threshold or the 30-candidate proposal cap; `known` has no mechanism that guarantees reproduction.)

H19 (room for the stock VPR packer) and H20 (room for the Norns packer): the same rule, `stock` and `norns` as P.
Per metric m in {CLB, WL, CPD}: the geometric mean over designs of r_m.
* Supported (there is room: the packer is worse than the known clustering) iff the geometric mean r >= 1.05 and the
  one-sided (r > 1) Wilcoxon p after Holm over the 3 metrics < 0.05.
* Not supported (no room) iff the geometric mean r <= 1.02 or the 90% bootstrap interval of the mean log r lies inside
  [log 0.98, log 1.02].
* Otherwise inconclusive. A mean below 1 (the packer beats the reference) counts as not supported. Variants (labelled):
  sizes B >= 32 only; per topology.

H21 (the gap grows with size). For P in {stock, norns} and m in {CLB, WL}: per cell (8 cells) the least-squares slope of
ln r_m on log2 B over the cell's kept designs (cells with < 5 kept sizes dropped). Statistic = median slope over
cells. 4 tests (2 packers x 2 metrics), Holm over the 4.
* Supported iff median slope >= 0.01 (at least 1% growth of the ratio per doubling), slope > 0 in >= 6 of the cells and
  the one-sided (slope > 0) Wilcoxon p after Holm < 0.05.
* Not supported iff the median slope <= 0.002.
* Otherwise inconclusive. Null: for each cell the r values are permuted over the sizes 10000 times; the share of
  permutations with a median slope at least the observed is reported as the permutation p (reported, not a rule).
  Needs >= 6 cells else inconclusive (n too small).

H22 (does the HDL-aware packer close part of the gap). Per metric m in {CLB, WL, CPD}: per design ratio `norns` / `stock`
(geometric mean over seeds). Same layout as round 4 H14.
* Supported (better) iff the geometric mean <= 0.99 and the one-sided (ratio < 1) Wilcoxon p after Holm over the 3
  metrics < 0.05.
* Not supported iff the geometric mean >= 1.00 or the 90% bootstrap interval lies inside [0.98, 1.02].
* Otherwise inconclusive. Round 4 saw WL 1.033 and CPD 0.996, so "not supported" is the expected outcome; stated before
  the data. Variants (labelled): per style; fraction of the gap closed = (r_stock - r_norns) / (r_stock - 1) on designs
  with r_stock >= 1.03 (reported with n).

H23 (HDL-aware packing helps exactly when the HDL exposes words). Per (topology, B) pair with both styles KEPT: d = purity
gain of `norns` over `stock` against the known blocks in `dp` minus the same in `ctl`. Wilcoxon one-sided (d > 0) over the
pairs.
* Supported iff the median d >= 0.05 and p < 0.05 and d > 0 in >= 70% of the pairs.
* Not supported iff the median d < 0.01.
* Otherwise inconclusive. Needs >= 12 pairs else inconclusive (n too small). Null: purity gain of 50 random repackings of
  the stock packing under the same CLB sizes is ~0 (reported with the mean and maximum null gain, for the "found" claim).
  Reported, not tested: WL ratio `norns` / `stock` per style.

Everything reported but not tested: gap per packer per size (table and figure), cut ratio, purity and exact-block counts
against the null, W, runtimes, attribution cross-check, share of critical-path hops crossing CLBs per arm.

## Tests (run before any VPR run, no `runs/` needed)

`tests/test_r5.py` (unittest, stdlib + scipy): (1) the generator is deterministic (two runs, equal SHA-256) and its
output differs for a different seed; (2) every function of a generated block depends on all six inputs; (3) the
designed spec respects the capacity limits (10 LUTs, 10 FFs, <= 40 inputs, <= 20 outputs, <= 4 outgoing edges) for all 72
designs; (4) the designed cut equals the cut computed from the spec by an independent counting function; (5) each
decision rule (H18 to H24) returns each of its three status words on synthetic data (constructed ratios), which shows no
status is unreachable by construction; (6) a design whose LUT count is perturbed is excluded by (k1). Gates: `ruff
check --select E4,E7,E9,F` clean on `scripts/` and `gen/`; regeneration (generator, designs record, statistics,
paper numbers) byte-identical from a `git archive` copy under `/tmp/claude-1000/nr5-*`; the steps that need `runs/` (VPR
logs, flat placements, BLIFs) are named in the paper and read the committed `data/r5/` records. Tectonic builds the
paper from the worktree and from the archive copy with 0 undefined references and citations.

## n

72 designs generated; the number KEPT is unknown (H18). If all are KEPT: H19 to H22 have n = 72 designs (or 63 for B >= 32 =
sizes 32..1024 = 7 sizes x 8 = 56 designs; the variant uses 56), H21 has 8 cells x 9 sizes, H23 has 36 pairs. A rule needs
n >= 12 designs (>= 6 cells, >= 12 pairs) else it is inconclusive; with fewer than 45 kept designs (< 5 sizes per cell)
H21's cells shrink and the status can be inconclusive; that is stated in the paper.
