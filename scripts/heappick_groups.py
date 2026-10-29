"""Heap-picking lane, P8: HDL words and how tightly their bits are tied by dataflow in the netlist (before packing), and what the stock
packer did with them.

Words come from two Odin III sources. `odin`: the word of an atom in a reported path (module/word, bit; the Odin III attribution, only for
atoms in the 1000-path report, so a sample of the design's words). `port`: a top-level bus `name[i]`: the logic atoms next to its pad
bits (consumers of an input bit, driver of an output bit). The module level is not measurable: every one of the 15 designs is one module.
"""
from __future__ import annotations

import collections
import math
import random
import re

import heap_lib as hl
import heappick_lib as pl

BUS = re.compile(r"^(.+)\[(\d+)\]$")
MIN_BITS = 8
PAIRS = 4000


def port_words(g):
    """{('in'|'out', bus): [atoms]} of the logic atoms next to the pad bits of each top-level bus (>= MIN_BITS bits)."""
    na, al = g["net_atom"], g["alias"]
    consumers = collections.defaultdict(set)
    for a, (_k, ins) in g["comb"].items():
        for n in ins:
            consumers[hl._resolve(n, al)].add(a)
    for q, dnet in g["seq"].items():
        consumers[hl._resolve(dnet, al)].add(q)
    words = collections.defaultdict(set)
    for n in g["pis"]:
        m = BUS.match(n)
        if m:
            words[("in", m.group(1))] |= consumers.get(n, set())
    for n in g["pos"]:
        m = BUS.match(n)
        if m:
            d = na.get(hl._resolve(n, al))
            if d is not None:
                words[("out", m.group(1))].add(d)
    bits = collections.Counter()
    for n in list(g["pis"]) + list(g["pos"]):
        m = BUS.match(n)
        if m:
            bits[m.group(1)] += 1
    return {k: sorted(v) for k, v in words.items() if bits[k[1]] >= MIN_BITS}


def odin_words(run):
    """{module/word: [atoms]} from the Odin III attribution of the atoms of this run's reports (>= MIN_BITS atoms)."""
    w = collections.defaultdict(list)
    for a, v in run["atoms"].items():
        if "word" in v:
            w[v["word"]].append(a)
    return {k: sorted(v) for k, v in w.items() if len(v) >= MIN_BITS}


def group_rows(run, ex, loc, R, seed=1):
    """One row per word with >= MIN_BITS logic atoms in clb clusters: ties (flow, any) over all pairs or PAIRS sampled pairs,
    heap rate (share of members in the post-route heap), co-cluster share (pairs in one clb under the stock packer), spread
    (clusters touched / ceil(n / 10))."""
    A = run["atoms"]
    rng = random.Random(seed)
    rows = []
    groups = [("odin", k, v) for k, v in odin_words(run).items()] + [("port", ":".join(k), v) for k, v in port_words(ex["g"]).items()]
    for src, key, atoms in groups:
        mem = [a for a in atoms if a in loc and A.get(a, {}).get("typ") in ("lut", "adder", "ff")]
        n = len(mem)
        if n < MIN_BITS:
            continue
        pairs = pl.sample_pairs(mem, PAIRS, rng)
        flow = anyp = same = 0
        for i, j in pairs:
            f, a = pl.pair_tied(i, j, ex["succ"], ex["pred"])
            flow += f
            anyp += a
            same += loc[i][0] == loc[j][0]
        clbs = len({loc[a][0] for a in mem})
        rows.append({"src": src, "key": key, "n": n, "pairs": len(pairs), "flow": flow / len(pairs), "any": anyp / len(pairs),
                     "co_cluster": same / len(pairs), "heap_rate": sum(1 for a in mem if a in R) / n, "spread": clbs / math.ceil(n / pl.CLB_FLES),
                     "kinds": dict(collections.Counter(A[a]["typ"] for a in mem))})
    return rows
