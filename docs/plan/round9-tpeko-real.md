# Norns round 9 protocol: a known-optimum clustering built from REAL designs (written 2026-10-29, before any D' is built)

This file is committed and pushed before any round-9 benchmark is generated and before any round-9 VPR run. Its commit
SHA is the "rule provenance" of round 9. A rule changes only by a NEW dated entry at the end that keeps the old rule;
the paper then reports both. Written without any round-9 data. What was read before writing: the round-5 plan and
generator, `scripts/r6.py`, `scripts/e10_main.py`, `packer/README.md`, the architecture file, and the BLIF and the stock
packing (`vpr --pack`, one seed) of the three pilot designs, only to learn their shape (hard blocks, chains, cluster fill).

## Plain-English summary

Round 5 measured how far VPR's packer is from a known-best clustering, on circuits we generated from regular blocks. Peter's
objection (2026-10-29): the regularity of those circuits hides the true gap. Round 9 repeats the idea on real circuits.
Take a real circuit D. Take a clustering C of it (what VPR's own packer made, or what an independent partitioner made).
Then edit D into D' in three ways that touch only the inside of each cluster: (1) pad every cluster with dummy logic until
it is exactly full, so that the number of CLBs a perfect packer could use is exactly the number of clusters of C, and no
packer can do better; (2) make every look-up table a full 6-input one, so the CLB count cannot be lowered by sharing a
logic element between two small tables; (3) add connections inside each cluster, never between clusters, so that moving or
swapping any logic cell out of its cluster makes the cut worse. The wiring between clusters stays as it was in D, so D'
keeps the real circuit's inter-cluster structure (reported: Rent exponent, degree distributions, D against D'). We then
hand D' to stock VPR and to the Norns packer told C, and compare area (CLBs), wirelength and critical-path delay. Two
checks guard against fooling ourselves: the order and names of all atoms are randomly permuted (3 shuffles) so a packer
cannot replay C from file order; and a second benchmark D'' is built from a FOREIGN clustering (METIS, not VPR), so that
any advantage VPR has from being the author of C shows as a difference between D' and D''. First this runs on three
designs only (pilot); the full 35 designs wait for the controller's go.

Purpose (hub docs/purpose.md): Norns N Q1.6, how far is the packer from a known optimal clustering, on real structure.
Measures: area (CLBs), wirelength, speed (CPD). RQ: N Q1.6. Peter (2026-10-29): "Modify the nodes (atoms) in the cluster
post clustering such that it forces that only that clustering is the optimal one, then try clustering again with that
modified [netlist] ... has to be thought about well such that the result tells us if there is room in the packing/clustering
algorithm worth working on." And: "the regularity of the design, its artificialness, hides the true gap". Decisions
(Peter, 2026-10-29): (1) the optimum is area plus cut only; CPD is observed, not claimed; (2) pilot on ch_intrinsics,
diffeq1, mkPktMerge x 3 shuffles first; (3) a dated plan before the runs, the room rule as round 5. Background: Cong,
Romesis, Xie, ICCAD 2003 (`Cong03tpeko`); round 5 (docs/plan/round5.md).

## Definitions (in the order they are used)

* Architecture and flow: VTR 3c9a4d23b2, `k6_frac_N10_frac_chain_mem32K_40nm` (as rounds 1 to 8). CLB = 10 fracturable logic
  elements (fle), 40 input pins with a complete crossbar to the fle inputs, outputs 2 per fle. An fle is in ONE of two modes
  (read from the architecture file, `<pb_type name="fle">`): `n1_lut6` (one 6-LUT with 6 inputs and one flip-flop whose D can
  only be that LUT's output; out: LUT or flip-flop) or `n2_lut5` (two blocks `ble5`, each a 5-LUT with a flip-flop, the two
  sharing 5 input pins; each `ble5` can instead be in `arithmetic` mode, holding one adder). Flow flags as r6 `arm_run`
  (default flow, `--timing_report_npaths 100`, minimum channel width search).
* D: the real design = the E10 base netlist (Odin III, k=6), after the same clean-up VPR applies (buffer LUTs absorbed,
  dangling logic removed, constants kept as constants). The clean-up is done by the generator; the check is that VPR on the
  cleaned BLIF reports the same atom count. D is the input of both constructions.
