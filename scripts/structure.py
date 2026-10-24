"""RQ-N1 and RQ-N2: structure analyses that need no VPR run.

N1  Does VPR's unseeded flat placement already rediscover the hierarchy? On each design's
    baseline, for the analytic initial placement, VPR's final placement and a random null
    (logic-CLB coordinates permuted, 20 samples), per labelling (module, word):
      nmi      NMI between a g x g grid partition of the logic CLBs (g = ceil(sqrt(labels)),
               at least 2) and the labels;
      density  CLB-weighted mean over labels of (CLBs of the label) / (area of the label's
               bounding box in grid tiles); higher = more compact.
N2  Does a design's structure predict the seed gain? Per design, on the netlist graph
    (undirected, simple): Louvain modularity Q; z-score of Q against a degree-preserving null
    (double edge swaps, 20 samples); a Rent exponent p from BFS balls (terminals = edges leaving
    the ball, fitted over geometric ball sizes, 40 seeds per size); the inverse Rent exponent is
    -p (a lower exponent is a more local, more hierarchical design). Spearman against the
    per-design gain 1 - wirelength ratio of the Urd full seed (round 1), of the best round-1
    family, and of the best round-2 word family.

Usage: python scripts/structure.py n1|n2|all [design ...]
Writes data/analysis/n1.json and data/analysis/n2.json.
"""

from __future__ import annotations

import collections
import json
import math
import random
import statistics
import sys

import nornlib as nl

NULL_SAMPLES = 20


def labels_of(design: str):
    import build_word_seeds as bws
    import build_seeds as bs
    blif, flat, blocks, place, chains, clb_class, clb_atoms, _slots = bws.prepare(design)
    urd = bs.block_clusters(design, blocks)["urd"]
    mod = bws.majority(place, clb_atoms, urd)
    members_path = nl.runs_dir(design, "words", "members.json")
    members = nl.read_json(members_path)
    ids = sorted({m["word"] for m in members.values() if m["word"]})
    widx = {w: i for i, w in enumerate(ids)}
    word = bws.majority(place, clb_atoms, {n: widx[m["word"]] for n, m in members.items()
                                           if m["word"]})
    return place, clb_class, mod, word


def nmi(a: list[int], b: list[int]) -> float:
    from sklearn.metrics import normalized_mutual_info_score
    return float(normalized_mutual_info_score(a, b))


def metrics(coords, names, labels, sites) -> tuple[float, float]:
    """(nmi, density) of a placement for the CLBs in names with a label."""
    names = [n for n in names if labels.get(n) is not None]
    if len(names) < 4:
        return float("nan"), float("nan")
    n_lab = len(set(labels[n] for n in names))
    if n_lab < 2:
        return float("nan"), float("nan")
    g = max(2, math.ceil(math.sqrt(n_lab)))
    xs = [coords[n][0] for n in names]
    ys = [coords[n][1] for n in names]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    gx = [min(g - 1, int((coords[n][0] - x0) * g / (x1 - x0 + 1))) for n in names]
    gy = [min(g - 1, int((coords[n][1] - y0) * g / (y1 - y0 + 1))) for n in names]
    grid = [a * g + b for a, b in zip(gx, gy)]
    score = nmi(grid, [labels[n] for n in names])
    groups: dict[int, list[str]] = collections.defaultdict(list)
    for n in names:
        groups[labels[n]].append(n)
    num = den = 0.0
    for members in groups.values():
        if len(members) < 2:
            continue
        lx = [coords[n][0] for n in members]
        ly = [coords[n][1] for n in members]
        area = (max(lx) - min(lx) + 1) * (max(ly) - min(ly) + 1)
        num += len(members) * (len(members) / area)
        den += len(members)
    return score, (num / den if den else float("nan"))


def n1_design(design: str) -> dict[str, object]:
    place, clb_class, mod, word = labels_of(design)
    base = nl.runs_dir(design, "runs", "baseline")
    logic = [r["name"] for r in place.rows if clb_class.get(r["name"]) == "logic"]
    init = {n: (c[0], c[1]) for n, c in place.coords().items()}
    final = {n: (c[0], c[1]) for n, c in nl.Place(base / "final.place").coords().items()}
    sites = sorted({init[n] for n in logic})
    rng = random.Random(5)
    out: dict[str, object] = {"design": design, "logic_clbs": len(logic)}
    for lab_name, labels in (("module", mod), ("word", word)):
        cell: dict[str, object] = {}
        names = [n for n in logic if labels.get(n) is not None]
        if lab_name == "word":
            names = [n for n in names if labels[n] is not None and labels[n] < 10 ** 9]
        cell["labelled_clbs"] = len(names)
        cell["labels"] = len({labels[n] for n in names})
        for tag, coords in (("initial", init), ("final", final)):
            cell[tag] = metrics(coords, names, labels, sites)
        nulls = []
        slots = [init[n] for n in logic]
        for _ in range(NULL_SAMPLES):
            perm = list(slots)
            rng.shuffle(perm)
            nulls.append(metrics(dict(zip(logic, perm)), names, labels, sites))
        for i, key in enumerate(("nmi", "density")):
            vals = [x[i] for x in nulls if not math.isnan(x[i])]
            cell[f"null_{key}_mean"] = statistics.mean(vals) if vals else float("nan")
            cell[f"null_{key}_sd"] = statistics.pstdev(vals) if vals else float("nan")
        out[lab_name] = cell
    return out


