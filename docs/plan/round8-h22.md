# Norns H22' re-run: packer with realistic bus words, no leak (written 2026-10-28, before any round-8 benchmark or VPR run)

This file is committed and pushed before any H22' design is generated for measurement and before any VPR run of this experiment. Its commit SHA is the rule provenance of the experiment. A rule changes only by a NEW dated entry at the end that keeps the old rule.

Purpose: Norns N3, question N Q3.1 (does packing by higher-level ideas keep the HDL structure and improve placement?). Measure: routed wirelength (WL, primary). CLB count and critical-path delay (CPD) are reported, never used for the verdict. Trigger (Peter 2026-10-28: "if the gains were an error, rerun the experiment").

## Why a re-run

Read-only controller investigation: H22's WL 0.902 (63 round-5 designs) comes only from the 18 mesh/tree `dp` designs whose word file equals the optimal CLB partition (`gen/r5gen.py` 308-313, word-file purity 0.9998). That is an oracle upper bound, not a gain. Leak-free round-6 levels show harm (a = 0.75: mesh 1.15, tree 1.29); designs with no words give 1.000. H37's pooled 4.15x on chain is the packer obeying misaligned words (a = 0: 8.71, a = 1: 1.003), expected, so that control was ill-posed.

## Hypothesis H22'

With realistic bus words that do not mirror the CLB partition, the Norns packer reduces WL versus stock VPR.

## Designs (`gen/r8gen.py`, new, copy of the round-6 layout code)

Logic, topologies, sizes and known blocks are the round-5 `dp` designs of the round-6 ladder: topology in {mesh, tree} (test) and chain (control), B in {16, 32, 64, 128, 256, 512, 1024}. Only the HDL register declaration changes (round-6 mechanism): block registers and ports are scalars; the top module declares word buses `wire [w-1:0] w<j>`; flip-flop (k, i) drives one bit of one word.