* Cell: the unit that takes one fle. A LUT with the flip-flop it alone drives = one cell (type LF); a LUT without such a
  flip-flop = one cell (L). A flip-flop that is not driven by a LUT with no other sink ("lone" flip-flop) gets a wrapper:
  a new 6-LUT whose first input is the flip-flop's old D net, and the flip-flop is then driven by the wrapper = a cell (LF).
  Adders: a carry chain of L adders is one macro of weight ceil(L/2) fle (a chain starts at an fle boundary). Cell weight 1.
* Hard blocks: memories, multipliers and the io pads. They are outside the claim (their own block types, the packer does not
  cluster them with logic). A net with a pad or hard-block pin and at least one logic pin is cut in EVERY clustering; these
  nets are a constant K0 of the cut and are removed from the optimisation. The claim is about the logic cells only.
* Clustering C: a partition of the cells and macros into N_C clusters. Demand of a cluster = sum of cell weights.
* Cut of a clustering: number of non-clock, non-constant nets with pins in more than one cluster (pads and hard blocks each
  count as their own cluster, as in round 5). cut = K0 + cut*, cut* = cut of the logic-only hypergraph H*.
* Purity against C, exact cluster, reproduction rate: as round 5 (`r5lib.packing_vs_blocks`), clusters of C playing the role
  of blocks; dummy atoms are labelled too (they are in C).

## Stage 1: the construction, and why it is sound

Input D and a clustering C0 of D (a partition of the cells). C0 is either `own` (the clusters of `vpr --pack`, AAPack, stock
binary, seed 1; atoms to clusters from the `.net`) or `foreign` (METIS k-way on the cell hypergraph into N_C parts, N_C = number
of clusters of the own construction). Output D' (own) or D'' (foreign), written as BLIF, plus C (cell to cluster), plus a
record of everything below.

### Step A: legalise C0 under the 6-LUT accounting (C0 becomes C)

Widening every LUT to 6 inputs makes a cluster that held 14 fractured small LUTs need 14 fle. So C is C0 repaired: while a
cluster has demand above 10 or more than 40 distinct external input nets, evict its least-connected cell (never a macro unless
only macros remain) to the cluster that shares most nets with it and has room, else to a new cluster. Consequence, stated up
front: N_C (the CLB count of C) is at least the number of VPR clusters of D, and is reported next to it. Chains longer than 20
adders do not fit one CLB (diffeq1 has four chains of 34): they are cut into segments of at most 20 adders, all but the last
of even length; the carry link between segments (one net per cut) is removed and the next segment's carry-in is tied to
ground. This is the nearest sound alternative to the brief's "keep whole chains in one cluster or drop the design"; the
segments are kept whole in one cluster each, the number of cut links is reported per design, and D' differs from D by those
nets. Chains of at most 20 adders are kept whole.

### Step B: pad to exactly full (area)

Each cluster is padded with dummy LF cells (a 6-input LUT feeding one flip-flop) up to demand exactly 10. Dummy inputs come
only from nets driven inside the same cluster; a dummy output is read only inside its cluster. Dummies form a ring so none is
dangling (VPR removes dangling blocks; check: atom count of D' after VPR equals the generator's count).

Why C is exactly optimal in CLB count. Total demand T' = 10 N_C after padding. In every packing the following holds, by the
architecture file: (i) a cell's LUT has six distinct input nets, so it cannot be in a `ble5` (5 inputs) and needs an `n1_lut6`
fle, one cell per fle; (ii) a flip-flop of a cell can only be fed by its LUT, so it needs no other fle; (iii) an adder macro
needs ceil(L/2) fle that no other cell shares (the fle is in arithmetic mode; chains start at an fle boundary); (iv) hard
blocks are in other block types and use no fle; (v) a CLB has 10 fle. So any legal packing needs at least ceil(T'/10) = N_C
CLBs, and C reaches N_C, so the minimum is exactly N_C, by a counting argument that does not depend on the packer. Two things
this argument does not prove, and the plan tests them instead: that C is legal in VPR's actual packer (intra-cluster
routing, pin limits) is checked by the `known` arm reproducing every cluster (reproduction rate 1.0 for at least one
shuffle per design, else the design is reported as "C not confirmed legal"); that the architecture file has no further
mode (none was found).

