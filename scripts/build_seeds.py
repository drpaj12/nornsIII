"""Seed builders: Urd (provenance hierarchy) and Verdandi (Loki L2 partitions) to VPR seeds.

Inputs (per design, produced by scripts/frontend.py, build_graph_clusters.py and the baseline
run): provenance BLIF, partition members, and the baseline VPR artifacts (initial.place,
final.flat_place). Outputs, per seed and variant:

  seeds/<seed>-full.place     soft seed, fine order = baseline analytic order inside a cluster
  seeds/<seed>-inter.place    soft seed, intra-cluster order shuffled (inter-cluster only)
  seeds/<seed>-full.flat_place  atom-level seed coordinates (retention/displacement)
  seeds/<seed>-hard.xml       hard seed: one PartitionRegion per cluster
  seeds/clusters.json         cluster -> CLBs, region bbox, seed positions

The quotient-graph layout contracts each cluster to a node weighted by inter-cluster net cuts,
lays it out with networkx spring_layout (seed 1), and scales it onto the die; CLB slots are then
taken nearest-first per cluster. Pad CLBs never move (their IO sites are fixed by the arch),
mult_36 macros stay anchored (their tile footprint has a placement orientation) and adder carry
chains move as a vertical run (VPR's carries are placement macros).

Usage: python scripts/build_seeds.py [design ...]
"""

from __future__ import annotations

import collections
import random
import sys
from pathlib import Path

import nornlib as nl

CLASSES = ("logic", "memory", "mult", "pad")


def baseline_paths(design: str) -> tuple[Path, Path, Path]:
    base = nl.runs_dir(design, "runs", "baseline")
    return base / "initial.place", base / "final.flat_place", base / "vpr.out"


def block_models(blif: Path, atom_names: set[str] | None = None) -> dict[str, str]:
    out = {}
    for b in nl.parse_blif(blif, atom_names, nl.arch_output_ports(nl.ARCH))["blocks"]:
        out[b["name"]] = b.get("model", b["kind"])
    return out