Layout, per (topology, w, B): a seeded `random.Random(f"{SEED}:{name}:layout")` (SEED = 20261026) draws one random permutation of all 10 B flip-flops (this also randomises block order); word j holds permutation entries j*w .. j*w+w-1 (the last word is narrower if w does not divide 10 B); bit = position in the word. Widths w in {4, 8, 16, 32}: none is a multiple of 10, so words cut across blocks. Names `r8_<topology>_w<w>_<B>`. Per design the measured word-file purity against the blocks (round-6 definition: sum over words of the largest count of one block's FFs, over FFs with a word and a block label), words per block and blocks per word are reported (`data/r8/designs.json`, `keep.json`). Keep rule: round-6 k1 to k5 (k5 = word coverage >= 90%). A design that is not kept is listed and dropped from the tests.

Designs: mesh and tree x 4 widths x 7 sizes = 56 test designs; chain x 4 widths x 7 sizes = 28 control designs; total 84. Extra control (ii): the 7 round-6 designs `r6_chain_a100_<B>` (`gen/r6gen.py`, unchanged), run with arms stock and norns only (the leak-free word = block layout on chain; expected about 1.003).

## Arms and seeds

Arms (round-6 `scripts/r6.py aff_flags`): `stock` (stock `vpr`); `norns` (Norns binary, the word file from Odin III word recovery as written, `--norns_affinity_weight 4`, `--norns_proposal_count queued`); `known` (yardstick: the block labels, weight 100, queued). VPR seeds 1, 2, 3. Flow and flags as round 6 (arch `k6_frac_N10_frac_chain_mem32K_40nm`, `--timing_report_npaths` raised from 100 to 1000 for near-critical data, `--write_flat_place`, `--write_initial_place_file`). The setup timing report is kept; the `.route` is kept only if under 1 MiB (in practice it is not written beyond what the flow writes into the run directory; nothing is deleted).
Runs: 84 designs x 3 arms x 3 seeds = 756, plus 7 x 2 x 3 = 42 for control (ii): 798.

## Controls, run first

(i) Beta 0 gate: the Norns binary with the chain word file and `--norns_affinity_weight 0` must give a `.net` byte-identical to stock on every chain design (packer/README Stage-1 gate (b)), checked on all 28 chain designs at seed 1 (packing does not depend on the seed). If it fails on any design: stop, report, run nothing else.
(ii) Chain at alignment 1 (the 7 `r6_chain_a100` designs): Norns/stock WL geometric mean expected about 1.003 (round 6); report what is measured.

## Measure and decision rule (fixed now)

Per design, ratio norns/stock of a metric = geometric mean over the seeds with both runs rc 0 of m_norns(seed)/m_stock(seed); a design needs >= 2 matched seeds, else it is dropped from that test and listed. Per width w the test set is mesh + tree pooled (n = 14 designs: 2 topologies x 7 sizes).
* One-sided Wilcoxon signed-rank test on log ratios (alternative: ratio < 1) per width; Holm adjustment over the 4 widths (family of 4). 90% interval of the geometric mean: bootstrap, seed 20261026, 10000 resamples (`scripts/r5stats.py` helpers).
* CONFIRMED iff geomean WL ratio <= 0.99 AND Holm-adjusted p < 0.05.
* NOT CONFIRMED iff geomean >= 1.00 OR the 90% interval lies inside [0.98, 1.02].
* Otherwise INCONCLUSIVE. Evaluation order: CONFIRMED, then NOT CONFIRMED, then INCONCLUSIVE. No combination across widths is defined; the four verdicts are the result.
* Chain control per width (n = 7): the geometric mean of the WL ratio must lie in [0.98, 1.02]. If it does not, report the mechanism and do not read the mesh/tree verdict of that width as a gain.
* CLB and CPD get the same statistics (same Holm family per metric) and are printed; they never change the WL verdict.

## Compute estimate (made before any run)

Round-6 sizing: about 31 s of flow per (topology, level, arm, seed) summed over the seven sizes: 12 (topology, width) groups x 9 runs x 31 s about 56 min VPR, plus 7 x 6 x 31 s for control (ii); the larger timing report adds a little. Synthesis plus word recovery about 11 min per (topology, level) in round 6, so 12 groups about 2 h, serially; total about 1.5 to 3 h of wall time. Memory: one VPR at a time under `/tmp/claude-1000/norns-vpr.lock`, <= 14 GB total, started only with >= 5 GB available; `/mnt/c` >= 30 GB free. Smallest designs first.

## Outputs

Results section appended to this file (table per width: n, geomean WL/CLB/CPD, 90% interval, p, verdict; chain control; purity); hypothesis register row H22' in the format of the register; H37 restated per alignment level from the round-6 data; run records (`mimir-run.json`) imported into a new store `work/mimir-data/h22.db` (`mimir import-runrecords`, `import-timing --report`), `mimir privacy-check` must report 0.

## Results (written 2026-10-28 after the runs; the literal rule above is the status)

Plan commit 55792adc7a5d9fbfd423f6adc325ab48e69df222 (before any run). All 84 designs KEPT (k1 to k5, word coverage 1.000); 798 of 798 runs rc 0; the 6 control-(ii) rows below come from the 7 `r6_chain_a100` designs.

Control (i), beta 0 gate: Norns binary, beta 0, chain word file, `--pack`, seed 1: `.net` byte-identical to stock on 28 of 28 chain designs (`data/r8/gate.json`). Passed; the experiment proceeded.

Per width, mesh + tree pooled (n = 14), norns / stock; geometric mean, 90% bootstrap interval, one-sided Wilcoxon p raw / Holm over 4 widths; chain control (n = 7). Verdict on WL only.


### Wirelength (primary, decides the verdict)

| word width w | n | geomean norns/stock | 90% interval | p raw / Holm | verdict (rule applied to this metric) | chain n | chain geomean [90%] | chain in [0.98, 1.02] |
|---|---|---|---|---|---|---|---|---|
| 4 | 14 | 1.652 | [1.525, 1.809] | 1.0000 / 1.0000 | NOT CONFIRMED | 7 | 3.575 [2.945, 4.336] | OUTSIDE |
| 8 | 14 | 2.011 | [1.824, 2.237] | 1.0000 / 1.0000 | NOT CONFIRMED | 7 | 5.604 [5.065, 6.152] | OUTSIDE |
| 16 | 14 | 2.349 | [2.125, 2.609] | 1.0000 / 1.0000 | NOT CONFIRMED | 7 | 7.969 [7.665, 8.273] | OUTSIDE |
| 32 | 14 | 2.505 | [2.247, 2.802] | 1.0000 / 1.0000 | NOT CONFIRMED | 7 | 9.497 [8.795, 10.196] | OUTSIDE |

### Logic CLBs (secondary)

| word width w | n | geomean norns/stock | 90% interval | p raw / Holm | verdict (rule applied to this metric) | chain n | chain geomean [90%] | chain in [0.98, 1.02] |
|---|---|---|---|---|---|---|---|---|
| 4 | 14 | 1.033 | [1.004, 1.064] | 0.9547 / 1.0000 | NOT CONFIRMED | 7 | 1.145 [1.095, 1.200] | OUTSIDE |
| 8 | 14 | 1.012 | [0.988, 1.034] | 0.7649 / 1.0000 | NOT CONFIRMED | 7 | 1.134 [1.107, 1.161] | OUTSIDE |
| 16 | 14 | 0.973 | [0.961, 0.984] | 0.0005 / 0.0015 | CONFIRMED | 7 | 1.136 [1.094, 1.187] | OUTSIDE |
| 32 | 14 | 0.946 | [0.925, 0.965] | 0.0002 / 0.0010 | CONFIRMED | 7 | 1.085 [1.065, 1.104] | OUTSIDE |

### Critical-path delay (secondary)

| word width w | n | geomean norns/stock | 90% interval | p raw / Holm | verdict (rule applied to this metric) | chain n | chain geomean [90%] | chain in [0.98, 1.02] |
|---|---|---|---|---|---|---|---|---|
| 4 | 14 | 1.329 | [1.235, 1.427] | 0.9999 / 1.0000 | NOT CONFIRMED | 7 | 1.493 [1.437, 1.560] | OUTSIDE |
| 8 | 14 | 1.371 | [1.252, 1.498] | 0.9999 / 1.0000 | NOT CONFIRMED | 7 | 1.828 [1.650, 2.022] | OUTSIDE |
| 16 | 14 | 1.380 | [1.299, 1.463] | 1.0000 / 1.0000 | NOT CONFIRMED | 7 | 2.101 [2.005, 2.212] | OUTSIDE |
| 32 | 14 | 1.407 | [1.302, 1.514] | 0.9999 / 1.0000 | NOT CONFIRMED | 7 | 2.285 [2.132, 2.464] | OUTSIDE |

### Word-file purity against the CLB blocks (median over 7 sizes, min to max)

| topology | w=4 | w=8 | w=16 | w=32 |
|---|---|---|---|---|
| mesh | 0.259 (0.250 to 0.331) | 0.151 (0.129 to 0.256) | 0.100 (0.067 to 0.156) | 0.069 (0.043 to 0.138) |
| tree | 0.259 (0.251 to 0.331) | 0.145 (0.129 to 0.219) | 0.106 (0.068 to 0.181) | 0.067 (0.043 to 0.156) |
| chain | 0.259 (0.251 to 0.350) | 0.142 (0.128 to 0.269) | 0.102 (0.069 to 0.188) | 0.070 (0.043 to 0.144) |

### Control (ii): chain at alignment 1 (`r6_chain_a100`, 7 designs)

Norns/stock WL 1.003 [0.993, 1.013], CLB 0.998, CPD 1.019. Inside [0.98, 1.02]; reproduces round 6 (about 1.003).

### H37 restated per alignment level (round-6 data, chain, norns/stock WL, n = 7 per level)

| designed alignment a | median word purity | geomean [90%] |
|---|---|---|
| 0 | 0.100 | 8.708 [8.063, 9.327] |
| 1 | 1.000 | 1.003 [0.993, 1.013] |
| 0.25 | 0.255 | 8.365 [7.209, 9.207] |
| 0.5 | 0.506 | 6.191 [5.603, 6.764] |
| 0.75 | 0.752 | 2.722 [2.505, 2.985] |

The pooled 4.15x of H37 is an average over alignment levels. At a = 1 (words equal blocks) the packer leaves chain unchanged (1.003); WL grows as purity falls (2.72 at 0.75, 6.19 at 0.5, 8.37 at 0.25, 8.71 at 0.1). The control was ill-posed: chain is not 'no effect', it is 'no headroom', and a packer that follows misaligned words is expected to do harm there.

### Verdicts

H22' is NOT CONFIRMED at all four widths (WL geomean 1.652, 2.011, 2.349, 2.505 at w = 4, 8, 16, 32; Holm p = 1.0). The packer does the opposite of reducing WL: it raises it by 65% to 150% on mesh and tree, and CPD by 33% to 41%. It reduces logic CLBs by 2.7% and 5.4% at w = 16 and 32 (Holm p 0.0015, 0.0010; CLB interval rule applied identically) but increases CLBs at w = 4 and 8; per the plan, a CLB result never changes the WL verdict. The chain control FAILS at every width (WL 3.58, 5.60, 7.97, 9.50), so no mesh/tree reading as a gain is possible; the plan's instruction to report the mechanism applies.

Mechanism (from the beta 0 gate and the control rows): at beta 0 the `.net` equals stock, so the whole effect is the affinity term. With words that are bit-slices over random flip-flops, the packer pulls flip-flops of different blocks into one CLB because they share a word; the harm grows with w (more flip-flops per word, lower purity, 0.26 down to 0.07) exactly as the chain H37 curve grows as purity falls. Chain suffers more than mesh and tree (3.58 to 9.50 against 1.65 to 2.51) in WL. Tree is hurt more than mesh (topology rows in `data/analysis/r8-results.json`: mesh 1.52 to 2.04, tree 1.79 to 3.08). The `known` yardstick (labels as affinity, weight 100) gives WL 0.672 of stock on mesh and tree at every width (the same logic and blocks at every width, so equal to 3 digits is expected but is recorded as observed, not explained further), i.e. the headroom is real; the realistic words do not reach it.

Reading: the H22 gain (0.902) was the leak; with words that do not mirror the CLB partition the Norns packer at beta 4 does harm. No result of this experiment supports a WL gain from HDL words of this kind. What was not tried and stays open: a smaller beta, words that only weakly agree with blocks, and real HDL words (this is a construction, not measured HDL; the layout is a random permutation, the extreme of non-alignment).

### Hypothesis register row (format of docs/paper/hypotheses.md on branch docs/hypotheses; that file is not in this branch)

| H22' | R8H22:Hypothesis H22' | Norns packer with realistic bus words (no leak) | With bus words that do not mirror the CLB partition, the packer reduces WL versus stock. | PRE-REGISTERED (plan commit 55792adc, before any run) | 56 mesh/tree designs (4 widths x 7 sizes x 2 topologies, pooled 14 per width), 28 chain controls, 3 seeds | WL (CLB, CPD secondary) | WL norns/stock 1.652, 2.011, 2.349, 2.505 (w = 4, 8, 16, 32); 90% intervals [1.525, 1.809], [1.824, 2.237], [2.125, 2.609], [2.247, 2.802]; CPD 1.33 to 1.41; CLB 0.946 to 1.033 | one-sided Wilcoxon, Holm over 4 widths (p = 1.0); interval vs [0.98, 1.02] | DISMISSED (NOT CONFIRMED at every width; the chain control also failed at every width) | yes (replaces the H22 gain claim)

### Deviations and notes

* `--route_file /dev/null` for B > 128 (the `.route` is kept in the run directory only for B <= 128); nothing was deleted. Stock arm = the stock VPR build (`$VTR_ROOT`), Norns arms = the Norns VPR (`work/norns-vtr`), as round 6.
* Word purity measured by the keep step differs slightly from the designed value for some designs (flip-flops Odin names after a primary output are labelled from the spec); measured values are reported.
* Run records: 798 `mimir-run.json`, `norns_source_clean` true (scripts committed before the batch). Near-critical data: `--timing_report_npaths 1000`, setup report kept per run, imported with `mimir import-timing --report --requested 1000` (342 exhaustive, 456 report-basis runs, 0 truncated). Store `work/mimir-data/h22.db`, `mimir privacy-check`: 0 hits.
* Raw runs (22 GB), logs and records: `/home/jamiespa/odin3-ws/work/norns-h22-out/` (`runs/`, `data/`, `pipeline.log`), outside the worktree; committed copies: `data/r8/` and `data/analysis/r8-results.json`. Scripts: `gen/r8gen.py`, `scripts/r8.py`, `scripts/r8stats.py`.