### Step C: strengthen the inside (cut)

All edits add sinks only inside a cluster; they never add a net that leaves a cluster and never add a cluster input pin.
Done in this priority until the conditions below hold or nothing more can be done:
1. Fill. A LUT with k < 6 distinct inputs gets 6-k inputs from nets driven inside its cluster (table: f XOR parity of the added
   inputs, so it depends on all six). Preference: a net driven by a dummy (a net that stays inside), then a net of a cell whose
   output already has the fewest sinks inside.
2. Doubling. If a net N has exactly one pin u in cluster Ci and all its other pins in one other cluster Cj, moving u to Cj
   would uncut N. Another cell of Ci with a spare input slot also reads N (no new pin of Ci, no change of the cluster-level
   graph). For u's own output net: another cell of Ci reads it.
3. Internal anchor. A cell whose count a(u) of nets lying entirely inside its cluster (u as driver or reader) is too small
   reads a dummy's output (dummy outputs are entirely inside).
4. If a violation remains because no cell of the cluster has a spare input slot and the cluster has no dummy, it is reported
   per design as `unmet` (count of cells). We do NOT rewire D's inter-cluster nets to fix it; the claim is then weaker for
   that design and the design is flagged. (Rewiring would remove the real structure we are trying to keep.)

Why C is optimal in cut. Let cut*(P) be the logic-only cut of a partition P into N_C parts. Every part of a N_C-part partition
has demand exactly 10 (T' = 10K), so the only partitions with the minimum CLB count are the exactly-full ones. Scope of the
claim: the cut is minimal among those partitions; clusterings with more than N_C CLBs are not covered (they can have a lower
cut and are worse in area, which is the primary measure). What the construction PROVES, as a margin: for every ordered pair
of cells (u in Ci, v in Cj, i not j), swapping u and v increases cut* by at least `margin(u,v)`, computed exactly over every
swap whose two clusters share a net, and by at least a(u) + a(v) for all other swaps (nothing can be saved without a shared
net); the conditions of Step C aim at margin >= 1 for every swap, and the measured minimum margin over all swaps is reported
per design. So C is a strict local optimum of the swap neighbourhood whenever the minimum margin is at least 1 and `unmet` is
0. What it does NOT prove: that no partition far from C (a cycle of three or more cells, or a different arrangement of whole
groups of cells) has a lower cut. That is a global statement; it is checked, not proved:
independent METIS runs (pymetis, the Mimir partition extra, k-way with N_C parts on the star expansion of H*, 100 seeds, option
variants cut and volume), each result repaired to exactly-full parts and then refined by pair-swap local search; a
Kernighan-Lin style swap search from C after random perturbation of 10 percent of the cells (100 restarts); and the best cut
found compared with cut*(C). Any partition found with a smaller cut* falsifies the claim for that design (reported, design
flagged). "No partition found" is evidence, not proof, and is worded that way. Round 5 had the same limit (its entry (f), item 4).

### Step D: remove the replay channel

VPR's greedy packer breaks ties by atom order and seeds clusters from the first atoms it sees; a BLIF written cluster by
cluster could be replayed. After the construction every atom name and net name is replaced by an opaque random token, the
order of `.names`, `.latch`, `.subckt` statements and the order of `.inputs` and `.outputs` are randomly permuted, with a
fixed seed per shuffle (shuffle s = 1, 2, 3; the seed is a SHA-256 of the design name, the construction and s). The
netlist is the same graph in all three shuffles; only names and order differ. Stock purity against C is reported per shuffle,
and one extra control per design, `ordered`: the unshuffled, cluster-by-cluster file, stock arm only, seeds 1 to 3. If `ordered`
is much better than the shuffles, order is leaking and the shuffled ones are the valid measurement; the difference is the
measured size of the replay risk.

### What real structure D' keeps (Rent exponent and degrees), stated before it is measured

Kept exactly: every net that leaves a cluster (driver, sinks, fanout) except the carry links cut by segmentation; the cluster
graph (which clusters connect, with how many nets); all hard blocks and pads; the number of LUTs and flip-flops of D.
Changed by construction: every LUT now has in-degree 6 (D's mean is lower), so the in-degree distribution moves to 6; fan-out of
nets driven by cells that receive doubling or fill sinks rises by the added sinks; dummy cells (a fraction of all cells,
reported) are all-internal. The Rent exponent is expected to drop at block sizes of about one CLB (more intra-cluster
connection) and be close to D's at larger block sizes (the inter-cluster graph is D's). These are expectations, not rules; the
measured values decide. Measure: Rent exponent with the Mimir rent measurer (`mimir.rent`, recursive METIS bisection, seeds
1 to 3, fit range as in Mimir); designs below its 512-node floor are reported as "not measured" for the standard fit and with a
labelled relaxed fit (range B = 4 to N/8). Degree: in-degree and fan-out distributions of the logic cells (mean, median, p90,
max) and the distribution of net degree and of clusters per net, D against D'. This is the paper's answer to "how much real
structure D' keeps".

### Self-bias control

C = VPR's own answer favours VPR (it is a point VPR's greedy can reach). The foreign construction D'' uses a METIS partition
of the cell hypergraph into N_C balanced parts (target demand T/N_C each, repaired by Step A), built into D'' exactly as D'. The
comparison: log (stock/known) on D' minus log (stock/known) on D'', per design. If stock does relatively better on D' the
benchmark is biased towards VPR by that amount, and the paper reports both gaps and does not average them away. Also reported:
cut of the foreign C and of the own C in D.

