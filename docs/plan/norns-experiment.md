# The Norns III: does clustering or provenance help placement?

The placement experiment of Yggdrasil III. Research question: does seeding
VPR's simulated anneal from netlist clusters (Loki L2) or from the provenance
hierarchy (Odin III) improve placement, and how hot can the anneal start
before it destroys the seed? Design agreed with Peter 2026-10-23, informed by
RLPlace (Elgammal, Murray, Betz, IEEE TCAD 2022): SA from VTR's analytic
start, RL-chosen move types, and checkpointing to prevent oscillation.

## Repos and code changes

- This repo (nornsIII) holds the VTR patch-set (additive, default-off, so the
  stock flow is untouched), the seed builders, the sweep/retention scripts and
  the runbook, so anyone can rerun the experiment.
- Odin III: zero changes (netlists + provenance already exist).
- Loki: zero changes (L2 already writes the four clusterings and region
  records; k-means at several k is configuration; the quotient-graph layout
  is a script here, not Loki code).
- VTR: pinned build v8.0.0+18416 already provides `--read_initial_place_file`
  (the soft seed), `--read_vpr_constraints` (the hard regions) and
  `--write_initial_place_file` (dump the analytic start). The only likely
  patch is checkpointing (save-best/restore in the anneal loop), default-off.

## Seeds (one arm each)

- Urd: the provenance hierarchy (one region per HDL module, die partitioned
  by a recursive cut of the module graph).
- Verdandi-Louvain, -spectral, -affinity, -kmeans(k = module count, 2x, 4x):
  Loki L2 partitions of the same netlists.
- None: VPR's analytic initial placement (the baseline; dumped and studied).

Inter-cluster layout: contract each cluster to a node, weight by inter-cluster
net cuts, lay the quotient graph out, scale to the die. Intra-cluster: the
seed's own internal order, or shuffled (the inter-cluster-only arm). Full-seed
vs inter-cluster-only pairs answer "where should the clustering start in
placement relative to the other clusters".

## Runs

1. Baseline: each design unseeded, VPR defaults.
2. Each seed, soft (`--read_initial_place_file`) and hard
   (`--read_vpr_constraints`), including the full-vs-inter-cluster-only split.
3. Cold-start calibration: take the best final placement P* across the seeds,
   re-anneal from P* with the initial temperature swept upward; the crossover
   where quality falls to the unseeded baseline is the safe-temperature
   recipe for cluster-derived starts.
4. Hotter-than-safe: every clustered seed at a temperature just above its
   crossover vs unseeded at the same temperature (does the coarse structure
   survive?).
5. Checkpointing arm (the patch, default-off): the same sweeps with
   save-best/restore enabled; prediction from RLPlace: the useful temperature
   range extends.

## Metrics (per run, kept as data)

- Seed retention: fraction of blocks still inside their seed cluster's region
  at exit; mean displacement from the seed coordinate.
- QoR: routed wirelength, critical-path delay, minimum channel width.
- Placement runtime and the per-temperature cost curve (VPR prints it).
- Reports: retention-vs-temperature curves per seed; geomean QoR ratios vs
  unseeded; Urd vs Verdandi comparison; the safe-temperature table.

## Method rules

- Designs: the 15 VTR benchmarks that fit the development machine (the Odin
  paper's set), smallest first; odin3 BLIF in, VPR pack/place/route out.
- One run at a time under the heavy lock, memory under 60% of the machine.
- Keep the data if small, else keep the scripts (Peter's rule); every number
  in the paper traces to a kept record.
- The VTR patch-set: additive flags, default off, stock behavior byte-identical
  when unused; patch notes state the pinned VTR commit.
