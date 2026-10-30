# Q-N1b: is there a seed choice that makes stock VPR's growth rebuild the known clustering? (plan written 2026-10-30, before the runs)

This file is committed and pushed before any Q-N1b arm run. It is not edited after the runs; results are appended below under
their own dated heading. The overlay option and the byte-identical gate are made before the plan is committed; the gate is not an arm run.

## Plain-English summary

HS0 (docs/plan/hs0-seed-gap.md) asked whether a better seed order closes the gap between stock VPR and the known-optimum clustering C of
the 33 round 9 designs. Its "oracle" picked one seed per cluster of C by a RULE (the atom with the most internal nets) and found almost no
gap (CLB stock/oracle 1.007). Peter (2026-10-30): "the seed oracle (not really an oracle though since it's using the rule to pick ...) -
a real oracle should have the Tpeko Cluster and pick the atom that will result in the exact clustering happening (maybe calculatable)."

So this experiment builds the real oracle. The packer is given C. Whenever it opens a new cluster it takes the next not yet finished cluster
of C, and for every atom (molecule) of that cluster it grows a TRIAL cluster from that atom with VPR's own gain, attraction and legality, in the
current packing state, and then undoes the trial. It commits the seed whose trial gave exactly the cluster of C; if no seed does, the seed whose
trial overlaps C most (Jaccard). The packer then grows that cluster again for real. This tests the seed CHOICE with the best possible choice
rule available (try them all) and stock's growth. Two outcomes are informative. If most clusters of C can be rebuilt exactly from some seed and
the CLB count drops towards N_C, the gap was in the seeds. If most clusters cannot be rebuilt exactly from any seed, the gap is in the growth
(gain and closing), not in seeding, and no seed rule can close it.

Purpose (hub docs/purpose.md): Norns, packing quality (area, speed). Research question Q-N1 (seed-order gap), refined after HS0, feeding N Q1.6
(room in the packer). Measures: CLBs (primary), wirelength (WL), critical-path delay (CPD); per cluster, rebuilt exactly (yes/no) and best
Jaccard; oracle/N_C next to stock/N_C.

## Hypothesis (Peter's, in testable form)

"For most known clusters there is a seed atom from which stock VPR's growth rebuilds the cluster exactly; seeding with it closes most of
the area gap to N_C."

## Feasibility of trial growth with rollback (checked in the code before writing this plan)

Feasible without touching the legalizer. `GreedyClusterer::try_grow_cluster` already has a rollback path: when a grown cluster has no legal final
routing it calls `ClusterLegalizer::destroy_cluster`, `compress` and decrements `num_used_type_instances`, and the main loop retries the same seed
with the FULL strategy. The trial uses exactly that sequence after a successful growth (`try_grow_cluster` returns before
`update_candidate_selector_finalize_cluster` and `clean_cluster` while a trial flag is set). All other state is per cluster (`ClusterGainStats`)
or read-only during growth. The one persistent mutable state in the candidate selector is its random generator, used only with attraction
groups; the option stops with an error if attraction groups exist (and with `--norns_seed_list` or `--norns_refresh_crit`). A self-check
counts the committed clusters whose atom count differs from the trial that chose them (`recheck_mismatch`, must be 0). The stock seed that
opened the step is put back into the stock seed order if the committed cluster did not absorb it, so every molecule is still packed.

## Overlay

Option `--norns_seed_oracle FILE` (FILE = lines `atom name TAB cluster id`, the known clustering C; here the round 9 ordered file `affinity.tsv`).
Absent: stock code path. Present, per new cluster:
1. s = the next stock seed (stock order, as HS0). If no atom of s is in C, or its C cluster was already handled, commit s (stock).
2. Otherwise mark the C cluster c handled. Candidates = distinct unclustered molecules of the atoms of c that can start the same block type as s,
   in ascending root-atom id (the fixed order). Trial each; stop at the first trial whose cluster atom set equals c. Else take the best Jaccard
   (ties: fewer outsiders, then the earlier candidate in the fixed order).
3. Log one line `NORNS_ORACLE c candidates trials exact jaccard outsiders missing |c|` per handled cluster, and a summary line.
4. When the oracle's clusters are done, leftover atoms pack by stock.
Here c is the set of atoms of c that exist in the netlist VPR packs (buffer LUTs absorbed by the prepacker, etc., are skipped); "exact"
means the trial's atoms equal c, "outsiders" are trial atoms not in c, "missing" are atoms of c not in the trial (including atoms already packed in
earlier clusters).

