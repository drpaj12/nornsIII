"""RQ-N8 (round 3, no VPR): does packing dilute HDL structure?

For each design, on the stock packing of round 1/2 (runs/<d>/runs/baseline/final.flat_place):
purity (plurality share, strict) and split factor at word and module level, against a null
(same CLB sizes, atoms assigned at random, 50 samples), and the split of word-coverage loss into
front end (ABC: atoms with no word; mixed spans vs no match) and packing (word atoms that are not
in a CLB where their word is the plurality word and passes the 1/3 rule).

Usage: python scripts/n8.py [design ...]   writes data/<d>/n8.json and data/analysis/n8.json
"""

from __future__ import annotations

import collections
import sys

import nornlib as nl
import r3lib as r3


def decompose(design: str, groups: dict[str, list[str]]) -> dict[str, float]:
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    atoms = [a for v in groups.values() for a in v]
    unl_mixed = unl_none = word = kept = 0
    for atom in atoms:
        m = members.get(atom)
        if m and m["word"]:
            word += 1
        elif m and m.get("ngroups", 0) >= 2:
            unl_mixed += 1
        else:
            unl_none += 1
    for clb, ats in groups.items():
        c = collections.Counter(members[a]["word"] for a in ats if a in members and members[a]["word"])
        if not c:
            continue
        top, cnt = c.most_common(1)[0]
        if sum(c.values()) / len(ats) >= r3.WORD_SHARE - 1e-9:
            kept += sum(1 for a in ats if a in members and members[a]["word"] == top)
    n = len(atoms)
    return {"atoms": n, "word": word / n, "no_word_mixed": unl_mixed / n,
            "no_word_none": unl_none / n, "word_in_own_clb": kept / n,
            "loss_abc": (unl_mixed + unl_none) / n, "loss_pack": (word - kept) / n}


def run(design: str) -> dict[str, object]:
    flat = nl.runs_dir(design, "runs", "baseline", "final.flat_place")
    groups = r3.logic_groups(flat)
    atoms = [a for v in groups.values() for a in v]
    stock = r3.design_purity(design, flat)
    labs = {"word": r3.word_labels(design, atoms), "module": r3.module_labels(atoms)}
    null = {lev: r3.null_stats(groups, labs[lev], seed=20261024) for lev in labs}
    res = {"design": design, "stock": stock, "null": null, "decompose": decompose(design, groups)}
    nl.write_json(nl.DATA / design / "n8.json", res)
    print(f"{design}: word share {stock['word']['share']:.3f} (null {null['word']['share']:.3f}) "
          f"split {stock['word']['split']:.2f}; module share {stock['module']['share']:.3f}")
    return res


def main(argv: list[str]) -> int:
    allres = [run(d) for d in (argv or list(nl.DESIGN_ORDER))]
    if not argv:
        nl.write_json(nl.DATA / "analysis" / "n8.json", {r["design"]: r for r in allres})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
