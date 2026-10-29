"""Round 9: how much real structure D' keeps (docs/plan/round9-tpeko-real.md, "What real structure D' keeps").

  python scripts/r9stats.py DESIGN [DESIGN ...]      # run with the Mimir venv python (needs mimir, pymetis)

Reads the cleaned D and the shuffle-1 file of each construction under $R9_OUT/<design>/, measures with the Mimir rent measurer
(recursive METIS bisection, seeds 1 to 3) and the degree distributions of the logic cells, and writes $R9_OUT/<design>/stats.json.
Rent: the standard fit (Mimir ranges, needs >= 512 nodes) and a labelled relaxed fit (B = 4 to N/8) for smaller designs.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from mimir import rent as rent_mod
from mimir.blif import read_blif
from mimir.netlist import COMB, HARD, LATCH

OUT = Path(__import__("os").environ.get("R9_OUT", str(Path.home() / "odin3-ws" / "work" / "r9-out")))
SEEDS = (1, 2, 3)


def quant(xs: list, q: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def dist(xs: list) -> dict:
    return {"n": len(xs), "mean": statistics.fmean(xs) if xs else float("nan"), "median": statistics.median(xs) if xs else float("nan"),
            "p90": quant(xs, 0.9), "max": max(xs) if xs else float("nan")}


def degrees(nl) -> dict:
    sinks = nl.sinks()
    logic = [v for v in range(len(nl)) if nl.kind[v] in (COMB, LATCH, HARD)]
    comb = [v for v in range(len(nl)) if nl.kind[v] == COMB]
    return {"logic_nodes": len(logic), "comb_in_degree": dist([len(set(nl.fanin[v])) for v in comb]),
            "net_fanout_logic_driven": dist([len(sinks[v]) for v in logic if sinks[v]]),
            "net_fanout_all": dist([len(sinks[v]) for v in range(len(nl)) if sinks[v] and nl.kind[v] != "const"])}


def rent(nl, relaxed: bool) -> dict:
    nodes, nets = rent_mod.build_nets(nl)
    out = {"nodes": len(nodes)}
    if not relaxed and len(nodes) < rent_mod.MIN_NODES:
        out["note"] = "below the 512-node floor of the standard fit"
        return out
    old = rent_mod.REGION2_DIV
    rent_mod.REGION2_DIV = 8 if relaxed else old
    try:
        ps, r2s, pts = [], [], []
        for s in SEEDS:
            c = rent_mod.curve(nodes, nets, s)
            f = rent_mod.fit(c, len(nodes))
            if f is not None:
                ps.append(f.p)
                r2s.append(f.r2)
                pts.append(f.points)
        out.update({"p_mean": statistics.fmean(ps) if ps else None, "p_seeds": ps, "r2_mean": statistics.fmean(r2s) if r2s else None,
                    "points": pts, "relaxed_fit": relaxed})
    finally:
        rent_mod.REGION2_DIV = old
    return out


def measure(path: Path) -> dict:
    nl = read_blif(path)
    return {"degrees": degrees(nl), "rent_standard": rent(nl, False), "rent_relaxed": rent(nl, True)}


def main(argv: list) -> int:
    for d in argv:
        root = OUT / d
        res = {"D": measure(next(root.glob(f"{d}.clean.blif")))}
        for cons in ("own", "foreign"):
            blif = root / cons / "sh1" / "design.blif"
            if blif.is_file():
                res[cons] = measure(blif)
                st = json.loads((root / cons / "struct.json").read_text())
                per_net = [len({st["cl"][v] for v in vs}) for vs in st["hn"]]
                res[cons]["clusters_per_logic_net"] = dist(per_net)
        (root / "stats.json").write_text(json.dumps(res, indent=1))
        for k, v in res.items():
            r = v["rent_standard"]
            rr = v["rent_relaxed"]
            print(d, k, "nodes", r["nodes"], "rent_p std", r.get("p_mean"), "relaxed", rr.get("p_mean"),
                  "in-degree mean", round(v["degrees"]["comb_in_degree"]["mean"], 2), "fanout mean", round(v["degrees"]["net_fanout_all"]["mean"], 2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
