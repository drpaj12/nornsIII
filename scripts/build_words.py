"""Word membership from Odin III provenance (the data behind the bitwise seeds, RQ-N7).

The provenance BLIF names a block ``module/$n<NET>@file:line``: the line is the HDL *statement*,
which is far too coarse for a word (an ``always`` block is one line, sha's holds 1739 of its
2506 blocks). The finer data is in the Odin III session that wrote the BLIF: every final cell
has its net's HDL names (``bus[i]``) and its source spans, and the word-level cells before
``lower`` have theirs. This script reruns the identical Odin III script (the BLIF it writes is
checked byte-for-byte against the kept one), reads the same records Loki's L0 labeller reads
(Loki is imported, never changed) and joins a final cell to its BLIF block through the net id
the BLIF name carries (``$n<NET>``), so the join is exact, not by name.

Word key of a block, first rule that applies:
  bus   an output net carries an HDL name ``bus[i]``: word = that bus (a register or a named
        wire), bit = i.  Registers always have it; so do some LUTs.
  cell  exactly one word-level cell's spans are contained in the cell's spans (Loki's match):
        word = that word cell (an adder, a multiplier, a one-statement LUT), bit order for an
        adder word = position along its carry chain.
  none  anything else (ABC's cone provenance merges the spans of a LUT that mixes words, and
        its budget makes whole runs share one record): left to the caller's fallback.

Usage: python scripts/build_words.py [design ...]
Writes runs/<design>/words/members.json (block name -> word id) and words.json (per word:
key, kind, size, bits) and data/<design>/words.json (the same summary, committed).
"""

from __future__ import annotations

import collections
import hashlib
import re
import sys
import tempfile
from pathlib import Path

import nornlib as nl

BUS = re.compile(r"^(.+)\[(\d+)\]$")


def odin_session(design: str):
    from loki import odin as lo
    from loki.snapshot import take_snapshot
    d, inst = lo.open_front("f1-k6", [nl.design_verilog(design)], None, nl.ARCH, None)
    snap = take_snapshot(d, inst)
    d.run_script("hardmap; lower; abc --lut 6")
    return d, snap


def blif_output_nets(blocks, models):
    """block -> its output net names (the BLIF names; a hard cell has several)."""
    out = []
    for b in blocks:
        if b["kind"] == "hard":
            pins = b.get("pins", {})
            ports = models.get(b.get("model", ""), set())
            nets = [v for k, v in pins.items() if k.split("[")[0] in ports]
        else:
            nets = [b["name"]]
        out.append((b, nets))
    return out


def net_key(name: str) -> str:
    """The part of a provenance net name that identifies the net: ``$n<ID>`` or a bus bit."""
    leaf = nl.provenance_parts(name)[1]
    return leaf


