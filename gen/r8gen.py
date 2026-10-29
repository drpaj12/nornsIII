"""Round-8 generator (H22' re-run, docs/plan/round8-h22.md): round-5 `dp` blocks and topologies, HDL words that are w-bit buses over a
random permutation of all flip-flops, so a word cuts across blocks and does not mirror the CLB partition.

The logic (blocks, topology, functions, external wiring) is exactly the round-5 `dp` design of the same topology and size
(`r5gen.build_spec("r5_<topology>_dp_<B>")`), as in round 6. Only the HDL declaration of the registers changes: inside a block the ten
registers and ten output ports are scalars; the top module declares word buses `wire [w-1:0] w<j>`. Layout: one seeded random
permutation of the 10 B flip-flops (k, i); word j holds entries j*w .. j*w+w-1 (the last word is narrower when w does not divide
10 B; with B a power of two from 16 and w in {4, 8, 16, 32} it always divides). Deterministic: same (topology, w, B) -> same bytes.

Usage: python gen/r8gen.py OUT_DIR [--only NAME ...]   writes OUT_DIR/<name>.v, .spec.json and data/r8/designs.json
       python gen/r8gen.py --list
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import r5gen

SEED = 20261026
SIZES = (16, 32, 64, 128, 256, 512, 1024)
TOPOLOGIES = ("mesh", "tree", "chain")
WIDTHS = (4, 8, 16, 32)
N_LE = r5gen.N_LE


def names() -> list[str]:
    return [f"r8_{t}_w{w}_{b}" for b in SIZES for t in TOPOLOGIES for w in WIDTHS]


def parse_name(name: str) -> tuple[str, int, int]:
    _, topo, w, b = name.split("_")
    return topo, int(w[1:]), int(b)


def r5_name(name: str) -> str:
    topo, _, b = parse_name(name)
    return f"r5_{topo}_dp_{b}"


def layout(name: str) -> list[list[int]]:
    """slot[k][i] = [word, bit] of flip-flop i of block k."""
    _, w, b = parse_name(name)
    ffs = [(k, i) for k in range(b) for i in range(N_LE)]
    random.Random(f"{SEED}:{name}:layout").shuffle(ffs)
    slot = [[[0, 0] for _ in range(N_LE)] for _ in range(b)]
    for pos, (k, i) in enumerate(ffs):
        slot[k][i] = [pos // w, pos % w]
    return slot


def designed_alignment(slot: list[list[int]]) -> dict:
    """Purity of the words against the blocks (sum over words of the largest count of one block's flip-flops, over all), mean blocks per
    word and mean words per block."""
    b = len(slot)
    per_word: dict[int, dict[int, int]] = {}
    for k in range(b):
        for w, _ in slot[k]:
            per_word.setdefault(w, {})
            per_word[w][k] = per_word[w].get(k, 0) + 1
    pur = sum(max(d.values()) for d in per_word.values()) / (N_LE * b)
    return {"purity": pur, "blocks_per_word": sum(len(d) for d in per_word.values()) / len(per_word),
            "words_per_block": sum(len({w for w, _ in slot[k]}) for k in range(b)) / b, "n_words": len(per_word)}


def build_spec(name: str) -> dict:
    spec = r5gen.build_spec(r5_name(name))
    topo, w, b = parse_name(name)
    slot = layout(name)
    spec.update({"name": name, "round": 8, "width": w, "layout": slot, "alignment": designed_alignment(slot),
                 "r5_design": r5_name(name)})
    return spec


def verilog(spec: dict) -> str:
    slot = spec["layout"]
    out = [f"// Norns round 8 generated design {spec['name']} (topology {spec['topology']}, word width {spec['width']}, B={spec['b']}, "
           f"seed {spec['seed']}). Logic = round-5 {spec['r5_design']}; known optimal clustering: block b<k> = one CLB; "
           f"HDL words w<j> = random-permutation layout of docs/plan/round8-h22.md.\n"]

    def bit(k, i):
        w, p = slot[k][i]
        return f"w{w}[{p}]"

    for blk in spec["blocks"]:
        k, slots = blk["k"], blk["slots"]
        ports = "input clk" + (f", input [{len(slots) - 1}:0] x" if slots else "") + ", " + ", ".join(
            f"output q{i}" for i in range(N_LE))
        out.append(f"module b{k}({ports});")
        out.append("  reg " + ", ".join(f"r{i}" for i in range(N_LE)) + ";")
        out += [f"  assign q{i} = r{i};" for i in range(N_LE)]
        out.append("  always @(posedge clk) begin")
        for i, f in enumerate(blk["funcs"]):
            sig = [f"r{a[1]}" if a[0] == "r" else f"x[{a[1]}]" for a in f["inputs"]]
            out.append(f"    r{i} <= {r5gen.render(f['expr'], sig)};")
        out.append("  end")
        out.append("endmodule\n")
    out.append("module top(input clk, input [7:0] pi, output [7:0] po);")
    widths: dict[int, int] = {}
    for row in slot:
        for w, p in row:
            widths[w] = max(widths.get(w, 0), p + 1)
    for j in sorted(widths):
        out.append(f"  wire [{widths[j] - 1}:0] w{j};")
    for blk in spec["blocks"]:
        k, slots = blk["k"], blk["slots"]
        conn = [".clk(clk)"]
        if slots:
            parts = [bit(s[1], s[2]) if s[0] == "q" else f"pi[{s[1]}]" for s in reversed(slots)]
            conn.append(".x({" + ", ".join(parts) + "})")
        conn += [f".q{i}({bit(k, i)})" for i in range(N_LE)]
        out.append(f"  b{k} u{k}({', '.join(conn)});")
    for p, (k, f) in enumerate(spec["po"]):
        out.append(f"  assign po[{p}] = {bit(k, f)};")
    out.append("endmodule")
    return "\n".join(out) + "\n"


def summary(spec: dict, text: str) -> dict:
    return {"name": spec["name"], "topology": spec["topology"], "width": spec["width"], "b": spec["b"], "seed": spec["seed"],
            "r5_design": spec["r5_design"], "edges": len(spec["edges"]), "luts": N_LE * spec["b"], "ffs": N_LE * spec["b"],
            "designed_cut": spec["designed_cut"], "alignment": spec["alignment"], "bytes": len(text),
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--list":
        print("\n".join(names()))
        return 0
    out_dir = Path(argv[0])
    only = argv[argv.index("--only") + 1:] if "--only" in argv else names()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in names():
        spec = build_spec(name)
        text = verilog(spec)
        rows.append(summary(spec, text))
        if name in only:
            (out_dir / f"{name}.v").write_text(text, encoding="utf-8")
            (out_dir / f"{name}.spec.json").write_text(json.dumps(spec, sort_keys=True) + "\n", encoding="utf-8")
    rec = Path(__file__).resolve().parents[1] / "data" / "r8" / "designs.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(rows)} designs; {sum(r['bytes'] for r in rows)} bytes of Verilog")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
