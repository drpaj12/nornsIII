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