def build(design: str) -> dict:
    from loki.extract import extract_netlist
    from loki.labels import match_words, _groups
    kept = nl.runs_dir(design, "netlist", f"{design}.blif")
    flat = nl.Flat(nl.runs_dir(design, "runs", "baseline", "final.flat_place"))
    models = nl.arch_output_ports(nl.ARCH)
    blocks = nl.parse_blif(kept, set(flat.atoms), models)["blocks"]
    d, snap = odin_session(design)
    with tempfile.TemporaryDirectory(prefix="nr2-") as tmp:
        again = Path(tmp) / "again.blif"
        d.run_script(f'write_blif --vtr --lut-k 6 --name-style provenance "{again}"')
        same = hashlib.sha256(again.read_bytes()).hexdigest() == \
            hashlib.sha256(kept.read_bytes()).hexdigest()
    nlst = extract_netlist(d, snap.top)
    # leaf (``$n<ID>`` or a bus-bit name) -> block name; hard cells by any output net
    by_leaf: dict[str, str] = {}
    for b, nets in blif_output_nets(blocks, models):
        if not b["name"] or b["name"] in ("gnd", "vcc", "unconn"):
            continue
        for net in nets:
            by_leaf.setdefault(net_key(net), b["name"])
    # hard cells (RAM, multiplier) may have no connected output: join them by the votes of all
    # their nets against the BLIF pin names
    hard_by_leaf: dict[str, set[str]] = collections.defaultdict(set)
    for b in blocks:
        if b["kind"] == "hard":
            for net in b.get("pins", {}).values():
                hard_by_leaf[net_key(net)].add(b["name"])
    member: dict[str, dict] = {}
    unjoined = 0
    cell_groups: dict[str, list[int]] = collections.defaultdict(list)
    for c in nlst.cells:
        if c.kind == "const":
            continue
        out_nets = [n for p in c.outputs for n in p.nets if n]
        block = None
        for n in out_nets:
            block = by_leaf.get(f"$n{n}")
            if block is None:
                for nm in nlst.nets[n].names if n in nlst.nets else ():
                    # the writer legalises a dotted flattened name: ``a.b[0]`` -> ``a__b[0]``
                    block = by_leaf.get(nm) or by_leaf.get(nm.replace(".", "__"))
                    if block:
                        break
            if block:
                break
        if block is None and c.kind == "hard":
            votes: collections.Counter = collections.Counter()
            for p in (*c.inputs, *c.outputs):
                for n in p.nets:
                    for blk in hard_by_leaf.get(f"$n{n}", ()):
                        votes[blk] += 1
            top = votes.most_common(2)
            if top and (len(top) == 1 or top[0][1] > top[1][1]) and top[0][0] not in member:
                block = top[0][0]
        if block is None:
            unjoined += 1
            continue
        bus, bit = "", -1
        for n in out_nets:
            for nm in (nlst.nets[n].names if n in nlst.nets else ()):
                m = BUS.match(nm)
                if m:
                    bus, bit = m.group(1), int(m.group(2))
                    break
            if bus:
                break
        groups = _groups(match_words(c, snap.words))
        info = {"kind": c.kind, "bus": bus, "bit": bit, "ngroups": len(groups)}
        if bus:
            info["word"] = "b:" + bus
        elif len(groups) == 1:
            info["word"] = f"c:{groups[0][0].id}:{groups[0][0].type}"
            info["cell_id"] = int(c.id)
        else:
            info["word"] = None
        member[block] = info
    # carry-chain bit order for adder words (cin <- cout links among that word's adders)
    adders = {b["name"]: b for b in blocks if b.get("model") == "adder" and b.get("pins")}
    cout_of = {}
    for name, b in adders.items():
        cout_of[b["pins"].get("cout", "")] = name
    nxt = {}
    prev = set()
    for name, b in adders.items():
        src = cout_of.get(b["pins"].get("cin", ""))
        if src and src != name:
            nxt[src] = name
            prev.add(name)
    pos: dict[str, int] = {}
    for head in [n for n in adders if n not in prev]:
        i, cur = 0, head
        while cur and cur not in pos:
            pos[cur] = i
            i += 1
            cur = nxt.get(cur)
    for name, i in pos.items():
        if name in member and member[name]["word"] and member[name]["bit"] < 0:
            member[name]["bit"] = i
            member[name]["bit_src"] = "chain"
    words: dict[str, list[str]] = collections.defaultdict(list)
    for name, info in member.items():
        if info["word"]:
            words[info["word"]].append(name)
    kinds = collections.Counter(i["word"].split(":")[0] if i["word"] else "none"
                                for i in member.values())
    sizes = sorted((len(v) for v in words.values()), reverse=True)
    summary = {
        "design": design, "blif_identical": same, "blocks": len(blocks),
        "final_cells": len(member), "unjoined_cells": unjoined,
        "by_rule": dict(kinds), "words": len(words),
        "words_ge2": sum(1 for s in sizes if s >= 2), "largest_words": sizes[:5],
        "blocks_in_word": sum(sizes), "bit_indexed": sum(1 for i in member.values()
                                                         if i["word"] and i["bit"] >= 0),
        "by_kind": {k: sum(1 for i in member.values() if i["kind"] == k and i["word"])
                    for k in ("lut", "ff", "hard")},
        "kind_total": {k: sum(1 for i in member.values() if i["kind"] == k)
                       for k in ("lut", "ff", "hard")},
        "line_groups_largest": line_groups(blocks),
    }
    nl.write_json(nl.runs_dir(design, "words", "members.json"), member)
    nl.write_json(nl.runs_dir(design, "words", "words.json"),
                  {k: sorted(v) for k, v in words.items()})
    nl.write_json(nl.DATA / design / "words.json", summary)
    return summary


def line_groups(blocks) -> list[int]:
    """Option 1 of the brief (module, file:line), kept as the comparison: largest group sizes."""
    g: dict[tuple, int] = collections.Counter()
    for b in blocks:
        m, _l, f, ln = nl.provenance_parts(b["name"])
        if f:
            g[(m, f, ln)] += 1
    return sorted(g.values(), reverse=True)[:5]


def main(argv: list[str]) -> int:
    for design in argv or list(nl.DESIGN_ORDER):
        s = build(design)
        print(f"{design}: identical={s['blif_identical']} cells={s['final_cells']} "
              f"unjoined={s['unjoined_cells']} rules={s['by_rule']} words={s['words']} "
              f"in_word={s['blocks_in_word']}/{s['blocks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
