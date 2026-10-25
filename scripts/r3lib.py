"""Round-3 shared helpers: packings from flat placements, labels, purity, split factor, null.

A packing is read from a VPR flat placement (``final.flat_place``: atom -> CLB id, atom pb type).
Labels: module (Odin III provenance module path), word (round-2 membership), io (Stage 3).
Purity and split-factor definitions are in docs/plan/round3.md ("Common definitions").
"""

from __future__ import annotations

import collections
import math
import random
import statistics
from pathlib import Path
from typing import Any

import build_seeds as bs
import nornlib as nl

NULL_SAMPLES = 50
WORD_SHARE = 1 / 3  # the 1/3-atoms rule of round 2 (build_word_seeds.WORD_SHARE)


def clb_atoms_of(flat_path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """(CLB id -> atoms, CLB id -> class pad/memory/mult/logic) of a flat placement."""
    flat = nl.Flat(flat_path)
    atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        atoms[row[4]].append(atom)
    cls = {clb: bs.classify(t) for clb, t in flat.clb_types().items()}
    return dict(atoms), cls


def logic_groups(flat_path: Path) -> dict[str, list[str]]:
    atoms, cls = clb_atoms_of(flat_path)
    return {c: sorted(a) for c, a in atoms.items() if cls.get(c) == "logic"}


def module_labels(atoms: list[str]) -> dict[str, str]:
    return {a: nl.module_of(a) for a in atoms if nl.module_of(a)}


def word_labels(design: str, atoms: list[str]) -> dict[str, str]:
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    return {a: members[a]["word"] for a in atoms if a in members and members[a]["word"]}


def purity(groups: dict[str, list[str]], label: dict[str, str]) -> dict[str, float]:
    """Plurality share (sum of plurality counts / labelled atoms, CLBs with >= 2 labelled atoms),
    the fraction of those CLBs that are strictly pure, and how many CLBs count."""
    plur = tot = pure = n = 0
    for atoms in groups.values():
        c = collections.Counter(label[a] for a in atoms if a in label)
        k = sum(c.values())
        if k < 2:
            continue
        n += 1
        plur += max(c.values())
        tot += k
        pure += 1 if len(c) == 1 else 0
    return {"share": plur / tot if tot else float("nan"),
            "strict": pure / n if n else float("nan"), "n_clbs": n}


def split_factor(groups: dict[str, list[str]], label: dict[str, str]) -> dict[str, float]:
    """Spanned CLBs / ceil(n / m) per label with n >= 4 atoms in logic CLBs (m = the largest
    number of atoms in a logic CLB). Median over labels and the atom-weighted median."""
    m = max((len(a) for a in groups.values()), default=1)
    span: dict[str, set[str]] = collections.defaultdict(set)
    count: collections.Counter = collections.Counter()
    for clb, atoms in groups.items():
        for a in atoms:
            if a in label:
                span[label[a]].add(clb)
                count[label[a]] += 1
    vals = []
    weights = []
    for lab, n in count.items():
        if n >= 4:
            vals.append(len(span[lab]) / math.ceil(n / m))
            weights.append(n)
    if not vals:
        return {"median": float("nan"), "wmedian": float("nan"), "n_labels": 0}
    return {"median": statistics.median(vals), "wmedian": weighted_median(vals, weights),
            "n_labels": len(vals)}


def weighted_median(vals: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(vals, weights))
    half = sum(weights) / 2
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def null_groups(groups: dict[str, list[str]], rng: random.Random) -> dict[str, list[str]]:
    """The same atoms assigned at random to CLBs of the same sizes."""
    ids = sorted(groups)
    atoms = [a for c in ids for a in groups[c]]
    rng.shuffle(atoms)
    out: dict[str, list[str]] = {}
    i = 0
    for c in ids:
        n = len(groups[c])
        out[c] = atoms[i:i + n]
        i += n
    return out


def null_stats(groups: dict[str, list[str]], label: dict[str, str], seed: int,
               samples: int = NULL_SAMPLES) -> dict[str, Any]:
    rng = random.Random(seed)
    shares, stricts, splits = [], [], []
    for _ in range(samples):
        g = null_groups(groups, rng)
        p = purity(g, label)
        shares.append(p["share"])
        stricts.append(p["strict"])
        splits.append(split_factor(g, label)["median"])
    return {"share": statistics.mean(shares), "share_sd": statistics.pstdev(shares),
            "strict": statistics.mean(stricts), "split": statistics.mean(splits),
            "samples": samples}


def design_purity(design: str, flat_path: Path, levels: tuple[str, ...] = ("word", "module"),
                  extra: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Purity and split factor of one packing at the requested label levels."""
    groups = logic_groups(flat_path)
    atoms = [a for v in groups.values() for a in v]
    out: dict[str, Any] = {"logic_clbs": len(groups), "logic_atoms": len(atoms)}
    labs = {"word": word_labels(design, atoms), "module": module_labels(atoms)}
    labs.update(extra or {})
    for lev in levels:
        lab = labs[lev]
        out[lev] = {**purity(groups, lab), "split": split_factor(groups, lab)["median"],
                    "wsplit": split_factor(groups, lab)["wmedian"],
                    "labelled": sum(1 for a in atoms if a in lab),
                    "n_labels": len(set(lab.values()))}
    return out