def n1(designs: list[str]) -> None:
    res = [n1_design(d) for d in designs]
    for r in res:
        print(r["design"], {k: (v["final"], v["null_nmi_mean"]) for k, v in r.items()
                            if isinstance(v, dict)})
    nl.write_json(nl.DATA / "analysis" / "n1.json", {"samples": NULL_SAMPLES, "designs": res})


# ---------------------------------------------------------------------------------------

def load_graph(design: str):
    import networkx as nx
    g = nl.read_json(nl.runs_dir(design, "graph.json"))
    graph = nx.Graph()
    graph.add_nodes_from(n["id"] for n in g["nodes"])
    for e in g["edges"]:
        if e["src"] != e["dst"]:
            graph.add_edge(e["src"], e["dst"])
    graph.remove_nodes_from([n for n in list(graph) if graph.degree(n) == 0])
    return graph


def modularity(graph, seed: int = 1) -> float:
    import networkx as nx
    comms = nx.community.louvain_communities(graph, seed=seed)
    return float(nx.community.modularity(graph, comms))


def rent_exponent(graph, seed: int = 3) -> tuple[float, int]:
    """p of T = t B^p over BFS balls (T = edges leaving the ball)."""
    nodes = sorted(graph)
    rng = random.Random(seed)
    n = len(nodes)
    sizes = []
    b = 4.0
    while b <= n / 4:
        sizes.append(int(b))
        b *= 1.6
    xs, ys = [], []
    for size in sizes:
        terminals = []
        for _ in range(40):
            start = rng.choice(nodes)
            ball = {start}
            frontier = [start]
            while frontier and len(ball) < size:
                nxt = []
                for u in frontier:
                    for v in graph[u]:
                        if v not in ball and len(ball) < size:
                            ball.add(v)
                            nxt.append(v)
                frontier = nxt
            if len(ball) < size:
                continue
            terminals.append(sum(1 for u in ball for v in graph[u] if v not in ball))
        if terminals and statistics.mean(terminals) > 0:
            xs.append(math.log(size))
            ys.append(math.log(statistics.mean(terminals)))
    if len(xs) < 3:
        return float("nan"), len(xs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    p = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return p, len(xs)


def n2_design(design: str) -> dict[str, object]:
    import networkx as nx
    graph = load_graph(design)
    q = modularity(graph)
    nulls = []
    for i in range(NULL_SAMPLES):
        h = graph.copy()
        nswap = min(10 * h.number_of_edges(), 200000)
        nx.double_edge_swap(h, nswap=nswap, max_tries=nswap * 20, seed=100 + i)
        nulls.append(modularity(h, seed=1))
    mean, sd = statistics.mean(nulls), statistics.pstdev(nulls)
    p, npts = rent_exponent(graph)
    return {"design": design, "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(), "q": q, "null_q_mean": mean, "null_q_sd": sd,
            "q_z": (q - mean) / sd if sd > 0 else float("nan"), "rent_p": p,
            "rent_points": npts}


def gains(design: str) -> dict[str, float | None]:
    import report
    recs = [r for r in report.load_records(design) if r.get("rc") == 0]
    base = report.pick(recs, "baseline")

    def wl(seed: str) -> float | None:
        return report.ratio(report.pick(recs, "soft", seed, "full"), base, "wirelength")

    r1 = [wl(s) for s in report.FAMILIES]
    r1 = [x for x in r1 if x is not None]
    r2 = [wl(s) for s in ("words", "slices", "hier", "words_partial")]
    r2 = [x for x in r2 if x is not None]
    return {"urd": 1 - wl("urd") if wl("urd") else None,
            "best_r1": 1 - min(r1) if r1 else None,
            "best_r2": 1 - min(r2) if r2 else None}


def n2(designs: list[str]) -> None:
    from scipy import stats
    rows = []
    for d in designs:
        row = n2_design(d)
        row["gain"] = gains(d)
        rows.append(row)
        print(d, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()
                  if k != "gain"})
    corr = {}
    for gname in ("urd", "best_r1", "best_r2"):
        for pname, sign in (("q", 1), ("q_z", 1), ("rent_p", -1)):
            pairs = [(sign * r[pname], r["gain"][gname]) for r in rows
                     if r["gain"][gname] is not None and not math.isnan(r[pname])]
            if len(pairs) >= 5:
                rho, p = stats.spearmanr([a for a, _ in pairs], [b for _, b in pairs])
                corr[f"{gname}~{pname}"] = {"rho": float(rho), "p": float(p), "n": len(pairs)}
    nl.write_json(nl.DATA / "analysis" / "n2.json",
                  {"samples": NULL_SAMPLES, "designs": rows, "spearman": corr})


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "all"
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    if mode in ("n1", "all"):
        n1(designs)
    if mode in ("n2", "all"):
        n2(designs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
