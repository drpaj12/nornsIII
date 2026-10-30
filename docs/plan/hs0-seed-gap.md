# HS0: is there a seed-order gap? (Q-N1; plan written 2026-10-30, before the arm runs)

This file is committed and pushed before any HS0 arm run (stock, oracle or random). It is not edited after the runs; the results are
appended below under their own dated heading. The overlay option and the byte-identical gate are made before this plan is
committed; the gate is not an arm run.

## Plain-English summary

A greedy packer builds one cluster at a time. It picks a seed atom, grows the cluster around it by a gain, closes it, and picks the
next seed. Stock VPR orders its seeds by timing criticality (and some size tie-breaks). Round 9 showed that stock needs about 10 percent
more CLBs than the number N_C of clusters of a known clustering C, on 33 real designs made into known-optimum yardsticks. The question
here (Peter, 2026-10-30) is one question only: is there a gap between stock VPR's seed order and better seed orders? If a better order
exists, a later question (Q-N2) asks what data predicts it; if not, that question does not start.

We give the packer a list of seeds and watch what happens, on the same 33 designs and the same three VPR seeds. Three kinds of seed order
are compared with stock: (1) the oracle: one seed per cluster of the known clustering C, so the packer starts a cluster exactly where
the answer says a cluster is (it still grows each one by its own gain, so this tests the seed CHOICE, not the growth); (2) eight random
atom orders, from which we report the best of eight (optimistic, because it picks the winner after seeing the results) and the median of
eight (an honest typical random order); and (3) stock itself. The gap of an arm is stock divided by the arm, per design, pooled over
designs. A ratio above 1 means the arm is better than stock. The gap "exists" only if the pooled ratio is above 1 with a Holm-adjusted p
below 0.05 and a 90 percent interval that excludes 1.

Purpose (hub docs/purpose.md): Norns, packing quality (area, speed). Research question Q-N1 (seed-order gap) feeding N Q1.6 (room in the
packer). Measures: CLBs (primary), wirelength (WL), critical-path delay (CPD) per design.

## Hypothesis

Proposed, to be confirmed by Peter (his wording is pending): "Seed order matters: a better seed choice gives fewer CLBs and lower WL/CPD
than stock."

## Overlay

Options added to the Norns packer (packer/vpr, one new VTR-side change; nothing removed):

* `--norns_seed_list FILE`: FILE holds atom names, one per line. The next seed is the molecule of the first not yet clustered atom of
  FILE; when FILE is exhausted, or empty, or the option is absent, the next seed is stock's (the sorted seed list, RAM first). Names that
  match no atom are skipped and counted in the log line `Norns seed list: <entries> entries, <unmatched> unmatched, <molecules> distinct
  molecules`. The seed is a molecule (a LUT with its flip-flop, an adder chain, a hard block), so any atom of a molecule selects it.
* `--norns_seed_dump FILE` (log-only): writes stock's seed order after the sort, one molecule per line: position, then the atom names of
  the molecule, tab separated. Used to order the clusters of the oracle by stock's own seed order.

Gate (before the arm runs, `scripts/hs0run.py gate`): the `.net` is byte-identical to the stock `.net` with the option absent and with an
empty FILE plus the dump option, on the 15 VTR designs (reference: the keep-sweep E10 base runs, seed 1, pack-only with 1000 timing
paths, as the critical-heap gate) and on 5 round 9 D' (ch_intrinsics, stereovision3, diffeq2, diffeq1, clma; VPR seeds 1 to 3; reference:
the round 9 stock `.net`). Result in the results section.

## Arms and measures

Units: the 33 round 9 D' (own clustering C, the ordered file sh0: atoms in the file cluster by cluster, the names are the round 9 tokens;
the read-only builds under work/r9-out-v2), VPR seeds 1, 2, 3. Flow and architecture as round 9 (VTR 3c9a4d23b2,
`k6_frac_N10_frac_chain_mem32K_40nm`, the default analytic flow, `--timing_report_npaths 100`); the packer is the HS0 build of the Norns
overlay, one binary for every arm, built in work/norns-vtr-hs0. The place and route files are written to /dev/null (they are not needed);
the `.net`, `vpr.out` and `metrics.json` are kept per run in work/hs0-out.