## Stage 2: arms, measures, rule

Arms on every D' and D'' (3 shuffles each): `stock` (the stock `vpr`) and `known` (Norns binary, `--norns_affinity` = C's
clusters over all logic atoms including dummies and wrappers, `--norns_affinity_weight 100`, `--norns_proposal_count queued`,
the round-5 known arm). VPR seeds 1, 2, 3. One VPR at a time under the Norns VPR lock
(`flock -x /tmp/claude-1000/norns-vpr.lock`). Per run: logic CLBs and CLBs/N_C, cut and cut/cut(C), purity vs C and reproduction
rate, routed WL, minimum channel width, CPD, pack and flow time. Failed runs are listed, not replaced.

Pilot (this PR): ch_intrinsics, diffeq1, mkPktMerge. For each: own and foreign construction, 3 shuffles, seeds 1 to 3, arms stock
and known = 108 runs, plus the `ordered` control 3 designs x 2 constructions x 3 seeds = 18 stock runs. The pilot then
STOPS; the full set (15 VTR Verilog + 20 MCNC, smallest first) needs the controller's go.

Ratios r = stock/known of the same design, shuffle and VPR seed; per design the geometric mean over the 9 (shuffle, seed)
pairs. Metrics CLB, WL, CPD. Rule (the round-5 room rule): ROOM iff geometric mean >= 1.05 and the 90 percent bootstrap
interval of the mean log ratio excludes 0; NO ROOM iff geometric mean <= 1.02 or the interval lies inside [log 0.98, log 1.02];
otherwise INCONCLUSIVE. Bootstrap: 10000 resamples, seed 20261029, percentile; the pilot resamples the 9 (shuffle, seed)
replicates within a design (a design-level resample needs far more than 3 designs). Holm over the three metrics, within a design.
With 3 designs the pilot makes NO pooled claim: pooled geometric means are printed descriptively with n, labelled
"inconclusive (n too small)" by the round-5 convention (fewer than 12 designs). Comparison with round 5 (stock/known on 72
synthetic designs: CLB 1.073, WL 1.220, CPD 1.093; mesh and tree WL 1.489, same architecture and flags): printed beside the
pilot, to answer whether artificialness hides or inflates the gap; at n = 3 it is a pointer, not a test.

CPD and WL are NOT claimed optimal: `known`'s WL and CPD are what VPR achieves from C, not a bound; a packer can beat C and
ratios may fall below 1.

## Principles of the brief that cannot be met exactly (said here, not quietly weakened)

1. Cut optimality is proved only for single swaps (a margin by construction); global optimality is checked with independent
   partitioners and is evidence, not proof.
2. "Whole chains inside one cluster or drop the design": diffeq1's chains (34 adders) cannot fit one CLB; they are segmented
   (nearest sound alternative above), at the price of removing one carry net per segment boundary.
3. "Keep D's topology": nets leaving clusters are kept, but every LUT is widened to 6 inputs and lone flip-flops get a wrapper
   LUT, so the in-degree distribution and the LUT count change by construction; reported as D against D'.
