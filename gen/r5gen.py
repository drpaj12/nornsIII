"""Round-5 generator: Verilog designs with a known optimal clustering (docs/plan/round5.md, Stage 1).

Each block is 10 flip-flops, each fed by a 6-input function (a 6-LUT), so a block fills one CLB of the
k6_frac_N10 architecture (N = 10 logic elements). Blocks are wired in a stated topology with fixed I/O.
Deterministic: the same (topology, style, B, seed) always gives the same bytes.

Usage: python gen/r5gen.py OUT_DIR [--only NAME ...]   writes OUT_DIR/<name>.v and data/r5/designs.json
       python gen/r5gen.py --list                      prints the design names
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

SEED = 20261026
SIZES = (4, 8, 16, 32, 64, 128, 256, 512, 1024)
TOPOLOGIES = ("chain", "mesh", "tree", "rand")
STYLES = ("dp", "ctl")
N_LE = 10          # logic elements per CLB (architecture XML: <pb_type name="clb">, num_pb of fle)
CLB_INPUTS = 40
CLB_OUTPUTS = 20
WIDTH = 2          # signals per directed edge
MAX_DEG = 4        # outgoing and incoming edges per block
N_PI = 8
N_PO = 8
MAX_SLOTS = 18     # external input slots of a block


def names() -> list[str]:
    return [f"r5_{t}_{s}_{b}" for b in SIZES for t in TOPOLOGIES for s in STYLES]


def parse_name(name: str) -> tuple[str, str, int]:
    _, topo, style, b = name.split("_")
    return topo, style, int(b)


# ---------------------------------------------------------------------------------------
# topologies: sorted list of directed edges (u, v)

def edges_of(topo: str, b: int, rng: random.Random) -> list[tuple[int, int]]:
    if topo == "chain":
        return [(k, k + 1) for k in range(b - 1)]
    if topo == "mesh":
        rows = 1 << (max(b.bit_length() - 1, 0) // 2)
        cols = b // rows
        if rows * cols != b:
            raise ValueError("mesh needs a power of two")
        out = []
        for r in range(rows):
            for c in range(cols):
                k = r * cols + c
                if c + 1 < cols:
                    out += [(k, k + 1), (k + 1, k)]
                if r + 1 < rows:
                    out += [(k, k + cols), (k + cols, k)]
        return sorted(out)
    if topo == "tree":
        out = []
        for i in range(1, b):
            p = (i - 1) // 2
            out += [(p, i), (i, p)]
        return sorted(out)
    if topo == "rand":
        for _ in range(1000):
            order = list(range(b))
            rng.shuffle(order)
            es = {(order[i], order[(i + 1) % b]) for i in range(b)}
            outd = {k: 0 for k in range(b)}
            ind = {k: 0 for k in range(b)}
            ok = True
            for u, v in es:
                outd[u] += 1
                ind[v] += 1
            extra = 0
            tries = 0
            while extra < b and tries < 50 * b + 100:
                tries += 1
                u, v = rng.randrange(b), rng.randrange(b)
                if u == v or (u, v) in es or outd[u] >= MAX_DEG or ind[v] >= MAX_DEG:
                    continue
                es.add((u, v))
                outd[u] += 1
                ind[v] += 1
                extra += 1
            if extra == b and ok:
                return sorted(es)
        raise RuntimeError(f"rand topology B={b}: no draw within the degree cap after 1000 tries")
    raise ValueError(topo)


# ---------------------------------------------------------------------------------------
# functions: expression trees over six leaves

def tt_depends_on_all(expr, nvars: int = 6) -> bool:
    table = [evaluate(expr, [(m >> i) & 1 for i in range(nvars)]) for m in range(1 << nvars)]
    for i in range(nvars):
        if all(table[m] == table[m ^ (1 << i)] for m in range(1 << nvars)):
            return False
    return True


def evaluate(expr, x: list[int]) -> int:
    tag = expr[0]
    if tag == "v":
        return x[expr[1]]
    if tag == "not":
        return 1 - evaluate(expr[1], x)
    a, b = evaluate(expr[1], x), evaluate(expr[2], x)
    return a & b if tag == "and" else (a | b if tag == "or" else a ^ b)


def render(expr, sig: list[str]) -> str:
    tag = expr[0]
    if tag == "v":
        return sig[expr[1]]
    if tag == "not":
        return "(~" + render(expr[1], sig) + ")"
    op = {"and": "&", "or": "|", "xor": "^"}[tag]
    return "(" + render(expr[1], sig) + " " + op + " " + render(expr[2], sig) + ")"


def tt_key(expr) -> str:
    return "".join(str(evaluate(expr, [(m >> i) & 1 for i in range(6)])) for m in range(64))


def ctl_expr(rng: random.Random):
    """Random tree over the five non-self leaves with 4 binary nodes, exactly 2 of them AND/OR and 2 XOR (random places,
    random NOTs), XORed with the self leaf at the root. A flip-flop whose function ANDs its own output (init
    unknown), or a network of mostly AND/OR nodes, collapses to constants that synthesis removes (found while
    building the generator, docs/plan/round5.md amendment 1); the XOR nodes keep every signal live."""
    leaves = [1, 2, 3, 4, 5]
    rng.shuffle(leaves)
    ops = ["xor", "xor", rng.choice(("and", "or")), rng.choice(("and", "or"))]
    rng.shuffle(ops)
    it = iter(ops)

    def build(ls):
        if len(ls) == 1:
            e = ("v", ls[0])
        else:
            cut = rng.randrange(1, len(ls))
            e = (next(it), build(ls[:cut]), build(ls[cut:]))
        return ("not", e) if rng.random() < 0.3 else e

    own = ("not", ("v", 0)) if rng.random() < 0.5 else ("v", 0)
    return ("xor", own, build(leaves))


def dp_expr(rng: random.Random):
    def lit(i):
        return ("not", ("v", i)) if rng.random() < 0.25 else ("v", i)

    t = ("xor", ("xor", lit(0), lit(1)), lit(2))
    u = (rng.choice(("and", "or")), lit(3), lit(4))
    return ("xor", ("xor", t, u), lit(5))


# ---------------------------------------------------------------------------------------
# a design

def pad_block(topo: str, b: int, p: int, out: bool = False) -> int:
    """Block of primary input (or output) p: chain: the first (last) block; others: spread, floor(p B / 8)."""
    if topo == "chain":
        return b - 1 if out else 0
    return p * b // N_PI


def observed(funcs: list[dict], n_edge_out: int, po_ffs: list[int]) -> bool:
    """Every flip-flop of the block reaches an output flip-flop (edge output or primary output) through the
    dependencies; otherwise synthesis sweeps the unobservable ones."""
    deps = [{a[1] for a in f["inputs"] if a[0] == "r"} for f in funcs]
    seen = set(range(2 * n_edge_out)) | set(po_ffs)
    grow = True
    while grow:
        grow = False
        for i in range(N_LE):
            if i in seen:
                for j in deps[i]:
                    if j not in seen:
                        seen.add(j)
                        grow = True
    return len(seen) == N_LE


def draw_block(style: str, slots: list, rng: random.Random, name: str, k: int) -> list[dict]:
    funcs: list[dict] = []
    seen: set[tuple] = set()
    for i in range(N_LE):
        for _ in range(200):
            if style == "dp":
                local = [(i + o) % N_LE for o in (0, 1, 2, 3, -1, -2)]
                expr = dp_expr(rng)
            else:
                others = [x for x in range(N_LE) if x != i]
                rng.shuffle(others)
                local = [i] + others[:5]
                expr = ctl_expr(rng)
            inputs: list = [["r", x] for x in local]
            for slot_id in range(i, len(slots), N_LE):
                inputs[slot_id // N_LE + 1] = ["x", slot_id]
            if not tt_depends_on_all(expr):
                continue
            key = (json.dumps(inputs), tt_key(expr))
            if key in seen:
                continue
            seen.add(key)
            funcs.append({"inputs": inputs, "expr": expr})
            break
        else:
            raise RuntimeError(f"{name}: block {k} function {i} not drawn")
    return funcs


def eval_words(expr, x: list[int], mask: int) -> int:
    tag = expr[0]
    if tag == "v":
        return x[expr[1]]
    if tag == "not":
        return ~eval_words(expr[1], x, mask) & mask
    a, b = eval_words(expr[1], x, mask), eval_words(expr[2], x, mask)
    return a & b if tag == "and" else (a | b if tag == "or" else a ^ b)


def alive(funcs: list[dict], n_slots: int, rng_seed: str) -> bool:
    """The block alone, from the zero state, with random external inputs, 64 parallel trajectories of 48 cycles: every
    flip-flop takes both values in the last 32 cycles and no two flip-flops (or a flip-flop and a complement of another)
    have the same history. This is what a sequential sweep (ABC `scorr`) would merge or turn into a constant."""
    rnd = random.Random(rng_seed)
    mask = (1 << 64) - 1
    state = [0] * N_LE
    hist: list[list[int]] = [[] for _ in range(N_LE)]
    for cycle in range(48):
        ext = [rnd.getrandbits(64) for _ in range(n_slots)]
        new = []
        for f in funcs:
            sig = [state[a[1]] if a[0] == "r" else ext[a[1]] for a in f["inputs"]]
            new.append(eval_words(f["expr"], sig, mask))
        state = new
        if cycle >= 16:
            for i in range(N_LE):
                hist[i].append(state[i])
    sigs = []
    for h in hist:
        if all(w == 0 for w in h) or all(w == mask for w in h):
            return False
        sigs.append(tuple(h))
        sigs.append(tuple(~w & mask for w in h))
    return len(set(sigs[0::2]) | set(sigs[1::2])) == 2 * N_LE


def build_spec(name: str) -> dict:
    topo, style, b = parse_name(name)
    rng = random.Random(f"{SEED}:{name}")
    edges = edges_of(topo, b, rng)
    outs: dict[int, list[tuple[int, int]]] = {k: [] for k in range(b)}
    ins: dict[int, list[tuple[int, int]]] = {k: [] for k in range(b)}
    for u, v in edges:
        outs[u].append((u, v))
    for u, v in edges:
        ins[v].append((u, v))
    # external slots of each block: edge slots in edge order, then primary inputs
    slots: dict[int, list[list]] = {k: [] for k in range(b)}
    for v in range(b):
        for u, _ in ins[v]:
            j = outs[u].index((u, v))
            for t in range(WIDTH):
                slots[v].append(["q", u, WIDTH * j + t])
    for p in range(N_PI):
        slots[pad_block(topo, b, p)].append(["pi", p])
    for k in range(b):
        if len(outs[k]) > MAX_DEG or len(slots[k]) > MAX_SLOTS:
            raise RuntimeError(f"{name}: block {k} over a degree or slot limit")
    po, used = [], {}
    for p in range(N_PO):
        k = pad_block(topo, b, p, True)
        po.append([k, 9 - used.get(k, 0)])  # a block's j-th primary output is flip-flop 9 - j (never an edge output)
        used[k] = used.get(k, 0) + 1
    blocks = []
    for k in range(b):
        po_ffs = [f for kk, f in po if kk == k]
        for _attempt in range(200):
            funcs = draw_block(style, slots[k], rng, name, k)
            if observed(funcs, len(outs[k]), po_ffs) and alive(funcs, len(slots[k]), f"{SEED}:{name}:{k}"):
                break
        else:
            raise RuntimeError(f"{name}: block {k} has an unobservable flip-flop in 200 draws")
        blocks.append({"k": k, "slots": slots[k], "funcs": funcs, "n_out": len(outs[k])})
    return {"name": name, "topology": topo, "style": style, "b": b, "seed": SEED, "edges": [list(e) for e in edges],
            "blocks": blocks, "po": po, "designed_cut": designed_cut(edges, po)}


def designed_cut(edges, po) -> int:
    """Edge nets (WIDTH per edge, each a distinct driving flip-flop) + one net per primary output + one per primary input."""
    return WIDTH * len(edges) + len(po) + N_PI


def verilog(spec: dict) -> str:
    b, style = spec["b"], spec["style"]
    out = [f"// Norns round 5 generated design {spec['name']} (topology {spec['topology']}, style {style}, "
           f"B={b}, seed {spec['seed']}). Known optimal clustering: block b<k> = one CLB.\n"]
    for blk in spec["blocks"]:
        k, slots = blk["k"], blk["slots"]
        ports = "input clk" + (f", input [{len(slots) - 1}:0] x" if slots else "") + ", output [9:0] q"
        out.append(f"module b{k}({ports});")
        if style == "dp":
            out.append("  reg [9:0] r;")
            out.append("  assign q = r;")
            reg = lambda i: f"r[{i}]"  # noqa: E731
        else:
            out.append("  reg " + ", ".join(f"r{i}" for i in range(N_LE)) + ";")
            out.append("  assign q = {" + ", ".join(f"r{i}" for i in reversed(range(N_LE))) + "};")
            reg = lambda i: f"r{i}"  # noqa: E731
        out.append("  always @(posedge clk) begin")
        for i, f in enumerate(blk["funcs"]):
            sig = [reg(a[1]) if a[0] == "r" else f"x[{a[1]}]" for a in f["inputs"]]
            out.append(f"    {reg(i)} <= {render(f['expr'], sig)};")
        out.append("  end")
        out.append("endmodule\n")
    out.append("module top(input clk, input [7:0] pi, output [7:0] po);")
    for k in range(b):
        out.append(f"  wire [9:0] q{k};")
    for blk in spec["blocks"]:
        k, slots = blk["k"], blk["slots"]
        conn = [".clk(clk)"]
        if slots:
            parts = [f"q{s[1]}[{s[2]}]" if s[0] == "q" else f"pi[{s[1]}]" for s in reversed(slots)]
            conn.append(".x({" + ", ".join(parts) + "})")
        conn.append(f".q(q{k})")
        out.append(f"  b{k} u{k}({', '.join(conn)});")
    for p, (k, f) in enumerate(spec["po"]):
        out.append(f"  assign po[{p}] = q{k}[{f}];")
    out.append("endmodule")
    return "\n".join(out) + "\n"


def summary(spec: dict, text: str) -> dict:
    return {"name": spec["name"], "topology": spec["topology"], "style": spec["style"], "b": spec["b"], "seed": spec["seed"],
            "edges": len(spec["edges"]), "luts": N_LE * spec["b"], "ffs": N_LE * spec["b"],
            "max_slots": max(len(x["slots"]) for x in spec["blocks"]),
            "max_out_edges": max(x["n_out"] for x in spec["blocks"]),
            "designed_cut": spec["designed_cut"], "bytes": len(text),
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
        (out_dir / f"{name}.spec.json").write_text(json.dumps(spec, sort_keys=True) + "\n", encoding="utf-8") if name in only else None
    rec = Path(__file__).resolve().parents[1] / "data" / "r5" / "designs.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(rows)} designs; {sum(r['bytes'] for r in rows)} bytes of Verilog")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
