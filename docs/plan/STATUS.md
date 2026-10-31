# Norns III status: closed 2026-10-31 (negative results)

Norns III closed on 2026-10-31 (Peter, dictated: "finish a write-up of the Norns and shut down that path"). No packing or
placement change tried here gave a speed, wirelength or area gain that stands apart from noise. The measured room (the
known-optimum yardstick, round 9 and H38; the gap anatomy of Q-N2; the seed oracle of Q-N1b) stands. The paper
(`docs/paper/norns.tex`, PDF `docs/paper/build/norns.pdf`) is the final write-up; `docs/paper/hypotheses.md` is the
register and the source of every number (88 rows: 15 useful, 10 possibly good, 27 inconclusive, 25 dismissed, 11
measurements; 10 untested ideas U1 to U10).

## Experiments, PRs and headline (geomean percent win; W/L/T; speed, WL, area; register verdict)

The CAD headline of every change is Table `tab:tried` of the paper (Summary of What Was Tried). In short:

| experiment | register ID | plan | PR | verdict |
|---|---|---|---|---|
| Known-optimum yardstick from real designs, 33 designs | H38 | `docs/plan/round9-tpeko-real.md` | #26, #30, #31 | useful (room in CLBs and wire; delay inconclusive) |
| Heap studies | CH-a to CH-d, HP-1 to HP-4 | `docs/plan/critical-heap.md`, `heap-picking.md` | #24, #25 | measurements |
| Refresh criticality while packing | H-refresh k=1, k=8 | `docs/plan/refresh-crit.md` | #27 | inconclusive, dismissed |
| HDL-aware packer, realistic registers | H22' | `docs/plan/round8-h22.md` | #19 | dismissed (WL 65% to 150% worse) |
| Seed-order gap (seed rule) | H-seed | `docs/plan/hs0-seed-gap.md` | #32, #33 | inconclusive |
| True seed oracle | H-seed-b, H-seed-b2 | `docs/plan/q-n1b-true-seed-oracle.md` | #34 | possibly good in WL and area, speed inconclusive; strong form dismissed |
| Where the packer departs from the known clustering | Q-N2 | `docs/plan/q-n2-appack-gap.md` | #35 | measurement |
| Ranking the right atom | Q-N3 | `docs/plan/q-n3-rank-right-atom.md` | #37 | measurement |
| 2-hop gain term | H-2hop-0.1, H-2hop-0.25 | `docs/plan/q-n3b-2hop-gain.md` | #38 | inconclusive, dismissed |
| Schabas spare room | H-spare-2, -2W, -4, -4W | `docs/plan/q-n5-schabas-spare.md` | #39 | inconclusive, dismissed |
| Duplication after placement | H-dup, H-dup-W, H-dup-spare, H-dup-spare-W | `docs/plan/q-n6-duplication.md` | #40 | dismissed (fixed width); setting-a gains withdrawn as selection |

Earlier rounds (seeding baseline R1, rounds 2 to 8, E10 option sweep) are rows of the register with their plan files in
`docs/plan/`; PR numbers for them are in the git history.

## Archive locations (off-machine, SHA256 verified, never deleted)

Run roots are under `/mnt/f/yggdrasil-archive/<date>/` (Windows F: drive); the index is
`/mnt/f/yggdrasil-archive/README.md`. Norns entries:

- `2026-10-27/`: Norns runs (seven tarballs `norns-runs-<group>.tar.xz`) and the Norns placers raw runs
  (`norns-placers-*.tar.xz`), with manifests.
- `2026-10-30/norns-refresh-out`, `2026-10-30/norns-h22-out`: H-refresh (315 runs) and the H22' re-run (756 runs).
- `2026-10-30/hs0-out`: HS0 (990 arm runs).
- `2026-10-30/r9-out-v1`: round 9 v1 run root (pilot and first full pass before the D' loop fix).
- `2026-10-30/q5-out`, `2026-10-30/q3b-out`, `2026-10-30/q6-out`: Q-N5, Q-N3b, Q-N6.
- `2026-10-29/mimir-excel`: the Mimir overview workbook with the Norns rounds.

Not found in the archive README at close (check before relying on them): the Q-N1b run root (the committed pooled
summary is `data/n1b/summary.json`), and the final round 9 run root (committed summaries `data/r9/`). Restore pattern:
`xz -dc X.tar.xz | tar -x -C <parent>`; see the README entry for the parent directory of each.

## Parked, not run

1. A timing-aware yardstick (a known-optimal timing clustering, as TPEKO did for placement).
2. The Loki L3 to packer-hints bridge.
3. Seed-split duplication.
4. The untested ideas U1 to U10 of the register.

## How to reopen

1. Read `docs/paper/hypotheses.md` and the paper's Summary of What Was Tried; do not re-run what is listed there.
2. Restore the needed run root from the archive (above) if raw runs are needed; committed summaries are under `data/`.
3. Write a dated plan in `docs/plan/` before any run (hypothesis, gate, verdict rule, CAD headline in the order
   speed, WL, area); a positive geomean whose interval touches 1 is inconclusive, not dismissed.
4. Add the result to the register, run `python3 docs/paper/check_register.py` and
   `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex`, rebuild the PDF.
