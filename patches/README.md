# VTR patch-set

Additive, default-off changes against the pinned VTR build (v8.0.0+18416-g3c9a4d23). Stock VPR
behaviour is byte-identical when the flags are unused. Expected:

- `--place_checkpoint` (or equivalent): save-best/restore in the anneal loop, default off.

The pinned build already provides `--read_initial_place_file`, `--read_vpr_constraints` and
`--write_initial_place_file`, which the experiment uses unpatched.
