"""RQ-N11 (round 3): what does the annealed placement say about HDL provenance?

On the stock-packing, analytic-start runs (runs/<d>/r3/stock.analytic.s<k>, k = 1..3) at CLB level:
for logic CLB pairs, Manhattan distance by provenance relation (same word, same module, same HDL
statement, net-connected, same io-word, none), the stratified (by direct net count) distance
difference of related vs unrelated pairs, neighbour stability across seeds, and a "why are these
neighbours" table. Definitions: docs/plan/round3.md (RQ-N11).

Usage: python scripts/n11.py [design ...]   writes data/<d>/n11.json, data/analysis/n11.json and
data/analysis/n11-why/<d>.tsv
"""

from __future__ import annotations

import collections
import itertools
import sys
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

import nornlib as nl
import r3lib

MAX_NET_FANOUT = 32
MAX_PAIRS = 400_000
PERMS = 1000       # label permutations per design and seed; the first AMEND_PERMS give the amendment's p
AMEND_PERMS = 200  # protocol entry 2026-10-24 (d805789): 200 permutations per design and seed
NULL_PERMS = 200   # position permutations of the null (protocol: 200; the first version used 20)
EXCLUDE_SHARE = 0.95
STRATA = (0, 1, 2, 4)  # lower bounds of the n_ij strata 0, 1, 2-3, >=4
RELATIONS = ("word", "module", "stmt", "net", "io")
N_SEEDS = (1, 2, 3)


def plurality(items: list[str]) -> str | None:
    if not items:
        return None
    return collections.Counter(items).most_common(1)[0][0]


def load_run(design: str, rundir: Path, blocks, members, iowords) -> dict:
    flat = nl.Flat(rundir / "final.flat_place")
    place = nl.Place(rundir / "final.place")
    num_xy = {r["num"]: (int(r["x"]), int(r["y"])) for r in place.rows}
    clb_atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        clb_atoms[row[4]].append(atom)
    types = flat.clb_types()
    logic = sorted((c for c in clb_atoms if r3lib.bs.classify(types[c]) == "logic" and c in num_xy),
                   key=lambda c: int(c.lstrip("#")))
    idx = {c: i for i, c in enumerate(logic)}
    word, module, stmt, io = [], [], [], []
    for c in logic:
        atoms = clb_atoms[c]
        words = [members[a]["word"] for a in atoms if a in members and members[a]["word"]]
        top = plurality(words)
        word.append(top if top and len(words) / len(atoms) >= r3lib.WORD_SHARE - 1e-9 else None)
        module.append(plurality([nl.module_of(a) for a in atoms if nl.module_of(a)]))
        stmt.append(plurality(["%s:%d" % (Path(p[2]).name, p[3]) for p in
                               (nl.provenance_parts(a) for a in atoms) if p[2]]))
        ios = [iowords[a] for a in atoms if a in iowords]
        io.append(plurality(ios))
    xy = np.array([num_xy[c] for c in logic], dtype=float)
    # nets at CLB level
    net_clbs: dict[str, set[int]] = collections.defaultdict(set)
    carry: set[tuple[int, int]] = set()
    cout_net: dict[str, int] = {}
    for b in blocks:
        clb = flat.clb_of(str(b["name"]))
        ci = idx.get(clb) if clb else None
        if ci is None:
            continue
        for net in b["inputs"]:
            net_clbs[net].add(ci)
        if b["kind"] != "hard":
            net_clbs[str(b["name"])].add(ci)
        elif b.get("model") == "adder":
            pins = {k.split("[")[0]: v for k, v in b.get("pins", {}).items()}
            for k, v in pins.items():
                net_clbs[v].add(ci)
            if "cout" in pins:
                cout_net[pins["cout"]] = ci
    for b in blocks:
        if b.get("model") == "adder":
            clb = flat.clb_of(str(b["name"]))
            ci = idx.get(clb) if clb else None
            pins = {k.split("[")[0]: v for k, v in b.get("pins", {}).items()}
            if ci is not None and pins.get("cin") in cout_net and cout_net[pins["cin"]] != ci:
                carry.add((min(ci, cout_net[pins["cin"]]), max(ci, cout_net[pins["cin"]])))
    big: dict[str, set[int]] = {}
    for net, s in net_clbs.items():
        if len(s) > MAX_NET_FANOUT + 1:
            big[net] = s
    inc_r, inc_c, n = [], [], 0
    nets_small = []
    for net, s in net_clbs.items():
        if 2 <= len(s) <= MAX_NET_FANOUT + 1:
            for k in s:
                inc_r.append(n)
                inc_c.append(k)
            nets_small.append(net)
            n += 1
    inc = sparse.csr_matrix((np.ones(len(inc_r)), (inc_r, inc_c)), shape=(n, len(logic)))
    adj = (inc.T @ inc).tocsr()
    adj.setdiag(0)
    adj.eliminate_zeros()
    return {"logic": logic, "xy": xy, "word": word, "module": module, "stmt": stmt, "io": io,
            "adj": adj, "big": big, "carry": carry}


