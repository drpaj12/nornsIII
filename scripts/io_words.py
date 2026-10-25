"""RQ-N10: I/O words (round 3, no VPR).

A top-level input or output bus ``name[i]`` is an io-word ``io:in:<name>`` / ``io:out:<name>``.
Word identity is propagated inward along bitwise-parallel paths (docs/plan/round3.md):
BFS from each pad bit through LUT and FF atoms only (not adders or other hard blocks), toward
the core (backward from output pads, forward from input pads), K_HOPS = 2 atom hops after the
atom next to the pad, through nets of fanout <= MAX_FANOUT = 16. An atom that already has a
round-2 word keeps it; any other atom gets the io-word iff it is reached from exactly one bit
of that io-word and from no bit of another io-word.

Usage: python scripts/io_words.py [design ...]
Writes runs/<d>/words/iowords.json (atom -> io-word) and data/<d>/iowords.json (summary).
"""

from __future__ import annotations

import collections
import re
import sys

import nornlib as nl

K_HOPS = 2
MAX_FANOUT = 16
BUS = re.compile(r"^(.+)\[(\d+)\]$")


def pad_bits(names: list[str], direction: str) -> dict[str, list[tuple[str, int]]]:
    """io-word -> [(pad net name, bit)] of a pad list."""
    out: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    for n in names:
        m = BUS.match(n)
        if m:
            out[f"io:{direction}:{m.group(1)}"].append((n, int(m.group(2))))
    return {w: bits for w, bits in out.items() if len(bits) >= 2}


def propagate(design: str) -> dict[str, object]:
    parsed = nl.parse_blif(nl.runs_dir(design, "netlist", f"{design}.blif"))
    blocks = [b for b in parsed["blocks"] if b["kind"] in ("lut", "latch")]
    driver = {b["name"]: b["name"] for b in blocks}
    consumers: dict[str, list[str]] = collections.defaultdict(list)
    fanout: collections.Counter = collections.Counter()
    for b in parsed["blocks"]:
        for net in b["inputs"]:
            fanout[net] += 1
            if b["kind"] in ("lut", "latch"):
                consumers[net].append(b["name"])
    inputs_of = {b["name"]: b["inputs"] for b in blocks}
    for n in parsed["outputs"]:
        fanout[n] += 1
    words = {**pad_bits(parsed["inputs"], "in"), **pad_bits(parsed["outputs"], "out")}
    reach: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for word, bits in words.items():
        backward = word.startswith("io:out:")
        for net, bit in bits:
            key = f"{bit}"
            frontier: list[str] = []
            if backward:
                if net in driver and fanout[net] <= MAX_FANOUT:
                    frontier = [driver[net]]
            else:
                if fanout[net] <= MAX_FANOUT:
                    frontier = list(consumers.get(net, []))
            seen = set(frontier)
            for atom in frontier:
                reach[atom][word].add(key)
            for _hop in range(K_HOPS):
                nxt: list[str] = []
                for atom in frontier:
                    if backward:
                        for net2 in inputs_of[atom]:
                            if net2 in driver and fanout[net2] <= MAX_FANOUT \
                                    and driver[net2] not in seen:
                                seen.add(driver[net2])
                                nxt.append(driver[net2])
                    else:
                        if fanout[atom] <= MAX_FANOUT:
                            for c in consumers.get(atom, []):
                                if c not in seen:
                                    seen.add(c)
                                    nxt.append(c)
                for atom in nxt:
                    reach[atom][word].add(key)
                frontier = nxt
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    io_of: dict[str, str] = {}
    for atom, per in reach.items():
        if members.get(atom, {}).get("word"):
            continue
        if len(per) == 1:
            word, bitset = next(iter(per.items()))
            if len(bitset) == 1:
                io_of[atom] = word
    luts = [b["name"] for b in blocks]
    has_word = sum(1 for a in luts if members.get(a, {}).get("word"))
    has_io = sum(1 for a in luts if a in io_of)
    lut_only = [b["name"] for b in blocks if b["kind"] == "lut"]
    lw = sum(1 for a in lut_only if members.get(a, {}).get("word"))
    li = sum(1 for a in lut_only if a in io_of)
    nl.write_json(nl.runs_dir(design, "words", "iowords.json"), io_of)
    summary = {"design": design, "k_hops": K_HOPS, "max_fanout": MAX_FANOUT,
               "io_words": len(words), "io_word_bits": sum(len(v) for v in words.values()),
               "luts": len(lut_only), "lut_word": lw, "lut_io_only": li,
               "lut_union": lw + li, "lut_cov_word": lw / max(1, len(lut_only)),
               "lut_cov_union": (lw + li) / max(1, len(lut_only)),
               "atoms": len(luts), "atom_word": has_word, "atom_io_only": has_io,
               "io_groups_used": len(set(io_of.values()))}
    nl.write_json(nl.DATA / design / "iowords.json", summary)
    return summary


def main(argv: list[str]) -> int:
    for design in argv or list(nl.DESIGN_ORDER):
        s = propagate(design)
        print(f"{design}: io-words {s['io_words']}, LUT coverage {s['lut_cov_word']:.3f} -> "
              f"{s['lut_cov_union']:.3f} (io adds {s['lut_io_only']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
