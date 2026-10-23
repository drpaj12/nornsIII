# The Norns III

The placement experiment of Yggdrasil III: does seeding VPR's simulated anneal from netlist
clusters (Loki III L2) or from the provenance hierarchy (Odin III) improve placement, and how
hot can the anneal start before it destroys the seed?

- `docs/plan/norns-experiment.md` — the experiment design (seeds, injection, the crossover
  sweep, the checkpointing arm, metrics).
- `docs/paper/` — the paper (IEEEtran, Overleaf-uploadable), updated as runs land.
- `patches/` — the VTR patch-set (additive, default-off) so the experiment can be rerun.

Urd uses what the design was (the provenance hierarchy), Verdandi what is recovered now
(Loki III clusters), and Skuld what shall be (the placement they constrain).

Part of [Yggdrasil III](https://github.com/drpaj12/YggdrasilIII). Uses
[Odin III](https://github.com/drpaj12/odin3) and [Loki III](https://github.com/drpaj12/loki).