4. C is VPR's clustering repaired for 6-LUT accounting, so N_C can exceed VPR's own cluster count on D.
5. Designs where hard blocks dominate (mkPktMerge: 459 memory slices against 178 LUTs) are kept in the pilot because the brief
   names them; the claim is about the logic CLBs only and the hard-block nets are a constant of the cut. They are listed.
6. A cluster with no dummy and no spare input slot cannot be strengthened without rewiring; it is flagged (`unmet`).

## Time estimate (before any run)

Pilot designs have 12 to 30 CLBs of logic (stock packing), so each flow is about 5 to 60 s (mkPktMerge has 459 memory slices
and a larger grid). 126 runs x at most 60 s is under 2.5 h of VPR under the lock; the generator, the METIS checks and the Rent
measurement are minutes.

## Entry 2026-10-29 (a): changes found necessary while writing the generator (dated; written before any D' or D'' was run in VPR)

The plan above is kept; the following refine Stage 1 and the reports. No VPR arm run of any D' or D'' existed when this entry was
written (VPR was run only on cleaned D, on single clusters, and on written files to test the generator). No rule of Stage 2 changed.

1. D is the generator's clean-up of the E10 BLIF (constants folded into LUTs, buffer LUTs absorbed, dangling logic swept). Check
   per design: `vpr --pack` on the cleaned file reports the same flip-flop and adder counts and at most two more LUT atoms than
   the cleaned file has, the extra ones being the constant generators `gnd` and `vcc`, which VPR instantiates as LUT atoms. Each is
   a cell of weight 1 (kind K) placed in a cluster, so the count stays exact; the bound still holds if VPR pairs the two in one fle
   (10K - 1 > 10(N_C-1)). A primary output driven by a constant is kept as `.names gnd o` (a buffer VPR absorbs).
2. Pin limits. C respects what VPR's default flow forms, not the raw architecture: at most 32 external input nets (0.8 of 40) and
   12 external output nets (0.6 of 20) per cluster; a carry-chain macro keeps its own pins. Reason: a C that needs 33 inputs cannot
   be formed by the stock flow, so stock/known would measure the flag, not the packer.
3. Step A also (i) keeps one logic element free per cluster for a dummy (capacity 9 for real cells, 10 only where a single vertex
   needs it), because the strict margin of Step C needs at least one all-internal net per cell and only a dummy can supply it, and (ii)
   merges clusters that fit together (VPR leaves tail clusters of one to four cells). N_C can still exceed VPR's cluster count.
4. Step C: when a cell already has six real inputs and no spare slot, one input that is a pad or hard-block net (constant-cut, with
   other readers) is replaced by a dummy output. Count reported as `rewired_const_cut`. Inter-cluster logic nets are never rewired.
   A cell that still cannot be anchored is counted as `unmet`. Constant-generator cells have no nets; a swap with one is a tie by
   construction and is counted apart (`swaps_le_0_with_const_cell`).
5. Carry chains are cut into segments of at most 12 adders (not 20): a segment then needs at most 24 input nets and 12 sumout nets,
   which VPR's default flow can form; a 20-adder segment (40 inputs, 20 outputs) cannot be formed by it. Segments are of even length
   except the last; one carry net is removed per boundary and its count is reported (`carry_links_cut`). Segments are the same
   in the own and the foreign construction; the cluster of a segment in `own` is the cluster of its first adder in VPR's packing.