Gate (before the arm runs, `scripts/n1brun.py gate`, wrapper of the HS0 gate): option absent -> `.net` byte-identical to the reference on the 15 VTR
designs (keep-sweep E10 base, seed 1, pack-only with 1000 timing paths) and on 5 round 9 D' (ch_intrinsics, stereovision3, diffeq2, diffeq1,
clma; VPR seeds 1 to 3; round 9 stock `.net`, full flow). Result in the results section.

## Arms and measures

Units: the 33 round 9 D' (own C, the ordered shuffle sh0), VPR seeds 1, 2, 3; flow and arch as HS0 (VTR 3c9a4d23b2, `k6_frac_N10_frac_chain_mem32K_40nm`,
default analytic flow, `--timing_report_npaths 100`, place and route files to /dev/null). Smallest design first.
* stock: the HS0 stock runs (data/hs0/runs.jsonl) are reused if the gate shows the new binary reproduces stock `.net` byte for byte (the new code is
  inert without the option; the gate is on the reference `.net` files of stock); otherwise stock is re-run.
* oracle: `--norns_seed_oracle` with C.
Per run kept: `metrics.json`, the oracle log (`NORNS_ORACLE` lines), `.net` gzipped, `vpr.out` gzipped.

## Statistics and the rule

* Gap per design: geometric mean over VPR seeds of stock / oracle for CLB, WL, CPD. Pool: geometric mean over designs, 90 percent bootstrap interval
  over designs (10000 resamples, seed 20261030), two-sided bootstrap p, Holm over the 3 metrics.
* Exact rebuild: share of handled clusters rebuilt exactly, per design and pooled over all runs; Jaccard distribution (quantiles) over clusters.
* Against N_C: stock/N_C and oracle/N_C (CLB, geometric mean over designs with a 90 percent interval; as round 9 and corrected N_C).
* Verdict. "Gap closed by seeds" (POSSIBLY GOOD) only if the CLB test has Holm p < 0.05, the interval excludes 1 (ratio above 1), AND oracle/N_C is closer to
  1 than stock/N_C by at least half of the log gap: log(stock/N_C) - log(oracle/N_C) >= 0.5 log(stock/N_C). A significant ratio below 1 is REVERSED. Else
  INCONCLUSIVE or, with a pooled exact share below one half, "gap is in growth, not seeding". The wording says plainly which.

## What this cannot show

The trial uses the cluster-by-cluster state of the packing, so a cluster that is not exact because earlier clusters took some of its atoms counts as
not rebuilt; this is part of the question (does stock plus the best seed rebuild C). Seeds are restricted to atoms of c; a seed outside c is not
tried. Weights of the weekly meter stop the work at 100.

## Results, 2026-10-30

Plain English first. Giving stock VPR the answer key as a true seed oracle (try every atom of the next known cluster as seed, keep the one whose
growth rebuilds the cluster) rebuilds only about a quarter of the known clusters exactly (25.5 percent of 3 x 33 designs' clusters; mean Jaccard
0.61, median 0.62; quartiles 0.35 and 1.0, the 5th percentile 0.11). So for most
known clusters NO seed makes stock's growth rebuild the cluster: the gap to the known optimum is mainly in growth (gain and closing), not in
seeding. The best seeds do help a little: wirelength is 2.8 percent lower, area (CLBs) 1.2 percent lower, delay no better (0.7 percent
worse, not significant). They close 11 percent of the log gap to N_C (stock/N_C 1.118, oracle/N_C 1.105), far from half.

Hypothesis (Peter's): "For most known clusters there is a seed atom from which stock VPR's growth rebuilds the cluster exactly; seeding with it
closes most of the area gap to N_C." Experiment as planned above: 33 designs x 3 VPR seeds, 99 oracle runs (all rc 0; `data/n1b/summary.json`,
`python3 scripts/n1brun.py pool`), stock = the HS0 stock runs (reused after the gate: the new binary reproduces stock `.net` 30 of 30 with the option
absent; gate `data/n1b/gate.json`). Trial growth with rollback was feasible (see above); `recheck_mismatch` = 0 on all 99 runs (every committed cluster has the
atom count of the trial that chose it). Statistics: per design the geometric mean over the 3 VPR seeds of stock/oracle; pooled geometric mean over
designs, 90 percent bootstrap over designs, Holm over the 3 metrics; wins and losses count designs where stock/oracle is above or below 1.

Reported per metric, speed first (T-VPack, marquardt99cluster, also judged packing on speed and density):

