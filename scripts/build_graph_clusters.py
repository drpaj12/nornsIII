"""Verdandi seeds: Loki L2 clusterings of the Odin III BLIF.

Norns builds the L0-schema ``graph.json`` from the same BLIF VPR places (nodes = BLIF block
names, so partitions map back exactly to VPR atoms); the four clusterings are Loki's own
``loki.analysis.cluster`` implementations, written through ``run_cluster`` as partition records.

Loki's own L0 build path was tried first: its ``key.json`` names come from the Odin III Python
API (dotted instance names) and do not join to the BLIF/VPR atom names (provenance names), so
the graph is built here from the identical netlist instead (agent default, EXPERIMENT.md).

Usage: python scripts/build_graph_clusters.py [design ...]
Writes runs/<design>/graph.json, runs/<design>/partitions/<seed>/*.json,
runs/<design>/partitions/<seed>/members.json (node -> cluster, the join the seeds use).
"""

from __future__ import annotations

import sys
from pathlib import Path

import nornlib as nl


def _label(name: str, kind: str, cell_type: str, module: str, line: int) -> dict[str, object]:
    hdl_file, hdl_line = "", 0
    _mod, _leaf, hdl_file, hdl_line = nl.provenance_parts(name)
    return {
        "cell_type": cell_type, "construct_type": "", "construct_types": "",
        "n_construct_cells": 0, "module_path": module, "bus_name": "", "bit_index": 0,
        "role": "unknown", "hdl_file": hdl_file, "hdl_line": hdl_line or line,
        "hdl_col": 0, "hdl_end_line": hdl_line or line, "hdl_end_col": 0, "n_spans": 1,
    }


def build_graph(blif: Path, design: str, atom_names: set[str] | None = None) -> dict[str, object]:
    parsed = nl.parse_blif(blif, atom_names, nl.arch_output_ports(nl.ARCH))
    skip = {"gnd", "vcc", "unconn", ""}
    blocks = [b for b in parsed["blocks"] if b["name"] and b["name"] not in skip]
    driver: dict[str, str] = {}
    for b in blocks:
        driver.setdefault(b["name"], b["name"])  # block output net names the block
    fan_in: dict[str, set[str]] = {b["name"]: set() for b in blocks}
    fan_out: dict[str, int] = {b["name"]: 0 for b in blocks}
    edges: list[dict[str, object]] = []
    for b in blocks:
        for net in b["inputs"]:
            src = driver.get(net)
            if src is None or src == b["name"]:
                continue
            fan_in[b["name"]].add(net)
            fan_out[src] = fan_out.get(src, 0) + 1
            edges.append({"src": src, "dst": b["name"], "net": net,
                          "pin": f"i{len(fan_in[b['name']]) - 1}"})
    # combinational level over .names (latch/hard outputs are level 0 sources)
    preds: dict[str, set[str]] = {}
    succs: dict[str, set[str]] = {}
    for b in blocks:
        preds[b["name"]] = set()
        succs.setdefault(b["name"], set())
    for b in blocks:
        if b["kind"] != "lut":
            continue
        for net in b["inputs"]:
            src = driver.get(net)
            if src is None or src == b["name"]:
                continue
            preds[b["name"]].add(src)
            succs.setdefault(src, set()).add(b["name"])
    level: dict[str, int] = {b["name"]: 0 for b in blocks}
    indeg = {name: len(preds.get(name, ())) for name in level}
    ready = [name for name, count in indeg.items() if count == 0]
    while ready:
        name = ready.pop()
        for nxt in succs.get(name, ()):
            level[nxt] = max(level[nxt], level[name] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    nodes = []
    for b in blocks:
        table, lw = nl.lut_table_hex(b) if b["kind"] == "lut" else ("", 0)
        kind = {"lut": "lut", "latch": "ff", "hard": "hard"}.get(b["kind"], "hard")
        nodes.append({
            "id": b["name"], "kind": kind,
            "features": {"fan_in": len(fan_in[b["name"]]), "fan_out": fan_out.get(b["name"], 0),
                         "level": level.get(b["name"], 0), "lut_width": lw,
                         "lut_table": table, "is_seq": int(b["kind"] == "latch"),
                         "is_const": 0, "hard_ports": len(b["inputs"]) if kind == "hard" else 0},
            "labels": _label(b["name"], kind, b["kind"], b["module"], 0),
        })
    return {"schema": 1, "design": design, "floor": "f1-k6", "nodes": nodes, "edges": edges}


def _loki():
    import loki.analysis.cluster as cluster
    from loki.analysis.graphio import load_graph
    from loki.schemas import dump_json
    return cluster, load_graph, dump_json


def run_design(design: str) -> int:
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    info_path = nl.runs_dir(design, "netlist", "info.json")
    if not blif.is_file():
        print(f"{design}: no BLIF (run scripts/frontend.py)")
        return 2
    modules = nl.read_json(info_path).get("modules") or 1
    flat_path = nl.runs_dir(design, "runs", "baseline", "final.flat_place")
    atom_names = set(nl.Flat(flat_path).atoms) if flat_path.is_file() else None
    if atom_names is None:
        print(f"{design}: no baseline flat placement (run matrix.py baseline first)")
        return 2
    graph_path = nl.runs_dir(design, "graph.json")
    graph = build_graph(blif, design, atom_names)
    cluster_mod, load_graph, dump_json = _loki()
    from loki.schemas import validate_graph
    errors = validate_graph(graph)
    if errors:
        print(f"{design}: graph.json invalid: {errors[:3]}")
        return 2
    nl.ensure_dir(graph_path.parent)
    graph_path.write_text(dump_json(graph), encoding="utf-8")
    g = load_graph(graph_path)
    base = nl.runs_dir(design, "partitions")
    k = max(2, int(modules) if modules > 1 else 2)
    jobs = [("louvain", ["louvain"], k), ("spectral", ["spectral"], k),
            ("affinity", ["affinity"], k), ("kmeans_k", ["kmeans"], k),
            ("kmeans_2k", ["kmeans"], 2 * k), ("kmeans_4k", ["kmeans"], 4 * k)]
    meta = {}
    for seed, methods, kk in jobs:
        out = nl.ensure_dir(base / seed)
        try:
            paths = cluster_mod.run_cluster(g, methods, out, k=kk, seed=1)
        except Exception as exc:  # a clustering can legitimately fail (non-convergence)
            print(f"{design}/{seed}: FAIL {type(exc).__name__}: {exc}")
            meta[seed] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        record = nl.read_json(Path(paths[0]))
        members = dict(zip(record["node_ids"], record["assignment"]))
        nl.write_json(out / "members.json", members)
        meta[seed] = {"partition": str(paths[0]), "n_clusters": record["n_clusters"],
                      "method": record["method"], "k": kk}
        print(f"{design}/{seed}: ok clusters={record['n_clusters']}")
    meta["_urd_clusters"] = max(1, int(modules))
    nl.write_json(base / "meta.json", meta)
    return 0


def main(argv: list[str]) -> int:
    designs = argv or list(nl.DESIGN_ORDER)
    rc = 0
    for design in designs:
        rc |= run_design(design)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
