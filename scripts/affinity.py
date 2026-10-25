"""Affinity files for the Norns packer (round 3): atom name -> integer group id.

Sources (docs/plan/round3.md):
  module   the Odin III provenance module path of the atom (every logic atom has one)
  word     the round-2 word of the atom (runs/<d>/words/members.json); atoms without a word absent
  wordio   word where the atom has one, else its I/O word (scripts/io_words.py); else absent
Only atoms that live in logic CLBs are listed: LUTs, flip-flops and adder cells; pads, multipliers
and memories are left out.

Usage: python scripts/affinity.py [design ...]    writes runs/<d>/r3/affinity/<source>.tsv
"""

from __future__ import annotations

import sys

import nornlib as nl

SOURCES = ("module", "word", "wordio")


def logic_atoms(design: str) -> list[str]:
    parsed = nl.parse_blif(nl.runs_dir(design, "netlist", f"{design}.blif"))
    out = []
    for b in parsed["blocks"]:
        if b["kind"] in ("lut", "latch") or (b["kind"] == "hard" and b.get("model") == "adder"):
            out.append(str(b["name"]))
    return out


def labels(design: str, source: str) -> dict[str, str]:
    atoms = logic_atoms(design)
    if source == "module":
        return {a: nl.module_of(a) for a in atoms if nl.module_of(a)}
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    word = {a: members[a]["word"] for a in atoms if a in members and members[a]["word"]}
    if source == "word":
        return word
    io = nl.read_json(nl.runs_dir(design, "words", "iowords.json"))
    out = dict(word)
    for a in atoms:
        if a not in out and a in io:
            out[a] = io[a]
    return out


def affinity_path(design: str, source: str):
    return nl.runs_dir(design, "r3", "affinity", f"{source}.tsv")


def write(design: str, source: str) -> int:
    lab = labels(design, source)
    ids = {g: i for i, g in enumerate(sorted(set(lab.values())))}
    path = affinity_path(design, source)
    nl.ensure_dir(path.parent)
    path.write_text("".join(f"{a}\t{ids[g]}\n" for a, g in sorted(lab.items())), encoding="utf-8")
    return len(lab)


def main(argv: list[str]) -> int:
    for design in argv or list(nl.DESIGN_ORDER):
        print(design, {s: write(design, s) for s in SOURCES})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
