"""Round-5 netlist level: the generator's specs written directly as BLIF (no Odin III, no ABC), plus the exactness check
(docs/plan/round5.md entry 2026-10-26 (b)).

  python gen/r5nl.py OUT_DIR [name ...]   write OUT_DIR/n5_*.blif for the named (or all) designs
"""

from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

import r5gen

N_RESTARTS = {4: 500, 8: 300}


def nl_name(hdl_name: str) -> str:
    return "n5_" + hdl_name[len("r5_"):]


def hdl_name(nl: str) -> str:
    return "r5_" + nl[len("n5_"):]


def names() -> list[str]:
    return [nl_name(n) for n in r5gen.names()]


def net_names(spec: dict) -> tuple[dict, dict]:
    """(q net name of (block, ff), l net name of (block, ff)); a flip-flop that drives a primary output is named po[p]."""
    q = {(k, i): f"b{k}_q{i}" for k in range(spec["b"]) for i in range(r5gen.N_LE)}
    for p, (k, f) in enumerate(spec["po"]):
        q[(k, f)] = f"po[{p}]"
    ln = {(k, i): f"b{k}_l{i}" for k in range(spec["b"]) for i in range(r5gen.N_LE)}
    return q, ln


def blif(spec: dict) -> str:
    q, ln = net_names(spec)
    out = [f".model {spec['name']}", ".inputs clk " + " ".join(f"pi[{p}]" for p in range(r5gen.N_PI)),
           ".outputs " + " ".join(f"po[{p}]" for p in range(r5gen.N_PO))]
    for blk in spec["blocks"]:
        k = blk["k"]
        for i, f in enumerate(blk["funcs"]):
            sigs = []
            for a in f["inputs"]:
                if a[0] == "r":
                    sigs.append(q[(k, a[1])])
                else:
                    s = blk["slots"][a[1]]
                    sigs.append(q[(s[1], s[2])] if s[0] == "q" else f"pi[{s[1]}]")
            out.append(".names " + " ".join(sigs) + " " + ln[(k, i)])
            for m in range(64):
                if r5gen.evaluate(f["expr"], [(m >> j) & 1 for j in range(6)]):
                    out.append("".join(str((m >> j) & 1) for j in range(6)) + " 1")
            out.append(f".latch {ln[(k, i)]} {q[(k, i)]} re clk 2")
    out.append(".end")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------
# exactness check at the cell level (a cell = one LUT/FF pair)

def cell_nets(spec: dict) -> tuple[dict, dict]:
    """(net -> set of members, cell -> set of nets). Members are cells (k, i) or pads ('pad', name). The LUT-to-flip-flop
    net inside a pair is internal and is not a net of the cell graph."""
    nets: dict[str, set] = {}
    cells: dict[tuple, set] = {}
    q, _ = net_names(spec)
    for blk in spec["blocks"]:
        k = blk["k"]
        for i, f in enumerate(blk["funcs"]):
            cells.setdefault((k, i), set())
            nets.setdefault(q[(k, i)], set()).add((k, i))
            for a in f["inputs"]:
                if a[0] == "r":
                    n = q[(k, a[1])]
                else:
                    s = blk["slots"][a[1]]
                    n = q[(s[1], s[2])] if s[0] == "q" else f"pi[{s[1]}]"
                    if s[0] == "pi":
                        nets.setdefault(n, set()).add(("pad", n))
                nets.setdefault(n, set()).add((k, i))
    for p in range(r5gen.N_PO):
        nets.setdefault(f"po[{p}]", set()).add(("pad", f"po[{p}]"))
    for n, mem in nets.items():
        for m in mem:
            if m[0] != "pad":
                cells[m].add(n)
    return nets, cells


def cut_value(nets: dict, part: dict, which=None) -> int:
    total = 0
    for n in (nets if which is None else which):
        parts = {part.get(m, m) for m in nets[n]}
        total += len(parts) > 1
    return total


def check(spec: dict) -> dict:
    nets, cells = cell_nets(spec)
    b = spec["b"]
    part = {(k, i): k for k in range(b) for i in range(r5gen.N_LE)}
    base = cut_value(nets, part)
    # (b) move gain: each cell has strictly more nets in common with its own block than with any other single block
    move_bad = 0
    for c, cn in cells.items():
        own = 0
        other: dict[int, int] = {}
        for n in cn:
            blocks = {m[0] for m in nets[n] if m[0] != "pad"}
            if c[0] in blocks:
                own += 1
            for k in blocks - {c[0]}:
                other[k] = other.get(k, 0) + 1
        if other and max(other.values()) >= own:
            move_bad += 1
    # (a) swap test over pairs of cells of block pairs that share a net
    adj: set[tuple[int, int]] = set()
    for mem in nets.values():
        bl = sorted({m[0] for m in mem if m[0] != "pad"})
        for x in bl:
            for y in bl:
                if x < y:
                    adj.add((x, y))
    swap_bad = 0
    pairs = 0
    cur = base
    for rnd_ in range(8):  # first round: count violations; every round applies the improving swaps (local search)
        changed = 0
        for x, y in sorted(adj):
            for i in range(r5gen.N_LE):
                for j in range(r5gen.N_LE):
                    ca, cb = (x, i), (y, j)
                    if part[ca] != x or part[cb] != y:
                        continue
                    aff = cells[ca] | cells[cb]
                    before = cut_value(nets, part, aff)
                    part[ca], part[cb] = y, x
                    after = cut_value(nets, part, aff)
                    if rnd_ == 0:
                        pairs += 1
                        swap_bad += after < before
                    if after < before:
                        cur += after - before
                        changed += 1
                    else:
                        part[ca], part[cb] = x, y
        if not changed:
            break
    res = {"cut": base, "move_violations": move_bad, "swap_violations": swap_bad, "swap_pairs": pairs,
           "cut_local_search": cur, "slack": (base - cur) / base}
    if b in N_RESTARTS:
        res["search_best"], res["search_restarts"] = search(nets, cells, b, N_RESTARTS[b], spec["name"])
        res["search_found_smaller"] = res["search_best"] < base
    return res


def search(nets: dict, cells: dict, b: int, restarts: int, name: str) -> tuple[int, int]:
    """Random balanced partitions improved by steepest pair swaps; the smallest cut found."""
    rnd = random.Random(f"{r5gen.SEED}:search:{name}")
    ids = sorted(cells)
    best = 10 ** 9
    for _ in range(restarts):
        order = ids[:]
        rnd.shuffle(order)
        part = {c: idx // r5gen.N_LE for idx, c in enumerate(order)}
        cur = cut_value(nets, part)
        improved = True
        while improved:
            improved = False
            for _t in range(4 * len(ids)):
                ca, cb = rnd.sample(ids, 2)
                if part[ca] == part[cb]:
                    continue
                aff = cells[ca] | cells[cb]
                before = cut_value(nets, part, aff)
                part[ca], part[cb] = part[cb], part[ca]
                after = cut_value(nets, part, aff)
                if after < before:
                    cur += after - before
                    improved = True
                else:
                    part[ca], part[cb] = part[cb], part[ca]
        best = min(best, cur)
    return best, restarts


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    for n in argv[1:] or names():
        spec = r5gen.build_spec(hdl_name(n))
        text = blif(spec)
        (out / f"{n}.blif").write_text(text, encoding="utf-8")
        print(n, hashlib.sha256(text.encode()).hexdigest()[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
