"""Round-7 corpus builder (docs/plan/round7.md, Stage 1): per design, from runs/r7/<d>/<arm>.s<seed>/ build
  runs/r7/<d>/atoms.tsv.gz       the design atom table (name, kind, HDL chain)
  runs/r7/<d>/runatoms.npz       per run: CLB id, x, y, pack criticality, post-route criticality, worst slack per atom
  runs/r7/<d>/pairs.npz          the pair universe with N17 class, HDL relations, per-run co-CLB and distance
  runs/r7/<d>/nets.npz           per-net table
  runs/r7/<d>/atlas/<arm>.s<seed>.json.gz   one JSON per run for the Wyrd placement atlas
  data/r7/corpus/<d>.json        committed summary (sizes, coverage, counts; no absolute paths)

  python scripts/r7corpus.py [design ...]
"""

from __future__ import annotations

import gzip
import json
import random
import sys
from pathlib import Path

import numpy as np

import nornlib as nl
import r4census as rc
import r7lib as lib

CLASS_CODE = {"SC": 0, "SN": 1, "SI": 2, "OR": 3, "FL": 4}
CONN_SAMPLE = 1_000_000
UNIFORM_SAMPLE = 200_000
CONN_RANDOM = 500_000
HDL_BITS = ("same_word", "same_bit", "same_word_bit", "same_stmt", "same_inst_full", "carry_nb", "same_inst_d1",
            "same_inst_d2", "same_inst_d3")


def arms_of(design: str) -> list[str]:
    """stock first, then the hindsight arms that ran (h1, h2, ...)."""
    out = ["stock"]
    k = 1
    while (lib.R7 / design / f"h{k}.s1").is_dir():
        out.append(f"h{k}")
        k += 1
    return out


def read_pincrit(path: Path) -> dict[str, dict[str, float]]:
    crit: dict[str, dict[str, float]] = {}
    if not path.is_file():
        return crit
    with gzip.open(path, "rt") as fh:
        for line in fh:
            a, n, c = line.rstrip("\n").split("\t")
            crit.setdefault(a, {})[n] = float(c)
    return crit


