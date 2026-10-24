# VTR patch-set

Status (2026-10-23): **no patch is needed**. The pinned build v8.0.0+18416 already carries
save-best/restore checkpointing, on by default, gated on the RL agent's late-anneal state:

- `--place_checkpointing {on, off}` (default **on**): `Placer::place()` saves the placement
  checkpoint late in the anneal (`save_placement_checkpoint_if_needed`,
  `vpr/src/place/placer.cpp:384`) and `restore_best_placement` restores it before the quench
  (`placer.cpp:440`). The baseline log prints `Checkpoint saved: bb_costs=... TD costs=...
  CPD=...`.
- It is effective because the pinned defaults also enable the RL agent and its second state:
  `--RL_agent_placement on` and `--place_agent_multistate on` (both default on).
- The experiment's arms are therefore: checkpointing **on** (VPR default, the whole main matrix)
  and checkpointing **off** (`--place_checkpointing off`, the control sweep in
  `scripts/matrix.py checkpoint`).

No VTR source is modified by this repository. The pinned checkout is read-only; nothing was
built into it. The original plan's expected patch was not written because the pinned build
already provides the behaviour, which is the stronger outcome for the paper: the checkpointing
arm is a stock-flag comparison, not a patch comparison.