def codes(labels: list[str | None]) -> np.ndarray:
    ids: dict[str, int] = {}
    out = np.full(len(labels), -1, dtype=np.int64)
    for i, lab in enumerate(labels):
        if lab is not None:
            out[i] = ids.setdefault(lab, len(ids))
    return out


def sample_pairs(c: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    total = c * (c - 1) // 2
    if total <= MAX_PAIRS:
        i, j = np.triu_indices(c, 1)
        return i, j
    i = rng.integers(0, c, MAX_PAIRS)
    j = rng.integers(0, c, MAX_PAIRS)
    keep = i != j
    return i[keep], j[keep]


def stratum(nij: np.ndarray) -> np.ndarray:
    return np.digitize(nij, STRATA[1:]).astype(np.int64)  # 0, 1, 2 (2-3), 3 (>=4)


def strat_diff(dist: np.ndarray, rel: np.ndarray, strat: np.ndarray) -> float:
    """Relative stratified mean-distance difference of related vs unrelated pairs."""
    num = den = wsum = 0.0
    for s in range(4):
        m = strat == s
        r = m & rel
        u = m & ~rel
        if r.sum() < 5 or u.sum() < 30:
            continue
        w = float(r.sum())
        num += w * (dist[r].mean() - dist[u].mean())
        den += w * dist[u].mean()
        wsum += w
    return num / den if wsum and den else float("nan")


def analyse_run(run: dict, seed: int) -> tuple[dict, tuple]:
    rng = np.random.default_rng(20261024 + seed)
    xy = run["xy"]
    c = len(xy)
    i, j = sample_pairs(c, rng)
    dist = np.abs(xy[i] - xy[j]).sum(axis=1)
    nij = np.asarray(run["adj"][i, j]).ravel()
    strat = stratum(nij)
    rel = {}
    for name in ("word", "module", "stmt", "io"):
        code = codes(run[name])
        rel[name] = (code[i] >= 0) & (code[i] == code[j])
    rel["net"] = nij > 0
    res: dict[str, object] = {"clbs": c, "pairs": int(len(i)), "mean_dist": float(dist.mean())}
    for name, mask in rel.items():
        res[name] = {"n_pairs": int(mask.sum()),
                     "mean_dist": float(dist[mask].mean()) if mask.any() else None}
    strata_idx = [np.flatnonzero(strat == s) for s in range(4)]
    for name in ("word", "module"):
        base = rel[name]
        # Original rule (docs/plan/round3.md, 4fb8b60): no exclusion; d is undefined (NaN) only when
        # no stratum has >= 5 related and >= 30 unrelated pairs. The share is kept for the amendment.
        res[f"share_{name}"] = float(base.mean())
        obs = strat_diff(dist, base, strat)
        res[f"d_{name}"] = obs
        # permutation of the relation labels within strata (PERMS draws; pooled over designs in r3stats)
        perm_d = []
        for _ in range(PERMS):
            perm = base.copy()
            for m in strata_idx:
                perm[m] = rng.permutation(base[m])
            perm_d.append(round(strat_diff(dist, perm, strat), 6))
        res[f"perm_d_{name}"] = perm_d
        first = [v for v in perm_d[:AMEND_PERMS]]
        res[f"p_{name}"] = (sum(1 for v in first if v <= obs) + 1) / (AMEND_PERMS + 1) if not np.isnan(obs) else float("nan")
    # null: positions permuted among logic CLBs, mean distance of all pairs
    nulls = []
    for _ in range(NULL_PERMS):
        p = rng.permutation(c)
        nulls.append(float(np.abs(xy[p][i] - xy[p][j]).sum(axis=1).mean()))
    res["null_mean_dist"] = float(np.mean(nulls))
    res["stmt_rel_unrelated"] = float(dist[~rel["stmt"]].mean())
    return res, (i, j, dist, nij, rel)


def neighbours(xy: np.ndarray, k: int = 4) -> list[set[int]]:
    tree = cKDTree(xy)
    _, idx = tree.query(xy, k=min(k + 1, len(xy)), p=1)
    return [set(int(x) for x in row[1:]) for row in idx]


def jaccard(a: list[set[int]], b: list[set[int]]) -> float:
    vals = [len(x & y) / len(x | y) for x, y in zip(a, b) if x | y]
    return float(np.mean(vals)) if vals else float("nan")


def why_table(design: str, run: dict, pairs: tuple) -> list[list[object]]:
    i, j, dist, nij, rel = pairs
    out = []
    for name in ("word", "module"):
        mask = rel[name]
        order = np.flatnonzero(mask)
        # closest related pairs, first with no direct net (the surprising ones), then with
        for want_net in (False, True):
            sel = [k for k in order if (nij[k] > 0) == want_net]
            sel.sort(key=lambda k: (dist[k], i[k], j[k]))
            for k in sel[:5]:
                a, b = int(i[k]), int(j[k])
                big_shared = [n for n, s in run["big"].items() if a in s and b in s]
                out.append([name, run["logic"][a], run["logic"][b], run[name][a], int(dist[k]),
                            int(nij[k]), len(big_shared),
                            int((min(a, b), max(a, b)) in run["carry"]), "not available"])
    return out


def run_design(design: str) -> dict | None:
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    runs_ = [nl.runs_dir(design, "r3", f"stock.analytic.s{k}") for k in N_SEEDS]
    runs_ = [r for r in runs_ if (r / "final.place").is_file()]
    if not runs_:
        return None
    parsed = nl.parse_blif(blif)
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    iop = nl.runs_dir(design, "words", "iowords.json")
    iowords = nl.read_json(iop) if iop.is_file() else {}
    per_seed, loaded, last = [], [], None
    for k, rd in enumerate(runs_, 1):
        run = load_run(design, rd, parsed["blocks"], members, iowords)
        res, pairs = analyse_run(run, k)
        per_seed.append(res)
        loaded.append(run)
        last = (run, pairs) if k == 1 else last
    out: dict[str, object] = {"design": design, "seeds": per_seed}
    for name in ("word", "module"):
        vals = [s[f"d_{name}"] for s in per_seed if not np.isnan(s[f"d_{name}"])]
        out[f"d_{name}"] = float(np.mean(vals)) if vals else float("nan")
        out[f"d_{name}_negative_seeds"] = int(sum(1 for s in per_seed if s[f"d_{name}"] < 0))
        # design-level share of related pairs (mean over the seeds) for the amendment's exclusion (>= 0.95)
        out[f"share_{name}"] = float(np.mean([s[f"share_{name}"] for s in per_seed]))
        out[f"excluded_amend_{name}"] = bool(out[f"share_{name}"] >= EXCLUDE_SHARE)
    # neighbour stability across seeds (placements share the CLB list when the packing is the same)
    stab, stab_null = [], []
    for a, b in itertools.combinations(range(len(loaded)), 2):
        if loaded[a]["logic"] == loaded[b]["logic"]:
            na, nb = neighbours(loaded[a]["xy"]), neighbours(loaded[b]["xy"])
            stab.append(jaccard(na, nb))
            rng = np.random.default_rng(7)
            stab_null.append(jaccard(na, neighbours(loaded[b]["xy"][rng.permutation(len(nb))])))
    out["stability"] = float(np.mean(stab)) if stab else None
    out["stability_null"] = float(np.mean(stab_null)) if stab_null else None
    nl.write_json(nl.DATA / design / "n11.json", out)
    run, pairs = last
    why = why_table(design, run, pairs)
    path = nl.DATA / "analysis" / "n11-why" / f"{design}.tsv"
    nl.ensure_dir(path.parent)
    head = "relation\tclb_a\tclb_b\tlabel\tmanhattan\tdirect_nets\thigh_fanout_shared\tcarry_chain\tcritical_path\n"
    path.write_text(head + "".join("\t".join(str(x) for x in row) + "\n" for row in why),
                    encoding="utf-8")
    print(f"{design}: d_word {out['d_word']:.3f} d_module {out['d_module']:.3f} "
          f"share_word {out['share_word']:.3f} share_module {out['share_module']:.3f} "
          f"stability {out['stability']}", flush=True)
    return out


def main(argv: list[str]) -> int:
    results = {}
    for design in argv or list(nl.DESIGN_ORDER):
        r = run_design(design)
        if r:
            results[design] = r
    if not argv:
        nl.write_json(nl.DATA / "analysis" / "n11.json", results)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