def read_paths(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def build(design: str) -> dict:
    out = lib.R7 / design
    view = lib.NetView(design)
    atoms = sorted(view.kind)
    aid = {a: i for i, a in enumerate(atoms)}
    n = len(atoms)
    hdl = lib.hdl_table(design, atoms)
    # string ids for HDL fields
    def ids(vals: list) -> np.ndarray:
        tab: dict = {}
        return np.array([-1 if v in (None, "", ()) else tab.setdefault(v, len(tab)) for v in vals], dtype=np.int32)

    word = ids([hdl[a]["word"] for a in atoms])
    bit = np.array([-1 if hdl[a]["bit"] is None else int(hdl[a]["bit"]) for a in atoms], dtype=np.int32)
    stmt = ids([hdl[a]["construct"] for a in atoms])
    inst_d = [ids([tuple(hdl[a]["inst"][:d]) if len(hdl[a]["inst"]) >= d else None for a in atoms]) for d in (1, 2, 3)]
    inst_full = ids([tuple(hdl[a]["inst"]) if hdl[a]["inst"] else None for a in atoms])
    kind = np.array([{"lut": 0, "latch": 1, "adder": 2}[view.kind[a]] for a in atoms], dtype=np.uint8)
    with gzip.open(out / "atoms.tsv.gz", "wt") as fh:
        fh.write("idx\tname\tkind\tconstruct\tinst\tword\tbit\tbus\n")
        for i, a in enumerate(atoms):
            h = hdl[a]
            fh.write(f"{i}\t{lib.base_name(a)}\t{view.kind[a]}\t{h['construct']}\t{'/'.join(h['inst'])}\t{h['word'] or ''}\t"
                     f"{'' if h['bit'] is None else h['bit']}\t{h['bus'] or ''}\n")
    # carry neighbours: adders joined by a net (cout -> cin)
    carry = set()
    for a in atoms:
        if view.kind[a] == "adder":
            for net in view.outs.get(a, ()):
                for s in view.sinks.get(net, ()):
                    if view.kind.get(s) == "adder" and s != a:
                        carry.add((min(aid[a], aid[s]), max(aid[a], aid[s])))
    arms = arms_of(design)
    runs: list[tuple[str, int]] = []
    for arm in arms:
        for s in lib.SEEDS:
            m = lib.read_metrics(design, arm, s)
            if m and m.get("rc") == 0:
                runs.append((arm, s))
    # per run atom arrays
    pc1 = read_pincrit(lib.run_dir(design, "stock", 1) / "pincrit.tsv.gz")
    runinfo: dict[tuple[str, int], dict] = {}
    for arm, s in runs:
        rd = lib.run_dir(design, arm, s)
        flat = nl.Flat(rd / "final.flat_place")
        clb = np.full(n, -1, dtype=np.int32)
        x = np.zeros(n, dtype=np.int16)
        y = np.zeros(n, dtype=np.int16)
        for a, (ax, ay, _l, _s, c, _pb) in flat.atoms.items():
            i = aid.get(a)
            if i is not None:
                clb[i] = int(str(c).lstrip("#"))
                x[i], y[i] = int(ax), int(ay)
        paths = read_paths(rd / "paths.json.gz")
        pc, sl, _cpd = lib.path_crit(paths)
        pcrit = np.array([pc.get(a, 0.0) for a in atoms], dtype=np.float32)
        slack = np.array([sl.get(a, np.nan) for a in atoms], dtype=np.float32)
        pk = read_pincrit(rd / "pincrit.tsv.gz") if arm == "stock" else {}
        pack = np.array([max(pk[a].values()) if a in pk and pk[a] else np.nan for a in atoms], dtype=np.float32)
        runinfo[(arm, s)] = {"clb": clb, "x": x, "y": y, "pcrit": pcrit, "slack": slack, "pack": pack,
                             "cov": float(np.mean(pcrit > 0)) if n else 0.0, "paths": paths}
    np.savez_compressed(out / "runatoms.npz", runs=np.array([f"{a}.s{s}" for a, s in runs]),
                        clb=np.stack([runinfo[r]["clb"] for r in runs]), x=np.stack([runinfo[r]["x"] for r in runs]),
                        y=np.stack([runinfo[r]["y"] for r in runs]), pcrit=np.stack([runinfo[r]["pcrit"] for r in runs]),
                        slack=np.stack([runinfo[r]["slack"] for r in runs]), pack=np.stack([runinfo[r]["pack"] for r in runs]))

    def key(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        lo, hi = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
        return lo * n + hi

    rng = random.Random(f"{lib.RNG_SEED}:{design}:pairs")
    # (i) co-CLB pairs in any run
    co_keys = []
    for r in runs:
        clb = runinfo[r]["clb"]
        order = np.argsort(clb, kind="stable")
        sc = clb[order]
        cuts = np.flatnonzero(np.diff(sc)) + 1
        for g in np.split(order, cuts):
            if len(g) >= 2 and clb[g[0]] >= 0:
                iu, ju = np.triu_indices(len(g), 1)
                co_keys.append(key(g[iu], g[ju]))
    co = np.unique(np.concatenate(co_keys)) if co_keys else np.zeros(0, dtype=np.int64)
    # (ii) connected pairs: nets of fanout <= 32 (series and shared input)
    ck, cser, cfan, ccrit = [], [], [], []
    for net, ss in view.sinks.items():
        if len(ss) > lib.FANOUT_COST or net in view.clock:
            continue
        d = view.driver.get(net)
        t = [x for x in ([d] if d in aid else []) + [s for s in ss if s in aid]]
        t = list(dict.fromkeys(t))
        if len(t) < 2:
            continue
        ti = np.array([aid[x] for x in t], dtype=np.int64)
        iu, ju = np.triu_indices(len(t), 1)
        ck.append(key(ti[iu], ti[ju]))
        is_d = np.array([x == d for x in t])
        ser = (is_d[iu] | is_d[ju]).astype(np.uint8)
        cser.append(ser)
        cfan.append(np.full(len(iu), len(ss), dtype=np.uint16))
        cr = np.zeros(len(iu), dtype=np.float32)
        for q in np.flatnonzero(ser):
            sink = t[ju[q]] if is_d[iu[q]] else t[iu[q]]
            cr[q] = pc1.get(sink, {}).get(net, 0.0)
        ccrit.append(cr)
    if ck:
        allk = np.concatenate(ck)
        uk, inv, cnt = np.unique(allk, return_inverse=True, return_counts=True)
        ser = np.zeros(len(uk), dtype=np.uint8)
        np.maximum.at(ser, inv, np.concatenate(cser))
        fan = np.full(len(uk), 65535, dtype=np.uint16)
        np.minimum.at(fan, inv, np.concatenate(cfan))
        scr = np.zeros(len(uk), dtype=np.float32)
        np.maximum.at(scr, inv, np.concatenate(ccrit))
    else:
        uk = np.zeros(0, dtype=np.int64)
        cnt = np.zeros(0, dtype=np.int64)
        ser = np.zeros(0, dtype=np.uint8)
        fan = np.zeros(0, dtype=np.uint16)
        scr = np.zeros(0, dtype=np.float32)
    conn_only = np.setdiff1d(uk, co, assume_unique=True)
    if len(conn_only) > CONN_SAMPLE:
        sel = np.array(sorted(rng.sample(range(len(conn_only)), CONN_SAMPLE)))
        conn_only = conn_only[sel]
    # (iii) uniform random pairs
    uni = set()
    while len(uni) < min(UNIFORM_SAMPLE, n * (n - 1) // 2 // 2):
        a, b = rng.randrange(n), rng.randrange(n)
        if a != b:
            uni.add(min(a, b) * n + max(a, b))
    uni_arr = np.array(sorted(uni), dtype=np.int64)
    # (ii') a uniform random sample of ALL connected pairs, co-located or not (unbiased by co-location; used for evaluation)
    conn_rand = uk[np.array(sorted(rng.sample(range(len(uk)), min(len(uk), CONN_RANDOM))), dtype=np.int64)] if len(uk) else uk
    keys = np.union1d(np.union1d(co, conn_only), np.union1d(uni_arr, conn_rand))
    a_idx = (keys // n).astype(np.int32)
    b_idx = (keys % n).astype(np.int32)
    src = (np.isin(keys, co).astype(np.uint8) | (np.isin(keys, conn_only).astype(np.uint8) << 1)
           | (np.isin(keys, uni_arr).astype(np.uint8) << 2) | (np.isin(keys, conn_rand).astype(np.uint8) << 3))
    pos = np.searchsorted(uk, keys)
    pos = np.minimum(pos, max(len(uk) - 1, 0))
    hit = (uk[pos] == keys) if len(uk) else np.zeros(len(keys), dtype=bool)
    nshared = np.minimum(np.where(hit, cnt[pos] if len(uk) else 0, 0), 255).astype(np.uint8)  # clipped: a count above 255 would wrap in uint8
    series = np.where(hit, ser[pos] if len(uk) else 0, 0).astype(np.uint8)
    scrit = np.where(hit, scr[pos] if len(uk) else 0.0, 0.0).astype(np.float32)
    minfan = np.where(hit, fan[pos] if len(uk) else 0, 0).astype(np.uint16)
    # N17 class (the registered r4census.classify with the seed-1 stock pin criticalities)
    nlist = view.nlist
    cls = np.zeros(len(keys), dtype=np.uint8)
    for q in range(len(keys)):
        cls[q] = CLASS_CODE[rc.classify(nlist, pc1, atoms[a_idx[q]], atoms[b_idx[q]])]
    # HDL relations
    sw = (word[a_idx] >= 0) & (word[a_idx] == word[b_idx])
    sb = (bit[a_idx] >= 0) & (bit[a_idx] == bit[b_idx])
    rel = np.zeros(len(keys), dtype=np.uint16)
    rel |= sw.astype(np.uint16) << 0
    rel |= sb.astype(np.uint16) << 1
    rel |= (sw & sb).astype(np.uint16) << 2
    rel |= ((stmt[a_idx] >= 0) & (stmt[a_idx] == stmt[b_idx])).astype(np.uint16) << 3
    rel |= ((inst_full[a_idx] >= 0) & (inst_full[a_idx] == inst_full[b_idx])).astype(np.uint16) << 4
    cset = np.array(sorted(a * n + b for a, b in carry), dtype=np.int64)
    rel |= np.isin(keys, cset).astype(np.uint16) << 5
    for j, arr in enumerate(inst_d):
        rel |= ((arr[a_idx] >= 0) & (arr[a_idx] == arr[b_idx])).astype(np.uint16) << (6 + j)
    bit_delta = np.where(sw & (bit[a_idx] >= 0) & (bit[b_idx] >= 0), np.abs(bit[a_idx] - bit[b_idx]), -1).astype(np.int16)
    # per-run co-CLB and distance
    stock_runs = [(arm, s) for arm, s in runs if arm == "stock"]
    dist = np.full((len(keys), len(lib.SEEDS)), 255, dtype=np.uint8)
    co_mask = {arm: np.zeros(len(keys), dtype=np.uint16) for arm in arms}
    for arm, s in runs:
        ri = runinfo[(arm, s)]
        same = (ri["clb"][a_idx] == ri["clb"][b_idx]) & (ri["clb"][a_idx] >= 0)
        co_mask[arm] |= same.astype(np.uint16) << (s - 1)
        if arm == "stock":
            d = np.abs(ri["x"][a_idx].astype(np.int32) - ri["x"][b_idx]) + np.abs(ri["y"][a_idx].astype(np.int32) - ri["y"][b_idx])
            dist[:, s - 1] = np.minimum(d, 254).astype(np.uint8)
    # the best hindsight run: lowest objective among all h-arm runs; co flag in that run
    hruns = [(arm, s) for arm, s in runs if arm != "stock"]
    best_h = None
    if hruns:
        best_h = min(hruns, key=lambda r: (lib.read_metrics(design, r[0], r[1])["objective"], r[1]))
    co_best = np.zeros(len(keys), dtype=np.uint8)
    if best_h is not None:
        ri = runinfo[best_h]
        co_best = ((ri["clb"][a_idx] == ri["clb"][b_idx]) & (ri["clb"][a_idx] >= 0)).astype(np.uint8)
    # best 5 stock runs by objective (for the distance target)
    stock_sorted = sorted(stock_runs, key=lambda r: (lib.read_metrics(design, "stock", r[1])["objective"], r[1]))
    np.savez_compressed(out / "pairs.npz", a=a_idx, b=b_idx, cls=cls, rel=rel, bit_delta=bit_delta, src=src, nshared=nshared,
                        series=series, scrit=scrit, minfan=minfan, dist=dist, co_best=co_best,
                        arms=np.array(arms), best_h=np.array([f"{best_h[0]}.s{best_h[1]}" if best_h else ""]),
                        best_stock=np.array([s for _a, s in stock_sorted]), **{f"co_{arm}": co_mask[arm] for arm in arms})
    # nets
    net_rows = []
    for net, ss in sorted(view.sinks.items()):
        if net in view.clock:
            continue
        d = view.driver.get(net)
        net_rows.append((net, d, len(ss)))
    # duplication candidates, per stock run and per hindsight run
    dup = {}
    for arm, s in runs:
        ri = runinfo[(arm, s)]
        clb_of = {atoms[i]: int(ri["clb"][i]) for i in range(n) if ri["clb"][i] >= 0}
        cands = lib.dup_candidates(view, clb_of)
        sav = lib.dup_saving([{"arrival": p["arrival"], "nodes": p["nodes"]} for p in ri["paths"]], set(cands), clb_of)
        pcs = [ri["pcrit"][aid[a]] for a in cands]
        dup[f"{arm}.s{s}"] = {"candidates": len(cands), "luts": int(np.sum(kind == 0)),
                              **lib.dup_other_sinks(view, clb_of, set(cands)),
                              "near5": int(sum(1 for c in pcs if c >= lib.PCRIT_NEAR[0])),
                              "near10": int(sum(1 for c in pcs if c >= lib.PCRIT_NEAR[1])), **sav}
    nl.write_json(out / "dup.json", dup)
    # atlas
    write_atlas(design, view, atoms, hdl, runs, runinfo, keys, a_idx, b_idx, cls, n)
    summary = {"design": design, "atoms": n, "runs": len(runs), "arms": arms, "pairs": int(len(keys)),
               "pairs_cooccur": int(np.sum(src & 1 > 0)), "pairs_connected_sample": int(np.sum((src >> 1) & 1)),
               "pairs_uniform": int(np.sum((src >> 2) & 1)), "pairs_connected_random": int(np.sum((src >> 3) & 1)), "carry_pairs": len(carry),
               "coverage_pcrit_mean": float(np.mean([runinfo[r]["cov"] for r in runs])) if runs else 0.0,
               "relation_share": {name: float(np.mean((rel >> i) & 1)) for i, name in
                                  enumerate(("same_word", "same_bit", "same_word_bit", "same_stmt", "same_inst_full", "carry_nb",
                                             "same_inst_d1", "same_inst_d2", "same_inst_d3"))},
               "class_share_pairs": {c: float(np.mean(cls == v)) for c, v in CLASS_CODE.items()}}
    nl.write_json(lib.DATA7 / "corpus" / f"{design}.json", summary)
    print(design, {k: summary[k] for k in ("atoms", "runs", "pairs")}, flush=True)
    return summary


def write_atlas(design, view, atoms, hdl, runs, runinfo, keys, a_idx, b_idx, cls, n) -> None:
    """One JSON per run (format in docs/plan/round7.md). Atom class = the strongest N17 class among its co-CLB pairs."""
    for arm, s in runs:
        ri = runinfo[(arm, s)]
        m = lib.read_metrics(design, arm, s)
        same = (ri["clb"][a_idx] == ri["clb"][b_idx]) & (ri["clb"][a_idx] >= 0)
        best = np.full(n, 5, dtype=np.uint8)
        np.minimum.at(best, a_idx[same], cls[same])
        np.minimum.at(best, b_idx[same], cls[same])
        clbs: dict[int, dict] = {}
        for i in range(n):
            c = int(ri["clb"][i])
            if c < 0:
                continue
            e = clbs.setdefault(c, {"id": c, "type": "clb", "x": int(ri["x"][i]), "y": int(ri["y"][i]), "atoms": []})
            e["atoms"].append(i)
        names = ["SC", "SN", "SI", "OR", "FL", ""]
        doc = {"design": design, "arm": arm, "seed": s, "grid": m.get("grid"), "cpd_ns": m.get("cpd_ns"),
               "wirelength": m.get("wirelength"), "chan_width": m.get("chan_width"),
               "clbs": [clbs[c] for c in sorted(clbs)],
               "atoms": [{"name": lib.base_name(atoms[i]), "kind": view.kind[atoms[i]], "class": names[int(best[i])],
                          "construct": hdl[atoms[i]]["construct"], "inst": "/".join(hdl[atoms[i]]["inst"]),
                          "word": hdl[atoms[i]]["word"], "bit": hdl[atoms[i]]["bit"],
                          "crit": None if np.isnan(ri["pack"][i]) else round(float(ri["pack"][i]), 4),
                          "pcrit": round(float(ri["pcrit"][i]), 4)} for i in range(n)]}
        lib.gz_write(lib.R7 / design / "atlas" / f"{arm}.s{s}.json.gz", json.dumps(doc, separators=(",", ":")))


def main(argv: list[str]) -> int:
    designs = argv or [d for d in lib.CALIB + lib.MAIN if (lib.R7 / d / "rounds.json").is_file()]
    for d in designs:
        build(d)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
