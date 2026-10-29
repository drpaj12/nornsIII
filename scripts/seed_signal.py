"""Seed-signal mining (docs/plan/seed-signal.md). Offline, no VPR.

  python scripts/seed_signal.py BUILD_DIR [BUILD_DIR ...] --out-json data/analysis/seed-signal.json --out-prefix data/analysis/seed-features-pilot

BUILD_DIR = `<r9-out>/<design>/<own|foreign>`; any list of them works (the pilot, or the full round 9 set). Features come from
seed_features.py (Mimir metrics on cluster and LUT regions), labels from the stock packing (`sh<s>/run-<sha>/stock.s1/design.net`).
Mining: AUC (binary label) and Spearman (continuous label) per feature, pooled raw and stratified (percentile within build),
bootstrap over clusters (blocks), Benjamini-Hochberg over all features, Holm on the top list, best per family, artefact checks,
both at the cluster level and the LUT level. Run with the Loki venv python (numpy, scipy).
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

import seed_features as sf

BOOT_ALL = 1000
BOOT_TOP = 10000
BOOT_SEED = 20261029
TOP = 40
MIN_VALID = 0.7


# ---------------------------------------------------------------------------------------------- labels

def read_clbs(net: Path) -> tuple:
    """(atom -> top-level block index, ordered list of logic clb indices)."""
    root = ET.parse(net).getroot()
    atom_cl: dict = {}
    logic = []
    for k, top in enumerate(root.findall("block")):
        if top.get("instance", "").startswith("clb["):
            logic.append(k)
        stack = [top]
        while stack:
            x = stack.pop()
            kids = x.findall("block")
            if kids:
                stack += kids
            elif x.get("name") != "open":
                atom_cl[x.get("name")] = k
    return atom_cl, logic


def stock_net(b: sf.Build, shuffle: int) -> tuple:
    """(path of the stock .net, True if it is byte-identical across the VPR seeds found)."""
    sha = b.rec["shuffles"][str(shuffle)]["sha256"][:10]
    runs = sorted((b.dir / f"sh{shuffle}" / f"run-{sha}").glob("stock.s*/design.net"))
    if not runs:
        raise FileNotFoundError(f"no stock net under {b.dir}/sh{shuffle}/run-{sha}")
    same = len({p.read_bytes() for p in runs}) == 1
    return runs[0], same, len(runs)


def read_census_seeds(path: Path) -> list:
    """Root atoms of the seed picks, in order (census `M` records whose third field is `seed`); empty if no file."""
    out = []
    if path.is_file():
        for ln in path.read_text().splitlines():
            t = ln.split("\t")
            if t and t[0] == "M" and len(t) > 11 and t[3] == "seed":
                out.append(t[11])
    return out


def labels(b: sf.Build, shuffle: int) -> dict:
    """Per-cluster and per-atom labels of one shuffle against the stock packing."""
    net, same, nruns = stock_net(b, shuffle)
    atom_cl, logic = read_clbs(net)
    order = {k: i for i, k in enumerate(logic)}
    per: dict = collections.defaultdict(collections.Counter)
    size_c = collections.Counter()
    for a, lab in b.aff.items():
        size_c[lab] += 1
        k = atom_cl.get(a)
        if k in order:
            per[k][lab] += 1
    where = collections.defaultdict(dict)
    for k, cnt in per.items():
        for lab, n in cnt.items():
            where[lab][k] = n
    cl_lab = {}
    for c in range(b.K):
        spread = where.get(c, {})
        if not spread:
            continue
        k_main = max(spread, key=lambda k: spread[k])
        purity = spread[k_main] / size_c[c]
        exact = int(len(spread) == 1 and spread[k_main] == size_c[c] == sum(per[k_main].values()))
        cl_lab[c] = {"exact": exact, "purity": purity, "stock_rank": order[k_main] / max(1, len(logic) - 1),
                     "stock_main": k_main, "n_stock_clusters": len(spread)}
    # atom (LUT) labels: share of C-cluster mates kept with it
    members: dict = collections.defaultdict(list)
    for a, lab in b.aff.items():
        members[lab].append(a)
    seeds = read_census_seeds(b.shdir / "census.tsv")
    seed_clb = {}
    for a in seeds:
        k = atom_cl.get(a)
        if k in order and k not in seed_clb:
            seed_clb[k] = a
    lut_lab = {}
    for n in b.lut_nodes():
        a = b.parsed.stm[b.node_stm[n]][3]
        c = b.aff.get(a)
        k = atom_cl.get(a)
        if c is None or k not in order:
            continue
        mates = [m for m in members[c] if m != a and m not in b.vatoms[b.node_vertex[n]]]
        kept = sum(1 for m in mates if atom_cl.get(m) == k)
        lab = {"mates_kept": kept / len(mates) if mates else float("nan")}
        if seeds:
            is_seed = int(seed_clb.get(k) == a)
            lab["is_seed"] = is_seed
            lab["seed_cluster_equals_c"] = (cl_lab.get(c, {}).get("exact") if is_seed else float("nan"))
        lut_lab[a] = lab
    return {"net": str(net.name), "net_identical_across_seeds": same, "n_stock_runs": nruns, "clusters": cl_lab, "luts": lut_lab,
            "seed_source": "census" if seeds else "none (pilot stock runs have no census)", "rank_source": ".net order"}


# ---------------------------------------------------------------------------------------------- tables

CLUSTER_ID = {"build", "cluster", "view", "K"}
FAMILY_WORDS = (
    ("rent", "rent"), ("reconv", "reconvergence"), ("crit", "timing proxy"), ("cone", "cone"),
    ("fanout", "fanout"), ("level", "level"), ("depth", "level"), ("seq_", "level"), ("back_edges", "level"),
    ("edge_len", "level"), ("fn_class", "function"), ("used_inputs", "function"), ("inputs", "function"),
    ("loyalty", "connectivity"), ("intdeg", "connectivity"), ("closeness", "connectivity"), ("tightness", "connectivity"),
    ("pin_pressure", "connectivity"), ("neighbours", "connectivity"), ("ext_nets", "connectivity"), ("internal_nets", "connectivity"),
    ("lcc", "connectivity"), ("chain", "size"),
)


def family(name: str) -> str:
    base = name.split(":", 1)[-1]
    reg = base.split(".", 1)[0]
    if reg[:2] in ("R2", "R3", "L2", "L3") and ("struct.n_" in base or base.endswith("struct.size") or base.endswith("struct.n_edges")):
        return "cone"
    for w, f in FAMILY_WORDS:
        if w in base:
            return f
    return "size"


def region(name: str) -> str:
    base = name.split(":", 1)[-1]
    return base.split(".", 1)[0] if "." in base else "own"


def build_matrices(builds: list, with_mimir: bool, luts: bool, shuffles=(1, 2, 3)) -> dict:
    """Wide tables: one row per (build, cluster, shuffle) and per (build, LUT, shuffle).

    Features are shuffle independent for clusters (same graph). LUT features are recomputed per shuffle (atom names differ), which
    also checks that the features do not depend on names or order."""
    crow, lrow = [], []
    info = {}
    for d in builds:
        base = {}
        for s in shuffles:
            b = sf.Build(Path(d), s)
            lab = labels(b, s)
            if s == shuffles[0]:
                cr = b.cluster_rows(with_mimir)
                wide = collections.defaultdict(dict)
                for r in cr:
                    v = r["view"]
                    for k, val in r.items():
                        if k in CLUSTER_ID or k == "dummies" and v == "a":
                            continue
                        wide[r["cluster"]][f"{v}:{k}"] = val
                base = wide
                info[b.name] = {"clusters": b.K, "seed_source": lab["seed_source"], "rank_source": lab["rank_source"],
                                "stock_net_identical_across_vpr_seeds": True, "stock_runs": lab["n_stock_runs"]}
            info[b.name]["stock_net_identical_across_vpr_seeds"] &= lab["net_identical_across_seeds"]
            for c, lb in lab["clusters"].items():
                row = {"build": b.name, "design": Path(d).parent.name, "cons": Path(d).name, "shuffle": s, "cluster": c}
                row.update(base[c])
                row.update({f"label:{k}": v for k, v in lb.items()})
                crow.append(row)
            if luts:
                for n in b.lut_nodes():
                    a = b.parsed.stm[b.node_stm[n]][3]
                    lb = lab["luts"].get(a)
                    if lb is None:
                        continue
                    r = b.lut_row(n, with_mimir)
                    row = {"build": b.name, "design": Path(d).parent.name, "cons": Path(d).name, "shuffle": s, "cluster": r["cluster"],
                           "vertex": r["vertex"]}
                    row.update({f"f:{k}": v for k, v in r.items() if k not in ("build", "cluster", "vertex", "atom")})
                    row.update({f"label:{k}": v for k, v in lb.items()})
                    lrow.append(row)
    return {"clusters": crow, "luts": lrow, "info": info}


# ---------------------------------------------------------------------------------------------- statistics

def feature_matrix(rows: list, prefix_ok, onehot: str = "") -> tuple:
    names = []
    for r in rows:
        for k, v in r.items():
            if prefix_ok(k) and k not in names and isinstance(v, (int, float)) and not isinstance(v, bool):
                names.append(k)
    cat = collections.defaultdict(set)
    if onehot:
        for r in rows:
            if onehot in r:
                cat[onehot].add(r[onehot])
    cols = []
    out_names = []
    for k in names:
        x = np.array([r.get(k, np.nan) for r in rows], dtype=float)
        x[~np.isfinite(x)] = np.nan
        cols.append(x)
        out_names.append(k)
    for k, vals in cat.items():
        for v in sorted(vals):
            cols.append(np.array([1.0 if r.get(k) == v else 0.0 for r in rows]))
            out_names.append(f"{k}={v}")
    return np.column_stack(cols), out_names


def clean(X: np.ndarray, names: list) -> tuple:
    keep = []
    for j in range(X.shape[1]):
        col = X[:, j]
        ok = np.isfinite(col)
        if ok.mean() < MIN_VALID:
            continue
        med = np.nanmedian(col)
        col = np.where(ok, col, med)
        if np.ptp(col) == 0:
            continue
        X[:, j] = col
        keep.append(j)
    return X[:, keep], [names[j] for j in keep]


def stratify(X: np.ndarray, strata: np.ndarray) -> np.ndarray:
    out = np.empty_like(X)
    for s in np.unique(strata):
        m = strata == s
        out[m] = (rankdata(X[m], axis=0) - 0.5) / m.sum()
    return out


def stats_of(X: np.ndarray, ybin, ycont) -> tuple:
    """(AUC per feature for ybin, Spearman per feature for ycont)."""
    n1 = ybin.sum()
    n0 = len(ybin) - n1
    auc = np.full(X.shape[1], np.nan)
    if n1 > 0 and n0 > 0:
        r = rankdata(X, axis=0)
        auc = (r[ybin == 1].sum(axis=0) - n1 * (n1 + 1) / 2) / (n1 * n0)
    rho = np.full(X.shape[1], np.nan)
    if np.ptp(ycont) > 0:
        rx = rankdata(X, axis=0)
        ry = rankdata(ycont)
        rx = rx - rx.mean(axis=0)
        ry = ry - ry.mean()
        den = np.sqrt((rx ** 2).sum(axis=0) * (ry ** 2).sum())
        rho = (rx * ry[:, None]).sum(axis=0) / np.where(den == 0, np.nan, den)
    return auc, rho


def block_boot(X, ybin, ycont, groups, strata_of_group, n_boot, rng, cols=None) -> tuple:
    """Bootstrap over groups (a cluster with all its shuffle rows), stratified by build. Returns arrays (n_boot, F)."""
    if cols is not None:
        X = X[:, cols]
    idx_of = collections.defaultdict(list)
    for i, g in enumerate(groups):
        idx_of[g].append(i)
    by_s = collections.defaultdict(list)
    for g in idx_of:
        by_s[strata_of_group[g]].append(g)
    A = np.full((n_boot, X.shape[1]), np.nan)
    R = np.full((n_boot, X.shape[1]), np.nan)
    for b in range(n_boot):
        pick = []
        for s, gs in by_s.items():
            for g in rng.choice(len(gs), size=len(gs)):
                pick.extend(idx_of[gs[g]])
        pick = np.array(pick)
        a, r = stats_of(X[pick], ybin[pick], ycont[pick])
        A[b], R[b] = a, r
    return A, R


def design_boot(X, ybin, ycont, designs, n_boot, rng) -> tuple:
    ud = sorted(set(designs))
    ix = {d: np.where(designs == d)[0] for d in ud}
    A = np.full((n_boot, X.shape[1]), np.nan)
    R = np.full((n_boot, X.shape[1]), np.nan)
    for b in range(n_boot):
        pick = np.concatenate([ix[ud[i]] for i in rng.choice(len(ud), size=len(ud))])
        a, r = stats_of(X[pick], ybin[pick], ycont[pick])
        A[b], R[b] = a, r
    return A, R


def p_from_boot(B: np.ndarray, null: float) -> np.ndarray:
    ok = ~np.isnan(B)
    n = ok.sum(axis=0)
    le = ((B <= null) & ok).sum(axis=0)
    ge = ((B >= null) & ok).sum(axis=0)
    p = 2 * np.minimum(le, ge) / np.maximum(n, 1)
    return np.maximum(p, 1.0 / np.maximum(n, 1)).clip(max=1.0)


def bh(p: np.ndarray) -> np.ndarray:
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    run = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        run = min(run, p[i] * m / (rank + 1))
        q[i] = run
    return q


def holm(p: np.ndarray) -> np.ndarray:
    m = len(p)
    order = np.argsort(p)
    out = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * p[i]))
        out[i] = run
    return out


def mine(rows: list, feat_ok, ybin_key: str, ycont_key: str, onehot: str, dummy_key: str, seed_off: int, designs_key: str = "design") -> dict:
    """Mine one table. Rows carry `build`, `cluster`, labels. Returns the ranking dict."""
    if not rows:
        return {"n_rows": 0}
    X, names = feature_matrix(rows, feat_ok, onehot)
    X, names = clean(X, names)
    ybin = np.array([r[ybin_key] for r in rows], dtype=float)
    ycont = np.array([r[ycont_key] for r in rows], dtype=float)
    ok = np.isfinite(ybin) & np.isfinite(ycont)
    rows = [r for r, o in zip(rows, ok) if o]
    X, ybin, ycont = X[ok], ybin[ok], ycont[ok]
    builds = np.array([r["build"] for r in rows])
    designs = np.array([r[designs_key] for r in rows])
    groups = [(r["build"], r["cluster"]) if "vertex" not in r else (r["build"], r["cluster"]) for r in rows]
    strata_of_group = {g: g[0] for g in groups}
    Xs = stratify(X, builds)
    rng = np.random.default_rng(BOOT_SEED + seed_off)
    auc, rho = stats_of(X, ybin, ycont)
    aucs, rhos = stats_of(Xs, ybin, ycont)
    A, R = block_boot(Xs, ybin, ycont, groups, strata_of_group, BOOT_ALL, rng)
    p_auc, p_rho = p_from_boot(A, 0.5), p_from_boot(R, 0.0)
    q_auc, q_rho = bh(np.nan_to_num(p_auc, nan=1.0)), bh(np.nan_to_num(p_rho, nan=1.0))
    effect = np.nan_to_num(np.abs(aucs - 0.5), nan=0) + np.nan_to_num(np.abs(rhos), nan=0) / 2
    top = np.argsort(-effect)[:TOP]
    At, Rt = block_boot(Xs, ybin, ycont, groups, strata_of_group, BOOT_TOP, rng, cols=top)
    Ad, Rd = design_boot(Xs[:, top], ybin, ycont, designs, BOOT_TOP, rng)
    p_top = np.maximum(p_from_boot(At, 0.5), p_from_boot(Rt, 0.0))
    holm_top = holm(p_top)
    own = np.array([r["cons"] == "own" for r in rows])
    dummies_col = None
    if dummy_key:
        dummies_col = np.array([r.get(dummy_key, np.nan) for r in rows], dtype=float)

    def side(mask):
        if mask.sum() < 4 or ybin[mask].min() == ybin[mask].max():
            return np.full(X.shape[1], np.nan), np.full(X.shape[1], np.nan)
        return stats_of(Xs[mask], ybin[mask], ycont[mask])

    a_own, r_own = side(own)
    a_for, r_for = side(~own)
    per_design = {}
    for d in sorted(set(designs)):
        m = designs == d
        per_design[d] = side(m)
    art = np.full(X.shape[1], np.nan)
    if dummies_col is not None and np.isfinite(dummies_col).any() and np.ptp(dummies_col[np.isfinite(dummies_col)]) > 0:
        dc = np.nan_to_num(dummies_col, nan=float(np.nanmedian(dummies_col)))
        rx = rankdata(X, axis=0) - (len(X) + 1) / 2
        ry = rankdata(dc) - (len(X) + 1) / 2
        art = (rx * ry[:, None]).sum(axis=0) / np.sqrt((rx ** 2).sum(axis=0) * (ry ** 2).sum())

    def lohi(B, j):
        v = B[:, j]
        v = v[~np.isnan(v)]
        return (float(np.percentile(v, 5)), float(np.percentile(v, 95))) if len(v) else (float("nan"), float("nan"))

    table = []
    pos = {int(j): t for t, j in enumerate(top)}
    for j, nme in enumerate(names):
        e = {"feature": nme, "family": family(nme), "region": region(nme), "auc_raw": float(auc[j]), "rho_raw": float(rho[j]),
             "auc": float(aucs[j]), "rho": float(rhos[j]), "p_auc": float(p_auc[j]), "p_rho": float(p_rho[j]),
             "q_auc": float(q_auc[j]), "q_rho": float(q_rho[j]), "auc_own": float(a_own[j]), "auc_foreign": float(a_for[j]),
             "rho_own": float(r_own[j]), "rho_foreign": float(r_for[j]), "rho_with_dummies": float(art[j]),
             "artefact_dummies": bool(np.isfinite(art[j]) and abs(art[j]) >= 0.7)}
        e["per_design_auc"] = {d: float(v[0][j]) for d, v in per_design.items()}
        e["per_design_rho"] = {d: float(v[1][j]) for d, v in per_design.items()}
        if j in pos:
            t = pos[j]
            e["auc_ci90_cluster"] = lohi(At, t)
            e["rho_ci90_cluster"] = lohi(Rt, t)
            e["auc_ci90_design"] = lohi(Ad, t)
            e["rho_ci90_design"] = lohi(Rd, t)
            e["p_top"] = float(p_top[t])
            e["holm_top"] = float(holm_top[t])
        e["same_sign_own_foreign"] = bool(np.isfinite(a_own[j]) and np.isfinite(a_for[j]) and (a_own[j] - 0.5) * (a_for[j] - 0.5) > 0)
        table.append(e)
    table.sort(key=lambda e: -(abs(e["auc"] - 0.5) + abs(e["rho"]) / 2) if np.isfinite(e["auc"]) else 0)
    best = {}
    for e in table:
        best.setdefault(e["family"], e)
    best_region = {}
    for e in table:
        best_region.setdefault(e["region"], e)
    return {"n_rows": len(rows), "n_features": len(names), "n_pos": int(ybin.sum()), "ranking": table[:TOP], "best_per_family": best,
            "best_per_region": best_region, "all": table, "boot_all": BOOT_ALL, "boot_top": BOOT_TOP}


def agreement(cl: dict, lu: dict) -> dict:
    """Do LUT-level and cluster-level signals agree? Compare the signed effect of the metrics both levels measure."""
    def key(name: str) -> str | None:
        base = name.split(":", 1)[-1]
        for a, b in (("R2d", "L2d"), ("R3d", "L3d")):
            if base.startswith(a):
                return "cone:" + base.replace(a, "d", 1)
            if base.startswith(b):
                return "cone:" + base.replace(b, "d", 1)
        return None

    cmap = {key(e["feature"]): e for e in cl.get("all", []) if key(e["feature"]) and e["feature"].startswith("r:")}
    lmap = {key(e["feature"]): e for e in lu.get("all", []) if key(e["feature"])}
    shared = sorted(set(cmap) & set(lmap))
    out = {"shared_metrics": len(shared)}
    if len(shared) >= 5:
        a = np.array([cmap[k]["rho"] for k in shared])
        b = np.array([lmap[k]["rho"] for k in shared])
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() >= 5:
            ra, rb = rankdata(a[ok]), rankdata(b[ok])
            out["spearman_of_effects"] = float(np.corrcoef(ra, rb)[0, 1])
            out["same_sign_share"] = float(np.mean(np.sign(a[ok]) == np.sign(b[ok])))
            out["n_compared"] = int(ok.sum())
    fam = {}
    for f, e in cl.get("best_per_family", {}).items():
        l = lu.get("best_per_family", {}).get(f)
        if l:
            fam[f] = {"cluster_best": e["feature"], "cluster_rho": e["rho"], "cluster_auc": e["auc"], "lut_best": l["feature"],
                      "lut_rho": l["rho"], "lut_auc": l["auc"]}
    out["best_per_family_both"] = fam
    return out


def run(builds: list, out_json: Path, out_prefix: Path | None, with_mimir: bool, luts: bool) -> dict:
    m = build_matrices(builds, with_mimir, luts)
    crows, lrows = m["clusters"], m["luts"]
    for r in crows:
        r["y_exact"] = r["label:exact"]
        r["y_purity"] = r["label:purity"]
    real_l = [r for r in lrows if not r["f:is_dummy"]]
    for r in real_l:
        r["y_whole"] = 1.0 if r["label:mates_kept"] == 1.0 else 0.0
        r["y_kept"] = r["label:mates_kept"]
    cl = mine(crows, lambda k: k.startswith(("r:", "a:")) and not k.startswith(("r:label", "a:label")), "y_exact", "y_purity", "",
              "r:dummies", 1)
    # the no-signal baseline of the plan: max pack-time criticality of the cluster
    base = next((e for e in cl.get("all", []) if e["feature"] == "r:crit_max"), None)
    lu = mine(real_l, lambda k: k.startswith("f:") and k not in ("f:is_dummy", "f:inputs_declared", "f:po_driver"), "y_whole", "y_kept",
              "f:fn_class", "f:fanin_dummy_share_d4", 2) if real_l else {"n_rows": 0}
    dummy_l = [r for r in lrows if r["f:is_dummy"]]
    dsum = {}
    if dummy_l and real_l:
        dsum = {"n_dummy_luts": len(dummy_l), "mates_kept_dummy": float(np.nanmean([r["label:mates_kept"] for r in dummy_l])),
                "mates_kept_real": float(np.nanmean([r["y_kept"] for r in real_l]))}
    res = {"designs": sorted({r["design"] for r in crows}), "builds": m["info"], "n_builds": len(m["info"]),
           "register_row": "MEASUREMENT (pointer, 3 pilot designs; real mining on the round 9 full set)",
           "baseline_max_crit_cluster": base, "cluster_level": cl, "lut_level": lu, "dummy_luts": dsum,
           "agreement": agreement(cl, lu) if lu.get("n_rows") else {}}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    slim = json.loads(json.dumps(res, default=lambda o: None if o is None else str(o)))
    for lvl in ("cluster_level", "lut_level"):
        if "all" in slim.get(lvl, {}):
            slim[lvl]["all"] = [{k: e[k] for k in ("feature", "family", "region", "auc", "rho", "q_auc", "q_rho", "artefact_dummies")}
                                for e in slim[lvl]["all"]]
    out_json.write_text(json.dumps(slim, indent=1, sort_keys=True, allow_nan=True))
    if out_prefix:
        sf.write_csv_gz(Path(str(out_prefix) + "-clusters.csv.gz"), crows)
        if lrows:
            sf.write_csv_gz(Path(str(out_prefix) + "-luts.csv.gz"), lrows)
    return res


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("builds", nargs="+")
    ap.add_argument("--out-json", default="data/analysis/seed-signal.json")
    ap.add_argument("--out-prefix", default="")
    ap.add_argument("--no-mimir", action="store_true")
    ap.add_argument("--no-luts", action="store_true")
    a = ap.parse_args(argv)
    run(a.builds, Path(a.out_json), Path(a.out_prefix) if a.out_prefix else None, not a.no_mimir, not a.no_luts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
