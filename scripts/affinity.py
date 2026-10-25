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


CONSTS = ("gnd", "vcc", "unconn")


def absorbed_buffers(parsed: dict) -> set[str]:
    """Names of buffer LUTs that VPR's netlist clean-up absorbs (``absorb_buffer_luts``, on by default):
    a ``.names`` with one input and the table ``1 1``, also when its output is a primary output (the pad
    then takes the net). VPR replaces the net by the buffer's input, so the atom does not exist in the
    packer's netlist. This is why round 3's affinity file of mkDelayWorker32B matched 38 of 1620 entries:
    the rest were buffers (constant buffers ``.names gnd x`` and buffers in front of primary outputs), not
    a different name form (round 4, Stage 1 item 2). The rule is checked against the atoms of a packed
    run by ``round4.py join``."""
    gone = set()
    for b in parsed["blocks"]:
        if b["kind"] == "lut" and len(b["inputs"]) == 1 and b["rows"] == [("1", "1")]:
            gone.add(str(b["name"]))
    return gone


def swept_blocks(parsed: dict, arch: dict[str, set[str]], gone: set[str]) -> set[str]:
    """Names of blocks whose outputs nobody uses once the buffers in `gone` are absorbed: VPR's clean-up
    (``sweep_blocks``) removes them, repeatedly. Dead logic is why e.g. 766 of the 833 adders of
    mkDelayWorker32B are not in the packer's netlist (a memory whose outputs are unused takes its address
    logic with it)."""
    alias = {str(b["name"]): b["inputs"][0] for b in parsed["blocks"] if str(b["name"]) in gone}

    def res(net: str) -> str:
        n = 0
        while net in alias and n < 100000:
            net = alias[net]
            n += 1
        return net

    outs_of: dict[str, list[str]] = {}
    ins_of: dict[str, list[str]] = {}
    for b in parsed["blocks"]:
        name = str(b["name"])
        if name in gone:
            continue
        if b["kind"] == "hard":
            ports = arch.get(b.get("model", ""), set())
            outs_of[name] = [n for f, n in b.get("pins", {}).items() if f.split("[")[0] in ports]
            ins_of[name] = [res(n) for f, n in b.get("pins", {}).items() if f.split("[")[0] not in ports]
        else:
            outs_of[name] = [name]
            ins_of[name] = [res(n) for n in b["inputs"]]
    users: dict[str, int] = {}
    driver: dict[str, str] = {}
    for name, nets in ins_of.items():
        for n in nets:
            users[n] = users.get(n, 0) + 1
    for name, nets in outs_of.items():
        for n in nets:
            driver[n] = name
    for n in parsed["outputs"]:
        users[res(n)] = users.get(res(n), 0) + 1
    dead: set[str] = set()
    work = [n for n, o in outs_of.items() if o and all(users.get(x, 0) == 0 for x in o)]
    while work:
        name = work.pop()
        if name in dead:
            continue
        dead.add(name)
        for n in ins_of[name]:
            users[n] -= 1
            d = driver.get(n)
            if d and d not in dead and all(users.get(x, 0) == 0 for x in outs_of[d]):
                work.append(d)
    return dead


def logic_atoms(design: str, vpr_view: bool = True) -> list[str]:
    """LUT, FF and adder atoms. With vpr_view (round 4) the buffer LUTs VPR absorbs and the blocks it sweeps
    as dead logic are left out; the round-3 list (vpr_view False) kept them."""
    # round 4: the architecture's output ports name an adder after its `cout` net, as VPR does. Round 3 called
    # parse_blif without them, which named every adder after its first pin (`a`): adder atoms were never in
    # the affinity files (the file listed the driver of the adder's `a` net twice, a dict collapsed it).
    ports = nl.arch_output_ports(nl.ARCH)
    parsed = nl.parse_blif(nl.runs_dir(design, "netlist", f"{design}.blif"), None, ports)
    gone = absorbed_buffers(parsed) if vpr_view else set()
    if vpr_view:
        gone = gone | swept_blocks(parsed, ports, gone)
    out = []
    for b in parsed["blocks"]:
        if str(b["name"]) in gone:
            continue
        if b["kind"] in ("lut", "latch") or (b["kind"] == "hard" and b.get("model") == "adder"):
            out.append(str(b["name"]))
    return out


def labels(design: str, source: str, vpr_view: bool = True) -> dict[str, str]:
    atoms = logic_atoms(design, vpr_view)
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


def affinity_path(design: str, source: str, rnd: str = "r3"):
    """Round 3 files: runs/<d>/r3/affinity (buffers listed); round 4: runs/<d>/r4/affinity."""
    return nl.runs_dir(design, rnd, "affinity", f"{source}.tsv")


def write(design: str, source: str, rnd: str = "r4") -> int:
    """Group ids come from the label set before the absorbed buffers are dropped, so dropping them does not
    renumber a group. The adder naming fix (above) does change the files of designs with adders."""
    full = labels(design, source, vpr_view=False)
    ids = {g: i for i, g in enumerate(sorted(set(full.values())))}
    lab = labels(design, source, vpr_view=True)
    path = affinity_path(design, source, rnd)
    nl.ensure_dir(path.parent)
    path.write_text("".join(f"{a}\t{ids[g]}\n" for a, g in sorted(lab.items())), encoding="utf-8")
    return len(lab)


def main(argv: list[str]) -> int:
    for design in argv or list(nl.DESIGN_ORDER):
        print(design, {s: write(design, s) for s in SOURCES})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
