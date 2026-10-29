"""Critical-heap lane: load the per-run dataset (read-only Mimir stores + the census files + the BLIFs) into plain dicts.

  load_all(mimir_dir, sweep_root, census_root) -> list of run dicts (45: 15 Verilog designs x 3 seeds)

Atom fields (logic atoms only; pads left out): pc (pack-time crit), cseq, crank, seq, rc (post-route crit, None = in no reported path),
kinds per view (op / blk / det), opd, muxd, size, lvl, typ, grp, word, bit, line.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3
from pathlib import Path

import heap_lib as hl

OPS = ("BINARY", "UNARY", "TERNARY", "CONCAT")
MUXES = ("IF", "CASE", "TERNARY")


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def chain_depths(chain):
    toks = [t.split("@")[0] for t in chain.split(">")] if chain else []
    return sum(t in OPS for t in toks), sum(t in MUXES for t in toks)


def load_structs(lane3, design):
    """{view: [(info, atoms)]} for design 'norns/<d>'; info = (kind, op_depth, mux_depth, n_members). Views: op, blk, det."""
    st = {}
    for sid, kind, chain, gran, rid in lane3.execute("select structure_id,kind,construct_chain,granularity,run_id from structure where design=?", ("norns/" + design,)):
        st[(sid, rid)] = (kind, chain, gran)
    mem = collections.defaultdict(set)
    for sid, rid, atom in lane3.execute("select structure_id,run_id,atom from structure_member where design=?", ("norns/" + design,)):
        mem[(sid, rid)].add(atom)
    views = {"op": [], "blk": [], "det": []}
    for key, (kind, chain, gran) in st.items():
        v = {"operator": "op", "block": "blk", "": "det"}.get(gran)
        atoms = mem.get(key, set())
        if v and atoms:
            od, md = chain_depths(chain)
            views[v].append(((kind, od, md, len(atoms)), atoms))
    return views


def parse_map_lines(path_xz):
    """atom hash -> 'file:line' from the O records of an Odin III name map (provenance, not timing)."""
    import lzma
    out = {}
    with lzma.open(path_xz, "rt", errors="replace") as fh:
        for ln in fh:
            f = ln.rstrip("\n").split("\t")
            if f[0] == "O" and len(f) >= 9:
                out[f[3]] = f"{Path(f[6]).name}:{f[7]}"
    return out


def load_all(mimir_dir, sweep_root, census_root, designs=None):
    mimir_dir, sweep_root, census_root = Path(mimir_dir), Path(sweep_root), Path(census_root)
    keep = ro(mimir_dir / "norns-keep.db")
    lane3 = ro(mimir_dir / "lane3-structures.db")
    runs = keep.execute("select r.run_id,r.design,r.seed from run r join timing_run t using(run_id) order by r.design,r.seed").fetchall()
    maps = {rid: bs for rid, bs in keep.execute("select run_id,blob_sha256 from run_artifact where kind='map'")}
    cache = {}
    out = []
    for rid, d, seed in runs:
        if designs and d not in designs:
            continue
        if d not in cache:
            blif = (sweep_root / "netlists" / "base" / d / "netlist" / f"{d}.blif").read_text(errors="replace")
            cen0 = hl.parse_census(census_root / d / "s1" / "census.tsv")
            g = hl.parse_blif_graph(blif, set(cen0))
            pads = set(g["pis"]) | {"out:" + n for n in g["pos"]}
            lv = hl.comb_levels(g)
            chains = hl.adder_chains(g)
            grp, gsize = hl.assign_cones(g, lv)
            views = load_structs(lane3, d)
            vmap = {v: hl.innermost_kind([(info, atoms) for info, atoms in items]) for v, items in views.items()}
            mp = maps.get(rid)
            lines = parse_map_lines(mimir_dir / "blobs" / mp[:2] / (mp + ".xz")) if mp else {}
            cache[d] = {"g": g, "pads": pads, "lv": lv, "chains": chains, "grp": grp, "gsize": gsize, "vmap": vmap, "lines": lines}
        c = cache[d]
        cen = hl.pack_rank(hl.parse_census(census_root / d / f"s{seed}" / "census.tsv", c["pads"]))
        tr = keep.execute("select cpd_ns,paths_in_report,last_crit,trunc_090,trunc_095,trunc_099,n_endpoints_090,n_endpoints_095,n_endpoints_099 from timing_run where run_id=?", (rid,)).fetchone()
        tr = dict(zip(("cpd", "n_paths", "last_crit", "trunc90", "trunc95", "trunc99", "ne90", "ne95", "ne99"), tr))
        hist = dict(keep.execute("select bin,n from timing_path_hist where run_id=?", (rid,)).fetchall())
        paths = {}
        for pi, cr, ar, ep in keep.execute("select path_index,crit,arrival_ns,endpoint from timing_path where run_id=?", (rid,)):
            paths[pi] = {"crit": cr, "arr": ar, "end": ep.split(".")[0] if ep else "", "atoms": [], "cell": 0.0, "net": 0.0}
        rc, w, wb = {}, {}, {}
        for pi, step, atom, cat, cell, net, mod, word, bit, span in keep.execute(
                "select path_index,step,atom,category,cell_delay_ns,net_delay_in_ns,module,word,bit,span from timing_path_node where run_id=? order by path_index,step", (rid,)):
            p = paths[pi]
            p["cell"] += cell or 0.0
            p["net"] += net or 0.0
            p["atoms"].append(atom)
            if cat != "matched" or atom not in cen:
                continue
            cr = p["crit"] or 0.0
            if cr > rc.get(atom, -1.0):
                rc[atom] = cr
                w[atom] = (cell or 0.0) + (net or 0.0)
            if word and bit is not None and bit >= 0:
                wb[atom] = (mod, word, bit)
        width = collections.defaultdict(int)
        for (mod, word, bit) in wb.values():
            width[(mod, word)] = max(width[(mod, word)], bit + 1)
        atoms = {}
        for a, v in cen.items():
            typ = "ff" if a in c["g"]["seq"] else ("adder" if a in c["g"]["comb"] and c["g"]["comb"][a][0] == "adder" else ("lut" if a in c["g"]["comb"] else "other"))
            row = dict(v)
            row["rc"] = rc.get(a)
            row["w"] = w.get(a, 0.0)
            row["typ"] = typ
            row["lvl"] = c["lv"].get(a, 0)
            row["grp"] = c["grp"].get(a)
            if a in c["chains"]:
                row["cpos"], row["clen"] = c["chains"][a]
            for view in ("op", "blk", "det"):
                info = c["vmap"][view].get(a)
                row[view] = info[0] if info else "none"
                row[view + "_info"] = info
            row["line"] = c["lines"].get(a)
            if a in wb:
                mod, word, bit = wb[a]
                row["word"], row["bit"], row["width"] = f"{mod}/{word}", bit, width[(mod, word)]
            atoms[a] = row
        out.append({"design": d, "seed": seed, "run_id": rid, "timing": tr, "hist": hist, "paths": paths, "atoms": atoms,
                    "gsize": c["gsize"], "pad_in_paths": 0})
    return out
