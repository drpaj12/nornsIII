"""Round 2 run matrix (VPR, one run at a time under the heavy lock), smallest design first.

  python scripts/round2.py soft  [design ...]   words(full,inter) slices hier words_partial
                                                random urd_shuf, all soft, scale 1
  python scripts/round2.py shuf  [design ...]   <best family>_shuf (coarse-random arm)
  python scripts/round2.py hard  [design ...]   hard arm of the best new family, scale 1
  python scripts/round2.py xover [design ...]   cold-start crossover sweep + the 2S hot step
                                                of the best new family
  python scripts/round2.py best                 print the best new family

The best new family is the one of words, slices, hier, words_partial with the lowest geomean
soft-full wirelength ratio over the designs where all four ran (best_family()). The
crossover sweep reuses round 1's unseeded runs at the same scales; the sweep starts from the
best family's own scale-1 final placement (its P*) and stops where round 1's sweep stopped.
All records go to data/<design>/runs.jsonl like round 1 (arms soft, hard, cold-r2, hot-r2).
"""

from __future__ import annotations

import shutil
import sys

import matrix
import nornlib as nl
import r2_best
import report

NEW = ("words", "slices", "hier", "words_partial")


best_family = r2_best.best_family


def soft_batch(design: str) -> None:
    matrix.baseline(design)
    for seed, variants in (("words", ("full", "inter")), ("slices", ("full",)),
                           ("hier", ("full",)), ("words_partial", ("full",)),
                           ("random", ("full",)), ("urd_shuf", ("full",))):
        for var in variants:
            matrix.soft(design, seed, var)


def shuf_batch(design: str, fam: str) -> None:
    matrix.soft(design, f"{fam}_shuf", "full")


def hard_batch(design: str, fam: str) -> None:
    matrix.hard(design, fam)


def r2_scales(design: str) -> list[float]:
    """Round 1's cold-start scales for this design (the unseeded runs already exist)."""
    path = nl.data_crossover(design, "crossover.json")
    rows = nl.read_json(path)["scales"]
    return [float(r["scale"]) for r in rows]


def xover(design: str, fam: str) -> None:
    src = nl.runs_dir(design, "runs", f"soft-{fam}-full", "final.place")
    if not src.is_file():
        print(f"{design}: no {fam} scale-1 placement")
        return
    pstar = nl.runs_dir(design, "crossover", f"{fam}-r2-Pstar.place")
    shutil.copyfile(src, pstar)
    rows = []
    for scale in r2_scales(design):
        u = matrix.unseeded(design, scale)
        tag = f"cold-r2-{fam}-{scale:g}"
        if matrix.done(design, tag):
            c = nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
        else:
            c = matrix.run_one(design, tag, ["--read_initial_place_file", str(pstar),
                                             "--anneal_auto_init_t_scale", f"{scale:g}"],
                               seed_place=pstar, region_seed=fam, arm="cold-r2", scale=scale)
        rows.append({"scale": scale, "unseeded": u.get("wirelength"),
                     "cold": c.get("wirelength"), "cold_ret": c.get("retention")})
    wins = [r["scale"] for r in rows if r["cold"] and r["unseeded"]
            and float(r["cold"]) < float(r["unseeded"])]
    res = {"design": design, "family": fam, "scales": rows,
           "crossover_scale": max(wins) if wins else None, "wins_all": len(wins) == len(rows)}
    nl.write_json(nl.runs_dir(design, "crossover", f"xover-{fam}.json"), res)
    matrix.keep_sweep(design, f"xover-{fam}.json")
    if res["crossover_scale"] is not None:
        hot_scale = float(res["crossover_scale"]) * 2
        matrix.unseeded(design, hot_scale)
        tag = f"hot-r2-{fam}-{hot_scale:g}"
        if not matrix.done(design, tag):
            matrix.run_one(design, tag, ["--read_initial_place_file", str(pstar),
                                         "--anneal_auto_init_t_scale", f"{hot_scale:g}"],
                           seed_place=pstar, region_seed=fam, arm="hot-r2", scale=hot_scale)
    print(f"{design}: {fam} crossover_scale={res['crossover_scale']}")


def main(argv: list[str]) -> int:
    mode = argv[0]
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    if mode == "best":
        print(best_family())
        return 0
    fam = best_family() if mode != "soft" else None
    if mode != "soft" and fam is None:
        nl.die("no best family yet (run `soft` on every design first)")
    for design in designs:
        if mode == "soft":
            soft_batch(design)
        elif mode == "shuf":
            shuf_batch(design, fam)
        elif mode == "hard":
            hard_batch(design, fam)
        elif mode == "xover":
            xover(design, fam)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
