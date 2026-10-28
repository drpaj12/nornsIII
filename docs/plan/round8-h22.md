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