| metric (stock / oracle, above 1 = oracle better) | geomean (percent) | 90% CI | Holm p | wins / losses / ties of 33 | median | 10th - 90th percentile | label |
|---|---|---|---|---|---|---|---|
| speed: critical-path delay | 0.9928 (-0.7%) | [0.9826, 1.0035] | 0.253 | 13 / 20 / 0 | 0.990 | 0.964 - 1.021 | INCONCLUSIVE |
| wirelength | 1.0280 (+2.8%) | [1.0171, 1.0397] | < 0.0001 | 25 / 8 / 0 | 1.029 | 0.996 - 1.069 | POSSIBLY GOOD |
| area: CLB count | 1.0120 (+1.2%) | [1.0055, 1.0189] | 0.0052 | 23 / 6 / 4 | 1.010 | 0.983 - 1.035 | POSSIBLY GOOD |

Per-design stock/oracle, sorted ascending (the sorted tables are also in `data/n1b/summary.json`, `distribution`).
CPD: s38417 0.896, raygentop 0.941, diffeq 0.944, dsip 0.964, s38584.1 0.967, misex3 0.967, mkPktMerge 0.973, diffeq1 0.974, ex5p 0.974, tseng 0.979,
seq 0.983, spla 0.983, elliptic 0.985, blob_merge 0.985, des 0.987, ex1010 0.989, sha 0.990, or1200 0.993, pdc 0.997, clma 0.998, mkSMAdapter4B 1.003,
mkDelayWorker32B 1.006, alu4 1.006, bigkey 1.008, ch_intrinsics 1.011, s298 1.011, boundtop 1.012, diffeq2 1.015, apex2 1.015, frisc 1.021, apex4 1.025,
stereovision3 1.047, stereovision1 1.135.
WL: boundtop 0.954, sha 0.957, mkPktMerge 0.973, raygentop 0.996, clma 0.996, diffeq1 0.997, diffeq 0.997, spla 0.997, mkDelayWorker32B 1.002, dsip 1.009,
bigkey 1.012, pdc 1.012, seq 1.014, elliptic 1.014, frisc 1.019, mkSMAdapter4B 1.024, stereovision1 1.029, or1200 1.029, s298 1.031, apex2 1.032,
ch_intrinsics 1.039, des 1.040, s38584.1 1.043, alu4 1.046, apex4 1.047, blob_merge 1.054, ex5p 1.061, s38417 1.065, diffeq2 1.068, ex1010 1.069,
stereovision3 1.075, misex3 1.079, tseng 1.172.
CLB: boundtop 0.956, alu4 0.979, des 0.982, ex5p 0.982, apex4 0.991, s38417 0.993, ch_intrinsics 1.000, diffeq 1.000, mkPktMerge 1.000, s298 1.000, sha 1.006,
elliptic 1.006, stereovision1 1.006, mkSMAdapter4B 1.006, blob_merge 1.007, apex2 1.008, clma 1.010, raygentop 1.010, dsip 1.013, ex1010 1.014, pdc 1.016,
seq 1.018, s38584.1 1.018, frisc 1.019, diffeq1 1.022, mkDelayWorker32B 1.028, spla 1.028, or1200 1.030, bigkey 1.030, misex3 1.035, stereovision3 1.042,
tseng 1.062, diffeq2 1.088.

Where the gains sit. No clear size trend: the WL and CLB gains appear on small, mid and large designs alike (the two largest, blob_merge and
stereovision1, gain 5 percent WL and 0.6 to 0.7 percent CLB; the largest CPD change, stereovision1 +13.5 percent, is one design). The share of
clusters rebuilt exactly is high on the designs with regular arithmetic or word structure (mkPktMerge 0.82, diffeq2 0.61, mkDelayWorker32B 0.61,
diffeq1 0.51) and lowest on the large-fanout MCNC logic (pdc 0.02, misex3 0.03, spla 0.03, seq 0.04, ex5p 0.00). Pooled exact share 0.255.

Against N_C (CLB, geometric mean over designs): stock/N_C 1.118 [1.088, 1.158] (corrected N_C 1.113 [1.086, 1.148]); oracle/N_C 1.105
[1.076, 1.144] (1.100 [1.074, 1.134]). Share of the log gap to N_C closed: 0.107 (HS0's rule-based oracle: 0.06).

Verdict. The hypothesis is DISMISSED: the exact share is 0.255 (not "most"), and the CLB gap to N_C is closed by 11 percent, not "most" (rule: half). Per
metric, as reported above: wirelength and area show small significant gains (POSSIBLY GOOD, 2.8 and 1.2 percent), delay is INCONCLUSIVE. The gap
to the known optimum is mainly in growth (gain and closing), not seeding. A different growth, not a different seed rule, is where room remains. No
follow-up question was started.