* stock: no list (the stock arm re-run on the HS0 binary, with the dump option).
* oracle: the list holds one atom per cluster of C. The atom of a cluster is the vertex with the most nets of H* that also touch another
  vertex of the same cluster (ties: the lower vertex index), and the first atom of that vertex. The clusters are listed in stock's own seed
  order: a cluster is placed at the earliest position, in the dump of the stock run with the same VPR seed, of any of its atoms (clusters
  with no atom in the dump last, by cluster number). After the list is used up the packer takes stock's order (pads, hard blocks, leftovers).
  Seeds of the list come before stock's RAM-first seeds. The packer still grows each cluster by its gain (the Norns affinity is off).
* random: R = 8 orders; order r is a permutation of the atoms of the affinity file (the atoms of C) made by Python `random.Random(2026103000 + r)`
  (shuffle of the file order), the same eight orders for the three VPR seeds. Fixed seeds, nothing drawn after seeing results.
* Order of work: smallest design first (by the size of the written file), all arms of a design before the next design.

Measures per run: logic CLBs (the `.net`), total wirelength and critical-path delay from the VPR log (as round 9). Memory cap 14 GB; the
disk guard reads /mnt/c before each design and stops below 15 G; the weekly meter stops the work at 97. A failed run (rc not 0) is
listed; a design-and-seed pair is used only if every arm has a result for it.

## Statistics and the rule

* Gap of an arm per design: the geometric mean over the VPR seeds of stock / arm, per metric. For best-of-8, per VPR seed the best
  (smallest) of the 8 random values of that metric (each metric picks its own best); for median-of-8, per VPR seed the median of the 8
  values (the geometric mean of the two middle values).
* Pool: geometric mean over designs, 90 percent bootstrap interval over designs (10000 resamples, seed 20261030, percentile), two-sided
  bootstrap p, Holm over the nine tests (oracle, best-of-8, median-of-8) x (CLB, WL, CPD).
* Verdict per test: "gap exists" (POSSIBLY GOOD, the register label) only if the Holm p is below 0.05 and the interval excludes 1 with the
  ratio above 1 (Peter, 2026-10-29). A significant ratio below 1 is reported as REVERSED (the arm is worse than stock). Everything else is
  INCONCLUSIVE. The answer to Q-N1 is "yes" if at least one test meets the rule. Best-of-8 is optimistic by selection and counts only
  with the chance-only reference below, and the oracle and the median-of-8 are the tests without selection.
* Chance-only reference for best-of-8: best-of-8 beats a typical random order by selection alone. The geometric mean over designs and VPR
  seeds of (geometric mean of the 8 values) / (best of the 8) is the expected size of that selection effect under the median spread: if
  stock were just another random order, stock / best-of-8 would be near this number. It is reported next to the best-of-8 gap, and a
  best-of-8 gap is read as evidence only to the extent it exceeds it.
* Against N_C (CLB): stock / N_C, oracle / N_C, best-of-8 / N_C and median-of-8 / N_C, geometric mean over designs with a 90 percent
  interval, for N_C as in round 9 (the build's cluster count) and for the corrected N_C (counting bound on the netlist VPR packed, round 9
  entry 2026-10-30 (b)). The share of the stock-to-N_C gap that seed order explains is (log stock/N_C - log arm/N_C) / log stock/N_C.
