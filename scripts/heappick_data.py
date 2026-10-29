"""Heap-picking lane: loaders for what heap_data does not carry (all read only): the full census, the packed .net, net fan-out, the HDL
names of atoms (name map) and the HDL graph (hdl_edge, hdl_port of norns-keep.db).

  load_extra(mimir_dir, sweep_root, census_root, designs) -> {design: dict(blif graph, fan-out, chains, names, hdl edges)}
"""
from __future__ import annotations

import collections
import lzma
import sqlite3
from pathlib import Path

import heap_data as hd
import heap_lib as hl
import heappick_lib as pl


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def effective_fanout(fo, alias):
    """Sink count of each root net after single-input identity LUTs (buffers) are absorbed: sum of the fan-outs of the net and of the
    buffer nets hanging off it, minus one buffer input pin per buffer."""
    out = collections.Counter()
    for n, c in fo.items():
        if n not in alias:
            out[n] += c
    for a in alias:
        r = hl._resolve(a, alias)
        out[r] += fo.get(a, 0) - 1
    return out


def name_map_names(path_xz):
    """{atom hash: (file:line, [HDL names of the region])} from the O and N records of an Odin III name map (provenance, not timing)."""
    reg_names = collections.defaultdict(set)
    o = {}
    with lzma.open(path_xz, "rt", errors="replace") as fh:
        for ln in fh:
            f = ln.rstrip("\n").split("\t")
            if f[0] == "N" and len(f) >= 5:
                reg_names[f[4]].add(f[3])
            elif f[0] == "O" and len(f) >= 9:
                o[f[3]] = (f"{Path(f[6]).name}:{f[7]}", f[8])
    return {h: (loc, sorted(reg_names.get(r, ()))) for h, (loc, r) in o.items()}


def load_hdl_graph(keep, run_id):
    """(edges, ports): edges [(src_node, dst_node, via_register)], nodes (module, word, bit) for named words, ('expr', span) for
    expression nodes (word ''); ports {(module, word)} of PI / PO bits."""
    def node(span, module, word, bit):
        return (module, word, bit) if word else ("expr", span)

    edges = []
    for ss, sm, sw, sb, ds, dm, dw, db, via in keep.execute(
            "select src_span,src_module,src_word,src_bit,dst_span,dst_module,dst_word,dst_bit,via_register from hdl_edge where run_id=?", (run_id,)):
        edges.append((node(ss, sm, sw, sb), node(ds, dm, dw, db), via))
    ports = collections.defaultdict(set)
    for module, word, bit, kind in keep.execute("select module,word,bit,kind from hdl_port where run_id=?", (run_id,)):
        ports[kind].add((module, word, bit))
    return edges, ports


def load_extra(mimir_dir, sweep_root, census_root, designs):
    mimir_dir, sweep_root, census_root = Path(mimir_dir), Path(sweep_root), Path(census_root)
    keep = ro(mimir_dir / "norns-keep.db")
    runs = {(d, s): (rid) for rid, d, s in keep.execute("select r.run_id,r.design,r.seed from run r join timing_run t using(run_id)")}
    maps = {rid: bs for rid, bs in keep.execute("select run_id,blob_sha256 from run_artifact where kind='map'")}
    lane3 = ro(mimir_dir / "lane3-structures.db")
    out = {}
    for d in designs:
        blif = (sweep_root / "netlists" / "base" / d / "netlist" / f"{d}.blif").read_text(errors="replace")
        cen0 = hl.parse_census(census_root / d / "s1" / "census.tsv")
        g = hl.parse_blif_graph(blif, set(cen0))
        fo = effective_fanout(pl.net_fanout(blif), g["alias"])
        drv_nets = collections.defaultdict(list)
        for n, a in g["net_atom"].items():
            drv_nets[a].append(n)
        rid = runs[(d, 1)]
        mp = maps.get(rid)
        names = name_map_names(mimir_dir / "blobs" / mp[:2] / (mp + ".xz")) if mp else {}
        edges, ports = load_hdl_graph(keep, rid)
        succ, pred = pl.build_adjacency(g, fo, hl._resolve)
        views = hd.load_structs(lane3, d)
        out[d] = {"succ": succ, "pred": pred, "blk_groups": [(info, atoms) for info, atoms in views["blk"]], "op_groups": [(info, atoms) for info, atoms in views["op"]],
                  "g": g, "fo": fo, "drv_nets": drv_nets, "chains": hl.adder_chains(g), "names": names, "hdl_edges": edges, "hdl_ports": ports,
                  "lv": hl.comb_levels(g), "run_id": rid}
    return out
