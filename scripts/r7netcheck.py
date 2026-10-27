"""Equivalence check of a written `.net` against the BLIF and against the stock `.net` (fix round 2, item 4).

The fidelity check of r7net.py only shows that the clusters stayed together. This one reads a `.net` with its OWN resolver
(it does not call the writer) and checks, for every file:

  A. atoms:      the lut/ff atoms of the `.net` are each present once, and every BLIF lut/ff atom is present
                 (atoms VPR sweeps or absorbs, i.e. buffer luts and dangling blocks, are counted apart);
  B. pins:       for every lut and ff, the net seen through each input pin (resolved up through ble6/fle/clb to the clb input
                 pin, or across to the driving fle) equals the BLIF net (lut: the set of input nets; ff: the D net and the clock);
  C. stock:      the same per-atom pin nets equal those in the stock `.net` (exact, independent of the BLIF);
  D. outputs:    for every clb, every net that is driven inside and read by another top-level block leaves on a `clbouts` pin,
                 and every `clbouts` pin points to an fle output that carries a net;
  E. inputs:     every net on a clb input pin is driven outside that clb or is a top-level input.

  python scripts/r7netcheck.py [design ...]     all written .net files under runs/r7f (and the stock one) -> data/r7/net_check.json
"""

from __future__ import annotations

import collections
import gzip
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import nornlib as nl
import r7lib as lib
import r7net as rn

_UP = re.compile(r"^(\w+)(?:\[(\d+)\])?\.(\w+)\[(\d+)\]->")
_INST = re.compile(r"^(\w+)\[(\d+)\]$")   # own copies of r7net's parse helpers: the checker does not share its parse with the writer


def _tok(block: ET.Element, kind: str, name: str) -> list[str]:
    """Tokens of the port `name` under `kind` (inputs, outputs, clocks) of a block."""
    for p in block.findall(f"{kind}/port"):
        if p.get("name") == name:
            return (p.text or "").split()
    return []


def _child(block: ET.Element, inst: str) -> ET.Element | None:
    """The direct child block with this instance name."""
    for c in block.findall("block"):
        if c.get("instance") == inst:
            return c
    return None


def _input_net(block: ET.Element, parent: dict[ET.Element, ET.Element], port: str, idx: int, kind: str = "inputs") -> str | None:
    """Net at input pin port[idx] of `block`: follow `parent.port[i]->conn` up and `sibling[i].out[j]->conn` across."""
    toks = _tok(block, kind, port)
    if idx >= len(toks) or toks[idx] == "open":
        return None
    t = toks[idx]
    m = _UP.match(t)
    if not m:
        return t            # a net name (top-level clb input pins, pads, clocks)
    par = parent.get(block)
    if par is None:
        return None
    base_p = re.match(r"^(\w+)", par.get("instance", "")).group(1)
    if m.group(2) is None and m.group(1) == base_p:
        kind_up = "clocks" if m.group(3) == "clk" else "inputs"
        return _input_net(par, parent, m.group(3), int(m.group(4)), kind_up)
    sib = _child(par, f"{m.group(1)}[{m.group(2)}]")
    return None if sib is None else _out_net(sib, parent, m.group(3), int(m.group(4)))


def _out_net(block: ET.Element, parent: dict[ET.Element, ET.Element], port: str, idx: int) -> str | None:
    """Net leaving `block` on output pin port[idx]: follows `child[i].port[j]->conn` down to the primitive. A block in wire mode
    routes its own input to its output (`self[i].in[j]->...`): that is the net at its input pin."""
    toks = _tok(block, "outputs", port)
    if idx >= len(toks) or toks[idx] == "open":
        return None
    t = toks[idx]
    m = _UP.match(t)
    if not m:
        return t
    if m.group(2) is not None and f"{m.group(1)}[{m.group(2)}]" == block.get("instance") and m.group(3) in ("in",):
        return _input_net(block, parent, m.group(3), int(m.group(4)))
    c = _child(block, f"{m.group(1)}[{m.group(2)}]")
    return None if c is None else _out_net(c, parent, m.group(3), int(m.group(4)))