* Sensitivity: the same pool without clma (round 9 outlier, N_C below VPR's cluster count).

## What this cannot show

The oracle uses the answer key C, so its gap is an upper bound on what a seed rule built from data could give, for this seed choice rule
and this growth. A different atom rule inside each cluster may do better or worse. A gap in CLBs does not say where the packer goes wrong
(Q-N2 asks that). The 33 designs are the round 9 set, own clustering only.

## Results, 2026-10-30

Plain English first. On the 33 round 9 designs there is no seed-order gap that this experiment can show. Giving the packer the answer key's
seeds (the oracle: one seed per known cluster) saves 0.7 percent of the CLBs (stock/oracle 1.007, 90 percent interval [1.000, 1.014],
Holm p 0.69) and does not change wire or delay. A typical random seed order is as good as stock (median of eight: CLB 0.997, WL 0.995,
CPD 0.997), so stock's order is not worse than chance. The best of eight random orders beats stock by 1.2 percent in CLBs, 4.8 percent in
wire and 4.5 percent in delay, and passes the literal rule, but that is what picking the best of eight does by itself: the chance-only
reference (mean of the eight over the best of the eight) is 1.017, 1.052 and 1.049, larger than the observed best-of-eight gaps, so
best-of-eight carries no evidence of a gap. The roughly 10 percent excess of stock over N_C that round 9 measured is therefore not
a matter of which atom the packer seeds next, with this seed rule and this growth: the oracle closes 6 percent of the log gap to N_C
(stock/N_C 1.118, oracle/N_C 1.110). Q-N2 (what data predicts the gap) has no gap to explain here and does not start on this evidence.

Hypothesis (proposed, to be confirmed by Peter): "Seed order matters: a better seed choice gives fewer CLBs and lower WL/CPD than stock."

Experiment as planned above: 33 designs, own C, ordered file, VPR seeds 1 to 3, arms stock, oracle, 8 random orders; 990 runs, all rc 0
(`data/hs0/runs.jsonl`, pooled in `data/hs0/summary.json`, `python3 scripts/hs0run.py pool`). Gate: 30 of 30 byte-identical in both
conditions (`data/hs0/gate.json`; a first attempt at the round 9 D' used pack-only runs, which do not use APPack and so differed from the
analytic-flow reference; the gate was rerun with the full flow).

| test | stock / arm CLB | WL | CPD |
|---|---|---|---|
| oracle | 1.0068 [0.9997, 1.0144] p 0.69 | 1.0067 [0.9959, 1.0180] p 1.0 | 0.9920 [0.9803, 1.0038] p 1.0 |
| best-of-8 (optimistic) | 1.0121 [1.0056, 1.0183] p 0.032 | 1.0483 [1.0375, 1.0597] p < 0.0001 | 1.0450 [1.0339, 1.0571] p < 0.0001 |
| median-of-8 | 0.9967 [0.9904, 1.0033] p 1.0 | 0.9951 [0.9867, 1.0032] p 1.0 | 0.9974 [0.9881, 1.0063] p 1.0 |
| chance-only reference (mean of 8 / best of 8) | 1.0172 [1.0148, 1.0194] | 1.0523 [1.0441, 1.0616] | 1.0495 [1.0413, 1.0587] |

(Geometric mean over 33 designs, 90 percent bootstrap interval over designs, Holm over the nine tests.) Without clma the numbers move
by at most 0.001 (oracle CLB 1.0067, best-of-8 CLB 1.0118).

Against N_C (CLB, geometric mean over designs, 90 percent interval): stock/N_C 1.118 [1.088, 1.159] (corrected N_C 1.113 [1.086, 1.149]);
oracle/N_C 1.110 [1.082, 1.150] (1.105 [1.080, 1.140]); best-of-8/N_C 1.105 [1.074, 1.145] (1.100 [1.073, 1.133]); median-of-8/N_C 1.122
[1.091, 1.163] (1.117 [1.089, 1.152]). The oracle explains 6 percent of the log gap of stock to N_C and best-of-8 11 percent, and the best-of-8
share is selection (it is chance-only reference sized). The stock/N_C here (1.118) is on the ordered file only; round 9 pooled the three
shuffles (1.103 corrected).

Per design the oracle CLB gap ranges from 0.966 (ex5p) to 1.087 (stereovision3); the largest gains are on the smallest designs
(stereovision3 1.087, ch_intrinsics 1.071, diffeq2 1.057).

Verdict. The literal rule is met by the three best-of-8 tests (Holm p 0.032, < 0.0001, < 0.0001), and by none of the oracle or
median-of-8 tests. By the plan's reading, best-of-8 counts only above the chance-only reference, and it is below it in all three metrics, so
Q-N1 is answered NO: no seed-order gap shown. This is a result for one oracle seed rule (the vertex with the most internal nets per
known cluster, clusters in stock's seed order) with stock's growth; another rule could do better. Register: H-seed DISMISSED.