6. Foreign C0 = the lowest cut over 40 METIS seeds (1001 to 1040), each followed by pair-swap descent, then Step A. The independent
   check uses seeds 1 to 100 (disjoint from the construction's). Reason: a single METIS run was beaten by a local search from other
   METIS runs on the first design tried, so it was not a fair "foreign optimum".
7. Legality of C. Added: VPR itself packs every cluster of C alone (stock binary, and the Norns binary with all atoms in one
   affinity group). C's clusters that give exactly one logic CLB under at least one of the two are "confirmed"; the others are
   listed per design. Greedy packing can fail on a legal cluster (observed: a cluster of one carry-chain macro plus ordinary cells
   is split by VPR's order of placement), so "not confirmed" is not "illegal"; it is reported, not hidden. The counting bound on
   the CLB count holds regardless.
8. Reports. Besides stock/known (the brief), the summary gives stock/N_C and known/N_C for CLBs (N_C is the exact area bound), cut/cut(C),
   purity, reproduction rate, and the `ordered` control (shuffle id 0: statements cluster by cluster, names in order of first use).
   Bootstrap detail: "interval excludes 0 after Holm" is read as the Holm-adjusted two-sided bootstrap p < 0.10.
9. The independent partitioner check can be vacuous when no METIS partition satisfies the pin limits (diffeq1); the record carries
   `metis_legal` and the best pin-illegal cut, and the report states which. The perturbation search (`shake`) is always legal.

## Entry 2026-10-29 (b): stage 3a, the exact arm (method choice; written before any full-set run)

Why. In the pilot the `known` arm (Norns packer told C, beta 100) reproduced C only 0.40 to 0.80 of the time (purity 0.89 to 0.97), so
stock/known measured the gap to the Norns mechanism, not to C. The aim of 3a is an arm in which VPR places and routes exactly C,
so that wirelength and critical-path delay OF C ITSELF are measured and `stock/exact` is a ratio to C.

Candidates read in VPR 3c9a4d23 (`vpr/src/base/read_options.cpp`): `--net_file` (:2071), `--read_vpr_constraints` (:2120),
`--read_flat_place` (:2134). Constraints and flat placement guide or limit where blocks go; neither is documented to force a packer to
form a given partition, and raising beta is a soft pull that the pilot already shows is not exact. `--net_file` skips packing and
loads a packed netlist, so the clusters are whatever the file says.

Method chosen: build the packed netlist from VPR's own packings of the single clusters. (1) Cut the shuffled `design.blif` into one
netlist per cluster of C (nets from outside become pads, nets to outside become outputs). (2) Pack each alone with the stock binary
(AAPack, seed 1); this gives VPR's own legal intra-cluster routing for that cluster. The first packer variant that gives one logic CLB
and puts every external input on a CLB pin is used (variant 0 is the default options; the others, listed in `scripts/r9exact.py`,
change clustering options only: alpha, connection or timing driven off, unrelated clustering, seed type, pin utilisation). (3) Copy
those CLB blocks into one `.net` file whose header, pads and hard blocks come from the stock packing of the full shuffled netlist
(same atom netlist, so the file's netlist hash matches), numbering the blocks as VPR requires. (4) Run `vpr --net_file ... --place
--route --analysis` (VPR seeds 1 to 3). Nothing about C is approximate: purity is 1 and the logic CLBs are N_C by construction, and the
check is that VPR loads the file against the BLIF and routes it. The constant generators `gnd` and `vcc` are CLBs of their own in the
stock packing of the full netlist, so every flow reports N_C plus those 1 or 2 CLBs; they are copied unchanged and left out of purity
(they are in no cluster of C in the packed file). The shipped statistics report `logic_clbs` as VPR prints it and `clbs - const_clbs`.

Acceptance (set before the full set): CLBs = N_C and purity >= 0.95 on the three pilot designs, both constructions, all 3 shuffles.
If a cluster cannot be packed alone by any variant, that design has no exact arm and is listed; if the method failed on the pilot,
stock/N_C (area, exact) would stay primary and WL and CPD would be stated against the Norns `known` arm.

Why this is a fair "C placed and routed" measure, and where it is not. The placer and router are VPR's own, run from C; they are free to
find a good or poor placement of C's clusters (3 VPR seeds, 3 shuffles). The intra-cluster packing of each cluster is the one VPR's
packer finds for it alone, which is a legal packing, but not the only one; pin assignment inside a cluster could change timing a little.
`exact` is therefore an achievable point, not a bound: a packer can beat C in WL or CPD, and ratios below 1 are possible.

Full set (3b), also fixed now. Designs: the 15 VTR Verilog designs (blob_merge, boundtop, ch_intrinsics, diffeq1, diffeq2,
mkDelayWorker32B, mkPktMerge, mkSMAdapter4B, or1200, raygentop, sha, stereovision0 to 3) and the 20 MCNC designs (alu4, apex2, apex4,
bigkey, clma, des, diffeq, dsip, elliptic, ex1010, ex5p, frisc, misex3, pdc, s298, s38417, s38584.1, seq, spla, tseng), the E10 base
netlists, ordered by LUT-plus-flip-flop count, smallest first. Per design: own and foreign construction, shuffles 1 to 3 plus the
`ordered` control (stock only), VPR seeds 1 to 3, arms stock, known and exact. A design that cannot be built within the memory cap or
in a day of generator time is listed with the reason, not dropped silently. For the large designs the independent partitioner check is
run with fewer seeds (the count is stored in the build record) and this is said where it applies.
Statistics: the design is the unit. Per design the ratio is the geometric mean over the 9 (shuffle, seed) pairs; the pooled value is the
geometric mean over designs; the interval is a bootstrap over designs (10000 resamples, seed 20261029, percentile, 90 percent); Holm
over the metrics CLB, WL, CPD. Verdicts by the same room rule. The primary ratios are stock/N_C (CLBs, exact) and stock/exact (WL and CPD);
stock/known is reported beside them. Self-bias: per design log(stock/exact) on own minus on foreign, pooled and bootstrapped over
designs. Comparison with round 5 (CLB 1.073, WL 1.220, CPD 1.093 on 72 synthetic designs) in one table.
Weekly meter is checked between steps; the work stops and reports at a weekly figure of 85 percent.

## Entry 2026-10-30: resume after the VM crash, fixes, and results of the full set (33 of 35 designs)

Plain English first. On 33 real designs, with the clustering C known by construction (N_C clusters, every cluster full), VPR's stock packer
needs about 10 percent more CLBs than N_C (own C 1.108, foreign C 1.101), and when its placement is compared with the placement and routing
of C itself, stock wirelength is about 33 percent higher (n = 25 designs that have an exact arm) and critical path delay about 3 to 5 percent
longer. The gap is not an artefact of C being VPR's own answer: the own/foreign difference is 1.01 in CLBs and not distinguishable from 1 in
wirelength and delay. The real-structure gap is about the same size as the round-5 synthetic gap in area (stock/known 1.059 against 1.073)
and larger in wirelength (1.265 against 1.220); delay is smaller (1.026 against 1.093). So artificialness did not hide the gap; it slightly
inflated the area and delay figures and slightly deflated the wirelength figure. Two designs (stereovision0, stereovision2) are not in the
set (below).

What happened on the resume. The crash (host C: full, 2026-10-29 about 22:08) left: runs.jsonl with a NUL line and complete lines; zero-length
`.net` and report files from single-cluster packs that were running; designs with 42 to 57 of 60 runs. A run is finished if and only if its
`metrics.json` exists (written last, then one line appended to runs.jsonl), so no run was half-counted; a run without `metrics.json` is run
again in its own directory (VPR rewrites its files; nothing deleted). The torn runs.jsonl line is skipped by `r9run.read_runs` (used by the
summary and by `r9pool.py`). Runs are keyed by the hash of the input file, so a rebuilt design never reuses an earlier run. The driver was a
shell loop (`resume.sh` in the run root, not committed) calling `r9build.py`, `r9run.py arms DESIGN --ordered` and `r9exact.py run DESIGN
--only-missing`, with the disk guard (C: free at least 15 G, read before each design and each step; lowest seen 40 G) and the weekly guard
(stop at 97; seen 79 to 80).

R2, the build rc=1 cases. (1) mkSMAdapter4B, s38584.1, s38417: the pre-fix generator raised "cluster too small to give a LUT six distinct
inputs without a combinational loop"; the chain later rebuilt all three with the loop fix (rc=0, 60 runs each for the two MCNC designs).
mkSMAdapter4B had been built with shuffles 0 and 1 only, so its runs stopped after six; it was rebuilt with all three shuffles. (2) blob_merge:
the legality check read a zero-length `.net` left by a pack the crash killed (`run_vpr_pack` reused any existing file). Fix: an empty cached
`.net` is packed again (`r9build.run_vpr_pack`, same in `r9exact.pack_alone`); test `TornPack`. blob_merge then built and ran (42 runs).
A slip of mine: one mkSMAdapter4B rebuild was started without `R9_OUT` and wrote into the v1 root (`r9-out/mkSMAdapter4B`: build.json,
struct.json, the clean file and `legal` were regenerated by the current generator). v1 runs.jsonl is untouched and no v1 file was deleted;
the v1 mkSMAdapter4B build directory no longer matches the v1 runs for that design (all of them failed foreign exact runs).

Exact arm (stage 3a), what was found and fixed. Single-cluster packs of clusters with a dangling adder `sumout` made it a pad, so the
assembled `.net` named a net that VPR sweeps ("unknown net found in .net file", mkPktMerge, or1200, mkDelayWorker32B). Fix in
`r9exact.cluster_blifs`: a dangling adder output is no pad; new output tag `exact16` (the old `exact15` files are kept; a run succeeded under
either tag counts, `--only-missing`). mkPktMerge then ran (own 8 of 9; the other still fails). Still without an exact arm (the stock and known
arms are complete for all of these): blob_merge, boundtop, raygentop (const_gnd cannot be packed alone), mkSMAdapter4B (const_vcc),
stereovision1 (16 own and about 38 foreign clusters do not pack alone), and mkDelayWorker32B, or1200, stereovision3 (the assembled `.net` makes
the stock VPR abort in the post-cluster delay calculator, SIGABRT, or rc=1; cause not found: the constant-generator and adder-chain handling is
the suspect; the stock `.net` of the same netlist runs). Their exact failures are listed and not replaced.

Excluded designs. stereovision2 (about 79k BLIF lines): the generator had not finished after 105 CPU-minutes when stopped; stereovision0
(about 18k LUT and FF): not started. Both are listed as not built, not as failures of the method. The set is therefore 33 designs
(13 VTR Verilog, 20 MCNC).

Results (data/r9/full-summary.json; scripts/r9pool.py; design is the unit; geometric mean over designs, 90 percent bootstrap over designs,
10000 resamples, seed 20261029, Holm over CLB, WL, CPD; room rule as round 5). Primary: CLB against N_C (exact), WL and CPD against the exact arm.

| ratio | C | n | CLB | WL | CPD |
|---|---|---|---|---|---|
| stock / N_C | own | 33 | 1.108 [1.080, 1.149] ROOM | - | - |
| stock / N_C | foreign | 33 | 1.101 [1.073, 1.140] ROOM | - | - |
| stock / exact | own | 25 | 1.099 [1.065, 1.146] ROOM | 1.322 [1.278, 1.367] ROOM | 1.033 [1.024, 1.042] INCONCLUSIVE |
| stock / exact | foreign | 25 | 1.087 [1.055, 1.136] ROOM | 1.330 [1.280, 1.384] ROOM | 1.054 [1.037, 1.076] ROOM |
| stock / known | own | 33 | 1.059 [1.049, 1.071] ROOM | 1.265 [1.223, 1.307] ROOM | 1.026 [1.014, 1.038] INCONCLUSIVE |
| stock / known | foreign | 33 | 1.056 [1.046, 1.066] ROOM | 1.287 [1.243, 1.332] ROOM | 1.042 [1.027, 1.062] INCONCLUSIVE |
| round 5, stock / known, synthetic, 72 | - | 72 | 1.073 | 1.220 | 1.093 |

Self-bias (own divided by foreign, per design, n = 33): stock/N_C 1.007 [0.999, 1.014]; stock/exact CLB 1.011 [1.005, 1.017] (Holm p 0.011),
WL 0.994 [0.978, 1.009], CPD 0.980 [0.962, 0.997] (Holm p 0.09). Stock does very slightly better in CLBs on the own C; nothing else is
distinguishable from 1. CPD is not claimed optimal (stage 1 decision): the exact arm is an achievable point, not a bound, and CPD verdicts
are mostly INCONCLUSIVE because the gm lies between 1.02 and 1.05. Outlier: clma has N_C = 51 below VPR's own 82 clusters and stock/N_C
1.95 (known/N_C 1.88), so even the Norns known arm cannot reach C there; it enters every geometric mean (without it stock/N_C is 1.089 own and 1.081 foreign).
Caveats: 25 of 33 designs have the exact arm and the missing eight are the hard-block, constant-heavy and large ones, so the stock/exact rows
describe the easier designs; the stock/known and stock/N_C rows cover all 33. The Norns known arm reproduces C 0.82 to 1.00 (purity).
Rename: K is now N_C (cluster count) in this plan and in the r9pool output; JSON keys in build.json and the summary still say K.