def read_blif(path: Path) -> dict[str, Any]:
    """lut atoms (output -> inputs), ff atoms (Q -> (D, clk)), buffer aliases (out -> in), declared inputs/outputs."""
    text = path.read_text(errors="replace").replace("\\\n", " ")
    luts: dict[str, list[str]] = {}
    ffs: dict[str, tuple[str, str | None]] = {}
    bufs: dict[str, str] = {}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        w = ln.split()
        if not w:
            continue
        if w[0] == ".names":
            luts[w[-1]] = w[1:-1]
            if len(w) == 3 and i + 1 < len(lines) and lines[i + 1].split() == ["1", "1"]:
                bufs[w[-1]] = w[1]
        elif w[0] == ".latch":
            ffs[w[2]] = (w[1], w[4] if len(w) > 4 and w[3] in ("re", "fe", "ah", "al", "as") else None)
    return {"luts": luts, "ffs": ffs, "bufs": bufs}


def read_net(path: Path) -> dict[str, Any]:
    """Per-atom pin nets of a `.net`, plus clb inputs/outputs for checks D and E."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as fh:  # type: ignore[operator]
        root = ET.parse(fh).getroot()
    parent = {c: p for p in root.iter() for c in p}
    lut: dict[str, list[str | None]] = {}
    ff: dict[str, tuple[str | None, str | None]] = {}
    dup = 0
    top = root.findall("block")
    in_nets: list[set[str]] = []
    driven_inside: list[set[str]] = []
    driven_fle: list[set[str]] = []
    o_nets: list[list[str | None]] = []
    o_tokens: list[list[str]] = []
    clb_of_top = []
    names = [b.get("name", "") for b in top]
    for b in top:
        ins = set()
        for p in b.findall("inputs/port"):
            ins.update(t for t in (p.text or "").split() if "->" not in t and t != "open")
        for p in b.findall("clocks/port"):
            ins.update(t for t in (p.text or "").split() if "->" not in t and t != "open")
        in_nets.append(ins)
        if not _INST.match(b.get("instance", "")) or _INST.match(b.get("instance", "")).group(1) != "clb":
            driven_inside.append(set())
            o_nets.append([])
            o_tokens.append([])
            clb_of_top.append(False)
            driven_fle.append(set())
            for p in b.findall("outputs/port"):
                driven_inside[-1].update(t for t in (p.text or "").split() if "->" not in t and t != "open")
            for blk in b.iter("block"):   # hard blocks (adders, multipliers, memories) drive the names on their output ports
                for p in blk.findall("outputs/port"):
                    driven_inside[-1].update(t for t in (p.text or "").split() if "->" not in t and t != "open")
            # top-level inputs (pads) drive their own name
            continue
        clb_of_top.append(True)
        di = set()
        dfle = set()
        for blk in b.iter("block"):
            m = _INST.match(blk.get("instance", ""))
            if not m or blk.get("name") == "open":
                continue
            kind = m.group(1)
            if kind == "lut" and not blk.findall("block"):
                nm = blk.get("name", "")
                if nm in lut:
                    dup += 1
                lut[nm] = [_input_net(blk, parent, "in", j) for j in range(len(_tok(blk, "inputs", "in")))]
            elif kind == "ff" and not blk.findall("block"):
                nm = blk.get("name", "")
                if nm in ff:
                    dup += 1
                ff[nm] = (_input_net(blk, parent, "D", 0), _input_net(blk, parent, "clk", 0, "clocks"))
            for p in blk.findall("outputs/port"):   # leaf outputs (also adder sum/cout in arithmetic mode) name the nets they drive
                di.update(t for t in (p.text or "").split() if "->" not in t and t != "open")
            if kind == "fle":
                for o in (0, 1):
                    n = _out_net(blk, parent, "out", o)
                    if n:
                        di.add(n)
                        dfle.add(n)
        driven_inside.append(di)
        driven_fle.append(dfle)
        toks = _tok(b, "outputs", "O")
        o_tokens.append(toks)
        o_nets.append([_out_net(b, parent, "O", j) if t != "open" else None for j, t in enumerate(toks)])
    return {"lut": lut, "ff": ff, "dup": dup, "in_nets": in_nets, "driven": driven_inside, "driven_fle": driven_fle, "o_nets": o_nets,
            "o_tokens": o_tokens, "names": names, "is_clb": clb_of_top, "top_in": set((root.findtext("inputs") or "").split()) | set((root.findtext("clocks") or "").split()), "n_top": len(top)}


def undriven_set(n: dict[str, Any]) -> set[tuple[str, str]]:
    """(clb name, net) of every clb input net that no other top-level block drives and that is not a top-level input."""
    out: set[tuple[str, str]] = set()
    for i in range(n["n_top"]):
        if not n["is_clb"][i]:
            continue
        driven = set().union(*[n["driven"][j] for j in range(n["n_top"]) if j != i]) | n["top_in"]
        out.update((n["names"][i], x) for x in n["in_nets"][i] if x not in driven)
    return out


def check(net_path: Path | dict[str, Any], blif: dict[str, Any] | None, stock: dict[str, Any] | None) -> dict[str, Any]:
    """All checks A-E on a `.net` (a path or the dict of read_net); blif=None skips A and B (fixture tests)."""
    n = net_path if isinstance(net_path, dict) else read_net(net_path)
    r: dict[str, Any] = {"atoms_lut": len(n["lut"]), "atoms_ff": len(n["ff"]), "duplicate_atoms": n["dup"]}
    if blif is None:
        blif = {"luts": {}, "ffs": {}, "bufs": {}}
        skip_ab = True
    else:
        skip_ab = False
    bufs = blif["bufs"]

    def canon(x: str) -> str:
        seen = 0
        while x in bufs and x not in n["lut"] and seen < 50:
            x, seen = bufs[x], seen + 1
        return x

    # A: coverage
    miss_l = [a for a in blif["luts"] if a not in n["lut"] and a not in bufs and a not in blif["ffs"] and blif["luts"][a]]
    extra_l = [a for a in n["lut"] if a not in blif["luts"]]
    extra_f = [a for a in n["ff"] if a not in blif["ffs"]]
    miss_f = [a for a in blif["ffs"] if a not in n["ff"]]
    if stock is not None:   # atoms VPR swept before packing are missing from the stock .net too; only a loss against the stock counts
        r["A_vpr_swept_lut"] = sum(1 for a in miss_l if a not in stock["lut"])
        r["A_vpr_swept_ff"] = sum(1 for a in miss_f if a not in stock["ff"])
        miss_l = [a for a in miss_l if a in stock["lut"]]
        miss_f = [a for a in miss_f if a in stock["ff"]]
    r["A_missing_lut"], r["A_missing_ff"] = len(miss_l), len(miss_f)
    r["A_extra_lut"], r["A_extra_ff"] = len(extra_l), len(extra_f)
    r["A_blif_constant_not_in_net"] = sum(1 for a, v in blif["luts"].items() if not v and a not in n["lut"])
    r["A_blif_buffer_absorbed"] = sum(1 for a in bufs if a not in n["lut"])
    if skip_ab:
        r["A_extra_lut"] = r["A_extra_ff"] = 0
    # B: pin nets vs BLIF
    bad_l = bad_f = 0
    for a, pins in n["lut"].items():
        if a not in blif["luts"]:
            continue
        got = sorted(canon(x) for x in pins if x)
        want = sorted(set(canon(x) for x in blif["luts"][a]))
        if sorted(set(got)) != want:
            bad_l += 1
    for a, (d, c) in n["ff"].items():
        if a not in blif["ffs"]:
            continue
        wd, wc = blif["ffs"][a]
        if (d and canon(d)) != canon(wd) or (wc and c != wc):
            bad_f += 1
    r["B_lut_mismatch"], r["B_ff_mismatch"] = bad_l, bad_f
    # C: vs the stock .net
    if stock is not None:
        cl = sum(1 for a, p in n["lut"].items() if a in stock["lut"] and p != stock["lut"][a])   # pin index to net, as lists
        cf = sum(1 for a, p in n["ff"].items() if a in stock["ff"] and p != stock["ff"][a])
        r["C_lut_vs_stock"], r["C_ff_vs_stock"] = cl, cf
        r["C_atoms_not_in_stock"] = sum(1 for a in n["lut"] if a not in stock["lut"]) + sum(1 for a in n["ff"] if a not in stock["ff"])
    # D, E
    bad_out_missing = bad_out_dead = bad_pin = 0
    undriven = undriven_set(n)
    for i in range(n["n_top"]):
        if not n["is_clb"][i]:
            continue
        others = set()
        for j in range(n["n_top"]):
            if j != i:
                others |= n["in_nets"][j]
        needed = n["driven_fle"][i] & others
        leaving = {x for x in n["o_nets"][i] if x}
        bad_out_missing += len(needed - leaving)
        for j, (t, x) in enumerate(zip(n["o_tokens"][i], n["o_nets"][i])):
            if t == "open":
                continue
            m = re.match(r"^fle\[(\d+)\]\.out\[(\d+)\]->clbouts(\d)$", t)
            if x is None or not m or j != 10 * int(m.group(2)) + int(m.group(1)) or int(m.group(3)) != int(m.group(2)) + 1:
                bad_pin += 1
            if x is not None and x not in others:
                bad_out_dead += 1
    r["D_needed_output_without_clbout"], r["D_clbout_pin_bad"], r["D_clbout_unread"] = bad_out_missing, bad_pin, bad_out_dead
    r["E_input_net_undriven"] = len(undriven)
    if stock is not None and n is not stock:
        und_s = undriven_set(stock)
        r["E_undriven_in_stock"] = len(und_s)
        r["E_input_net_undriven"] = len(undriven - und_s)   # per pin: a (clb, net) undriven in the stock file too (primary input without a pad entry) is not the writer's
    keys = [k for k in r if k.startswith(("A_missing", "B_", "C_lut", "C_ff", "C_atoms", "D_needed", "D_clbout_pin", "E_input")) or k == "duplicate_atoms"]
    r["ok"] = all(r[k] == 0 for k in keys)
    return r


def _blif_path(design: str) -> Path:
    return nl.runs_dir(design, "netlist", f"{design}.blif")


def run(designs: list[str]) -> int:
    out: dict[str, Any] = {"files": [], "totals": {}}
    for d in designs:
        blif = read_blif(_blif_path(d))
        sp = rn.stock_net_path(d)
        stock = read_net(sp)
        files = [sp] + sorted((rn.R7F / d).glob("*.net.gz"))
        for fp in files:
            r = check(fp, blif, stock)
            r.update({"design": d, "file": fp.name if fp != sp else "stock.net.gz"})
            out["files"].append(r)
            print(d, r["file"], "ok" if r["ok"] else "FAIL", {k: v for k, v in r.items() if isinstance(v, int) and v and k.startswith(("A_m", "B_", "C_", "D_", "E_", "dup"))}, flush=True)
    t = collections.Counter()
    for r in out["files"]:
        t["files"] += 1
        t["files_ok"] += int(r["ok"])
        t["atoms_checked"] += r["atoms_lut"] + r["atoms_ff"]
        for k, v in r.items():
            if isinstance(v, int) and not isinstance(v, bool) and k[:2] in ("A_", "B_", "C_", "D_", "E_"):
                t[k] += v
    out["totals"] = dict(t)
    nl.write_json(lib.DATA7 / "net_check.json", out)
    print(out["totals"])
    return 0


def main(argv: list[str]) -> int:
    ds = argv or [d for d in list(lib.CALIB) + list(lib.MAIN) if (rn.R7F / d / "rounds.json").is_file()]
    return run(ds)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