def block_clusters(design: str, blocks: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    """seed name -> {block name -> cluster number} for every seed family that exists."""
    seeds: dict[str, dict[str, int]] = {}
    urd: dict[str, int] = {}
    modules = sorted({str(b["module"]) for b in blocks if b["module"]}
                     | {"<flat>"})
    index = {m: i for i, m in enumerate(modules)}
    for b in blocks:
        urd[str(b["name"])] = index[str(b["module"])] if b["module"] else index["<flat>"]
    seeds["urd"] = urd
    parts = nl.runs_dir(design, "partitions")
    for seed in ("louvain", "spectral", "affinity", "kmeans_k", "kmeans_2k", "kmeans_4k"):
        members = parts / seed / "members.json"
        if members.is_file():
            seeds[seed] = {str(k): int(v) for k, v in nl.read_json(members).items()}
    return seeds



def adder_chains(blocks: list[dict[str, object]], flat: nl.Flat,
                 id2name: dict[str, str]) -> list[dict[str, object]]:
    """Carry-chain groups at CLB level: VPR places a chain as a vertical run (direct y -1).

    A chain is an ordered list of CLBs, head first (an adder in the head drives the next CLB's
    adder cin). The CLB edges come from the atom-level cout->cin nets (many adders can share a
    CLB); seeds move each chain as one run kept in the same column, or VPR's macro verification
    rejects the placement.
    """
    adders = [b for b in blocks if b.get("model") == "adder" and b.get("pins")]
    cout_clbs: dict[str, set[str]] = collections.defaultdict(set)
    cin_pairs: list[tuple[str, str]] = []
    for b in adders:
        pins = {k.split("[")[0]: v for k, v in b["pins"].items()}
        clb = flat.clb_of(str(b["name"]))
        if clb is None:
            continue
        if "cout" in pins:
            cout_clbs[pins["cout"]].add(clb)
        if "cin" in pins and pins["cin"] != "gnd":
            cin_pairs.append((clb, pins["cin"]))
    edges: dict[str, str] = {}
    has_pred: set[str] = set()
    for clb, cin_net in cin_pairs:
        for pred in sorted(cout_clbs.get(cin_net, ())):
            if pred != clb and pred not in edges and clb not in has_pred:
                edges[pred] = clb
                has_pred.add(clb)
    chains: list[dict[str, object]] = []
    seen: set[str] = set()
    for head in [c for c in edges if c not in has_pred] + sorted(edges):
        if head in seen:
            continue
        run = [head]
        seen.add(head)
        while run[-1] in edges and edges[run[-1]] not in seen:
            run.append(edges[run[-1]])
            seen.add(run[-1])
        names = [id2name.get(c) for c in run]
        if len(names) > 1 and all(names):
            chains.append({"blocks": names, "clbs": names})
    return chains


def slot_runs(slots: list[tuple[int, int, int, int]]) -> list[list[tuple[int, tuple[int, int, int, int]]]]:
    """Vertical runs of logic slots: same x, consecutive y (descending), with their indices."""
    by_x: dict[int, list[tuple[int, tuple[int, int, int, int]]]] = collections.defaultdict(list)
    for i, slot in enumerate(slots):
        by_x[slot[0]].append((i, slot))
    runs = []
    for x in sorted(by_x):
        column = sorted(by_x[x], key=lambda item: -item[1][1])
        run: list[tuple[int, tuple[int, int, int, int]]] = []
        last_y = None
        for item in column:
            y = item[1][1]
            if last_y is not None and y != last_y - 1:
                runs.append(run)
                run = []
            run.append(item)
            last_y = y
        if run:
            runs.append(run)
    return runs


def classify(pb_types: set[str]) -> str:
    if pb_types and pb_types <= {"inpad", "outpad"}:
        return "pad"
    low = {p.lower() for p in pb_types}
    if any("memory" in p or "ram" in p for p in low):
        return "memory"
    if any("mult" in p for p in low):
        return "mult"
    return "logic"


def build(design: str) -> int:
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    init_place, final_flat, _log = baseline_paths(design)
    if not (blif.is_file() and init_place.is_file() and final_flat.is_file()):
        print(f"{design}: missing inputs (frontend, clusters or baseline)")
        return 2
    flat = nl.Flat(final_flat)
    parsed = nl.parse_blif(blif, set(flat.atoms), nl.arch_output_ports(nl.ARCH))
    blocks = parsed["blocks"]
    models = block_models(blif, set(flat.atoms))
    seeds = block_clusters(design, blocks)
    place = nl.Place(init_place)
    chains = adder_chains(parsed["blocks"], flat,
                          {r["num"]: r["name"] for r in place.rows})
    width, height = nl.grid_size(place)
    clb_types = {clb: classify(types) for clb, types in flat.clb_types().items()}
    clb_class = {r["name"]: clb_types.get(r["num"], "logic") for r in place.rows}
    clb_atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        clb_atoms[row[4]].append(atom)
    # block -> cluster per seed; a CLB takes the majority cluster of its non-pad atoms
    block_cluster = {seed: {name: cl for name, cl in mapping.items()}
                     for seed, mapping in seeds.items()}
    clb_cluster: dict[str, dict[str, int | None]] = {}
    for seed, mapping in block_cluster.items():
        per: dict[str, int | None] = {}
        for clb in place.rows:
            counts = collections.Counter()
            for atom in clb_atoms.get(clb["num"], []):
                if atom in mapping:
                    counts[mapping[atom]] += 1
            per[clb["name"]] = counts.most_common(1)[0][0] if counts else None
        clb_cluster[seed] = per
    # cluster adjacency from the BLIF netlist, for the quotient layout
    out: dict[str, object] = {"design": design, "seeds": {}}
    base_slots = collections.defaultdict(list)
    for r in place.rows:
        base_slots[clb_class.get(r["name"], "logic")].append(
            (int(r["x"]), int(r["y"]), int(r["sub"]), int(r["layer"])))
    for seed, per in clb_cluster.items():
        clusters: dict[int, list[str]] = collections.defaultdict(list)
        for clb, cl in per.items():
            if cl is not None and clb_class.get(clb) not in ("pad", "mult"):
                clusters[cl].append(clb)
        if not clusters:
            continue
        result = build_seed(design, seed, clusters, clb_class, base_slots, place, width, height,
                            blocks, block_cluster[seed], flat, chains)
        out["seeds"][seed] = result
        print(f"{design}/{seed}: {len(clusters)} clusters, "
              f"{sum(len(v) for v in clusters.values())} CLBs")
    nl.write_json(nl.runs_dir(design, "seeds", "clusters.json"), out)
    return 0


def build_seed(design: str, seed: str, clusters: dict[int, list[str]],
               clb_types: dict[str, str], base_slots: dict[str, list[tuple[int, int, int, int]]],
               place: nl.Place, width: int, height: int,
               blocks: list[dict[str, object]], block_cluster: dict[str, int],
               flat: nl.Flat, chains: list[dict[str, object]]) -> dict[str, object]:
    import networkx as nx

    # quotient graph: one node per cluster, weight = inter-cluster net count
    g = nx.Graph()
    for cl in clusters:
        g.add_node(cl)
    cut = collections.Counter()
    driver = {str(b["name"]): str(b["name"]) for b in blocks}
    for b in blocks:
        dst_cl = block_cluster.get(str(b["name"]))
        if dst_cl is None:
            continue
        for net in b["inputs"]:
            src = driver.get(net)
            if src is None:
                continue
            src_cl = block_cluster.get(src)
            if src_cl is not None and src_cl != dst_cl:
                cut[(min(src_cl, dst_cl), max(src_cl, dst_cl))] += 1
    for (a, b), w in cut.items():
        g.add_edge(a, b, weight=w)
    if len(g) > 1:
        pos = nx.spring_layout(g, seed=1, weight="weight", iterations=80)
    else:
        pos = {next(iter(g)): (0.0, 0.0)}
    logic_xy = base_slots.get("logic", [])
    xs = [s[0] for s in logic_xy] or [1, width - 2]
    ys = [s[1] for s in logic_xy] or [1, height - 2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    target = {}
    for cl, (px, py) in pos.items():
        target[cl] = (x0 + (px + 1.0) / 2.0 * max(1, x1 - x0),
                      y0 + (py + 1.0) / 2.0 * max(1, y1 - y0))
    # per class, assign the slots nearest each cluster's target
    assignment_full: dict[str, tuple[int, int, int, int]] = {}
    assignment_inter: dict[str, tuple[int, int, int, int]] = {}
    rng = random.Random(7)
    for cls in CLASSES:
        if cls in ("pad", "mult"):
            # pad sites are fixed by the arch; mult_36 macros have a placement orientation and
            # stay anchored where the analytic placer put them (agent default, EXPERIMENT.md)
            for r in place.rows:
                if clb_types.get(r["name"]) == cls:
                    coords = (int(r["x"]), int(r["y"]), int(r["sub"]), int(r["layer"]))
                    assignment_full[r["name"]] = coords
                    assignment_inter[r["name"]] = coords
            continue
        slots = list(base_slots.get(cls, []))
        need: list[tuple[float, int, str]] = []
        for cl, names in clusters.items():
            for name in names:
                if clb_types.get(name) == cls:
                    px, py = target[cl]
                    need.append(((px, py), cl, name))
        # greedy nearest slot, clusters in a stable layout order
        by_cluster: dict[int, list[str]] = collections.defaultdict(list)
        for point, cl, name in need:
            by_cluster[cl].append(name)
        order = sorted(by_cluster, key=lambda c: (target[c][0], target[c][1], c))
        used: set[int] = set()
        base_xy = {r["name"]: (float(r["x"]), float(r["y"])) for r in place.rows}
        # carry chains first: a chain occupies one vertical run, head at the top (VPR direct
        # y_offset -1); its CLBs keep that run in both variants
        chain_names: set[str] = set()
        clb2cl = {c: cl for cl, members in clusters.items() for c in members}
        if cls == "logic" and chains:
            runs = slot_runs(slots)
            for chain in sorted(chains, key=lambda c: -len(c["clbs"])):
                members = [c for c in chain["clbs"] if clb_types.get(c) == "logic"]
                if len(members) < 2:
                    continue
                counts = collections.Counter(clb2cl[c] for c in members if c in clb2cl)
                if counts:
                    cl = counts.most_common(1)[0][0]
                    px, py = target.get(cl, (0.0, 0.0))
                else:
                    px, py = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                best = None
                n = len(members)
                for run in runs:
                    # aligned, non-overlapping windows keep a long run usable by later chains
                    starts = list(range(0, len(run) - n + 1, n))
                    if starts and starts[-1] + n < len(run):
                        starts.append(len(run) - n)
                    for start in starts:
                        if start + n > len(run):
                            continue
                        head = run[start:start + n]
                        if any(i in used for i, _s in head):
                            continue
                        cx = head[0][1][0]
                        cy = sum(s[1] for _i, s in head) / n
                        dist = (cx - px) ** 2 + (cy - py) ** 2
                        if best is None or dist < best[0]:
                            best = (dist, head)
                if best is None:
                    continue
                for name, (i, slot) in zip(members, best[1]):
                    assignment_full[name] = slot
                    assignment_inter[name] = slot
                    used.add(i)
                    chain_names.add(name)
        for cl in order:
            names = [n for n in by_cluster[cl] if n not in chain_names]
            if not names:
                continue
            px, py = target[cl]
            avail = [(i, s) for i, s in enumerate(slots) if i not in used]
            avail.sort(key=lambda item: (item[1][0] - px) ** 2 + (item[1][1] - py) ** 2)
            picked = [s for _i, s in avail[:len(names)]]
            picked_ids = {i for i, _s in avail[:len(names)]}
            used |= picked_ids
            # full: preserve the analytic fine order inside the cluster
            fine = sorted(names, key=lambda n: base_xy.get(n, (0.0, 0.0)))
            for name, slot in zip(fine, sorted(picked)):
                assignment_full[name] = slot
            shuffled = list(picked)
            rng.shuffle(shuffled)
            for name, slot in zip(names, shuffled):
                assignment_inter[name] = slot
        # every remaining CLB of this class takes a leftover slot (never a duplicate)
        leftover = [s for i, s in enumerate(slots) if i not in used]
        rest = [r["name"] for r in place.rows
                if clb_types.get(r["name"]) == cls and r["name"] not in assignment_full]
        for name, slot in zip(rest, sorted(leftover)):
            assignment_full[name] = slot
            assignment_inter[name] = slot
    # regions: bbox of the full-seed slots per cluster, expanded, legal-class aware
    regions = {}
    site_map = {cls: {(s[0], s[1]) for s in slots} for cls, slots in base_slots.items()}
    for cl, names in clusters.items():
        coords = [assignment_full[n] for n in names if n in assignment_full]
        if not coords:
            continue
        xs2 = [c[0] for c in coords]
        ys2 = [c[1] for c in coords]
        n_logic = sum(1 for name in names if clb_types.get(name) == "logic"
                      and name in assignment_full)
        expand = 2
        while True:
            lo_x, hi_x = max(0, min(xs2) - expand), min(width - 1, max(xs2) + expand)
            lo_y, hi_y = max(0, min(ys2) - expand), min(height - 1, max(ys2) + expand)
            room = sum(1 for x, y in site_map.get("logic", set())
                       if lo_x <= x <= hi_x and lo_y <= y <= hi_y)
            if room >= n_logic or (lo_x == 0 and hi_x == width - 1
                                   and lo_y == 0 and hi_y == height - 1):
                break
            expand += 1
        need_classes = {clb_types[n] for n in names if n in assignment_full}
        for cls in need_classes - {"logic", "pad"}:
            if not any(x in range(lo_x, hi_x + 1) and y in range(lo_y, hi_y + 1)
                       for x, y in site_map.get(cls, set())):
                px, py = target[cl]
                near = sorted(site_map.get(cls, set()),
                              key=lambda s: (s[0] - px) ** 2 + (s[1] - py) ** 2)
                if near:
                    sx, sy = near[0]
                    lo_x, hi_x = max(0, min(lo_x, sx)), min(width - 1, max(hi_x, sx))
                    lo_y, hi_y = max(0, min(lo_y, sy - 1)), min(height - 1, max(hi_y, sy + 1))
        regions[cl] = [lo_x, lo_y, hi_x, hi_y]
    write_place(design, seed, "full", place, assignment_full)
    write_place(design, seed, "inter", place, assignment_inter)
    write_flat(design, seed, "full", place, assignment_full, flat)
    write_flat(design, seed, "inter", place, assignment_inter, flat)
    write_constraints(design, seed, regions, clusters, place, flat)
    return {"n_clusters": len(clusters), "clb_counts": {str(k): len(v) for k, v in clusters.items()},
            "clbs": {str(k): sorted(v) for k, v in clusters.items()},
            "regions": {str(k): v for k, v in regions.items()}}


def write_place(design: str, seed: str, variant: str, place: nl.Place,
                assignment: dict[str, tuple[int, int, int, int]]) -> None:
    path = nl.runs_dir(design, "seeds", f"{seed}-{variant}.place")
    out = nl.Place.__new__(nl.Place)
    out.header = place.header
    out.rows = []
    for r in place.rows:
        x, y, sub, layer = assignment.get(r["name"],
                                          (int(r["x"]), int(r["y"]), int(r["sub"]),
                                           int(r["layer"])))
        out.rows.append({"name": r["name"], "x": str(x), "y": str(y), "sub": str(sub),
                         "layer": str(layer), "num": r["num"]})
    out.write(path)


def write_flat(design: str, seed: str, variant: str, place: nl.Place,
               assignment: dict[str, tuple[int, int, int, int]], flat: nl.Flat) -> None:
    path = nl.runs_dir(design, "seeds", f"{seed}-{variant}.flat_place")
    out = ["# Norns III seed flat placement (atom x y layer subtile)"]
    for atom, (x, y, layer, sub, clb, _pb) in flat.atoms.items():
        sx, sy, ssub, slayer = assignment.get(clb, (int(x), int(y), sub, layer))
        out.append(f"{atom} {sx} {sy} {slayer} {ssub}")
    nl.ensure_dir(path.parent)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _esc(name: str) -> str:
    return name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(
        '"', "&quot;")


def write_constraints(design: str, seed: str, regions: dict[int, list[int]],
                      clusters: dict[int, list[str]], place: nl.Place,
                      flat: nl.Flat) -> None:
    path = nl.runs_dir(design, "seeds", f"{seed}-hard.xml")
    clb_atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        clb_atoms[row[4]].append(atom)
    name_to_id = {r["name"]: r["num"] for r in place.rows}
    lines = ['<vpr_constraints tool_name="vpr">', "   <partition_list>"]
    for cl in sorted(clusters):
        if cl not in regions:
            continue
        lo_x, lo_y, hi_x, hi_y = regions[cl]
        lines.append(f'   <partition name="c{cl}">')
        for clb in sorted(clusters[cl]):
            for atom in clb_atoms.get(name_to_id.get(clb, ""), []):
                lines.append(f'       <add_atom name_pattern="{_esc(atom)}"/>')
        lines.append(f'       <add_region x_low="{lo_x}" y_low="{lo_y}" '
                     f'x_high="{hi_x}" y_high="{hi_y}"/>')
        lines.append("   </partition>")
    lines += ["   </partition_list>", "</vpr_constraints>"]
    nl.ensure_dir(path.parent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    designs = argv or list(nl.DESIGN_ORDER)
    rc = 0
    for design in designs:
        rc |= build(design)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
