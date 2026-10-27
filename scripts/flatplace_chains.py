"""Carry-chain normalisation of a VPR flat-place file (docs/plan/placers.md section 10.7).

VPR's AP flow reads a flat placement only if every atom of a prepacked molecule sits at ONE location
(vpr/src/analytical_place/analytical_placement_flow.cpp:110). A carry chain (adders linked cout -> cin, plus the flip-flop fed by an
adder's sumout: arch pack pattern "chain", adder.sumout -> ff.D) that crosses CLB rows is written by VPR at several locations, so VPR cannot
read back its own file. This module moves every atom of a chain to the location of the chain head (the adder whose cin is not another
adder's cout), which is what the AP global placer produces before legalisation.

CLI: python3 flatplace_chains.py --blif B --in F --out O [--stats S.json]
Library: chains(blif_path) -> (member_of_head: {atom: head_atom}, chain_ffs: set of flip-flop atom names).
"""
import argparse
import json
from pathlib import Path

OUT_PORTS = {"cout", "sumout"}


def _lines(path):
    lines, cur = [], ""
    for raw in Path(path).read_text().splitlines():
        s = raw.split("#", 1)[0].rstrip()
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        cur += s
        if cur.strip():
            lines.append(cur.strip())
        cur = ""
    return lines


def chains(blif):
    adders, latches = [], []
    for ln in _lines(blif):
        t = ln.split()
        if t[0] == ".subckt" and t[1] == "adder":
            pins = dict(x.split("=", 1) for x in t[2:])
            first_out = next(x.split("=", 1)[1] for x in t[2:] if x.split("=", 1)[0] in OUT_PORTS)
            adders.append((first_out, pins.get("cin"), pins.get("cout"), pins.get("sumout")))
        elif t[0] == ".latch":
            latches.append((t[1], t[2]))
    by_cout = {c: n for n, _cin, c, _s in adders if c}
    nxt = {}
    for n, cin, _c, _s in adders:
        if cin in by_cout:
            nxt[by_cout[cin]] = n  # previous adder -> this adder
    prev = {v: k for k, v in nxt.items()}
    head_of = {}
    for n, *_ in adders:
        h = n
        while h in prev:
            h = prev[h]
        head_of[n] = h
    by_sum = {s: n for n, _cin, _c, s in adders if s}
    ffs = {}
    for d, q in latches:
        if d in by_sum:
            ffs[q] = head_of[by_sum[d]]
    head_of.update(ffs)
    return head_of, set(ffs)


def collapse(blif, lines):
    head_of, ffs = chains(blif)
    loc = {}
    for ln in lines:
        if ln.strip() and not ln.startswith("#"):
            t = ln.split("#", 1)[0].split()
            loc[t[0]] = t
    out, moved = [], 0
    for ln in lines:
        if not ln.strip() or ln.startswith("#"):
            out.append(ln)
            continue
        body, sep, comment = ln.partition("#")
        t = body.split()
        h = head_of.get(t[0])
        if h and h != t[0] and h in loc and t[1:5] != loc[h][1:5]:
            t[1:5] = loc[h][1:5]
            moved += 1
            ln = " ".join(t) + (" #" + comment if sep else "")
        out.append(ln)
    return out, {"chain_atoms": len(head_of), "chain_ffs": len(ffs), "moved": moved}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--blif", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stats")
    a = ap.parse_args()
    new, st = collapse(a.blif, Path(a.inp).read_text().splitlines())
    Path(a.out).write_text("\n".join(new) + "\n")
    if a.stats:
        Path(a.stats).write_text(json.dumps(st) + "\n")
    print(json.dumps(st))
