"""Round-6 generator: round-5 `dp` blocks and topologies, HDL words that disagree with the blocks by a controlled amount
(docs/plan/round6.md, Stage 1).

The logic (blocks, topology, functions, external wiring) is exactly the round-5 `dp` design of the same topology and size
(`r5gen.build_spec("r5_<topology>_dp_<B>")`). Only the HDL declaration of the registers changes: inside a block the ten
registers and the ten output ports are scalars (no bus name), and the top module declares B word vectors `w<j>[9:0]`;
flip-flop (k, i) is bit `bit` of word `word` by a LAYOUT. Layout at alignment a:
  * per block, q_k = round((1-a) 10 (k+1)) - round((1-a) 10 k) flip-flops are DISPLACED (error-diffusion rounding, so every
    block displaces the same number up to one); which local indices are displaced is a seeded draw;
  * the non-displaced flip-flops keep their own slot (word k, bit i);
  * the displaced flip-flops are listed by (local index i, block k) and dealt, in that order, into the displaced slots listed
    by (word, bit): a bit-slice across blocks (word j then holds the same local bit of consecutive blocks).
a = 1: no displacement, word k = block k (the round-5 dp layout, the reference). a = 0: every flip-flop is displaced, a word
holds one flip-flop of each of about ten different blocks and a block's flip-flops sit in about ten different words.
Deterministic: same (topology, a, B, seed) -> same bytes.

Usage: python gen/r6gen.py OUT_DIR [--only NAME ...]   writes OUT_DIR/<name>.v, .spec.json and data/r6/designs.json
       python gen/r6gen.py --list
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
LEVELS = (0, 25, 50, 75, 100)  # design alignment a = level / 100
N_LE = r5gen.N_LE


def names() -> list[str]:
    return [f"r6_{t}_a{a}_{b}" for b in SIZES for t in TOPOLOGIES for a in LEVELS]


def parse_name(name: str) -> tuple[str, int, int]:
    _, topo, a, b = name.split("_")
    return topo, int(a[1:]), int(b)


def r5_name(name: str) -> str:
    topo, _, b = parse_name(name)
    return f"r5_{topo}_dp_{b}"


def layout(name: str) -> list[list[int]]:
    """slot[k][i] = [word, bit] of flip-flop i of block k."""
    topo, level, b = parse_name(name)
    frac = (100 - level) / 100.0
    rng = random.Random(f"{SEED}:{name}:layout")
    slot = [[[k, i] for i in range(N_LE)] for k in range(b)]
    disp: list[tuple[int, int]] = []
    for k in range(b):
        q = int(frac * N_LE * (k + 1) + 0.5) - int(frac * N_LE * k + 0.5)
        for i in sorted(rng.sample(range(N_LE), q)):
            disp.append((k, i))
    ffs = sorted(disp, key=lambda x: (x[1], x[0]))
    slots = sorted(disp)
    for (k, i), (w, bit) in zip(ffs, slots):
        slot[k][i] = [w, bit]
    return slot


def designed_alignment(slot: list[list[int]]) -> dict:
    """Word purity against the blocks from the layout: sum over words of the largest count of one block's flip-flops, over all
    flip-flops; and the share of flip-flops in their own slot."""
    b = len(slot)
    per_word: dict[int, dict[int, int]] = {}
    own = 0
    for k in range(b):
        for i, (w, bit) in enumerate(slot[k]):
            per_word.setdefault(w, {})
            per_word[w][k] = per_word[w].get(k, 0) + 1
            own += (w, bit) == (k, i)
    pur = sum(max(d.values()) for d in per_word.values()) / (N_LE * b)
    blocks_per_word = sum(len(d) for d in per_word.values()) / len(per_word)
    words_per_block: dict[int, set] = {}
    for k in range(b):
        words_per_block[k] = {w for w, _ in slot[k]}
    return {"purity": pur, "own_slot": own / (N_LE * b), "blocks_per_word": blocks_per_word,
            "words_per_block": sum(len(v) for v in words_per_block.values()) / b}


def build_spec(name: str) -> dict:
    spec = r5gen.build_spec(r5_name(name))
    topo, level, b = parse_name(name)
    slot = layout(name)
    spec.update({"name": name, "round": 6, "level": level, "layout": slot, "alignment": designed_alignment(slot),
                 "r5_design": r5_name(name)})
    return spec


def verilog(spec: dict) -> str:
    b, level = spec["b"], spec["level"]
    slot = spec["layout"]
    out = [f"// Norns round 6 generated design {spec['name']} (topology {spec['topology']}, alignment {level / 100:g}, B={b}, "
           f"seed {spec['seed']}). Logic = round-5 {spec['r5_design']}; known optimal clustering: block b<k> = one CLB; "
           f"HDL words w<j> = layout of docs/plan/round6.md.\n"]

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
    for j in range(b):
        out.append(f"  wire [9:0] w{j};")
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
    return {"name": spec["name"], "topology": spec["topology"], "level": spec["level"], "b": spec["b"], "seed": spec["seed"],
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
    rec = Path(__file__).resolve().parents[1] / "data" / "r6" / "designs.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(rows)} designs; {sum(r['bytes'] for r in rows)} bytes of Verilog")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
