"""Round-7 first mining (EXPLORATORY, docs/plan/round7.md Stage 3). Reads runs/r7/<d>/pairs.npz (built by r7corpus.py)
and writes data/r7/mine.json. Every association is paired with the same statistic on HDL labels shuffled within the
design (one joint permutation of the atom to (word, bit, construct, instance) assignment per shuffle).

  python scripts/r7mine.py [--quick]      (--quick: fewer shuffles, for tests)
"""

from __future__ import annotations

import gzip
import sys

import numpy as np

import nornlib as nl
import r7lib as lib

POP = np.array([bin(i).count("1") for i in range(1 << 10)], dtype=np.uint8)
REL_BITS = {"same_word": 0, "same_bit": 1, "same_word_bit": 2, "same_stmt": 3, "same_inst_full": 4, "carry_nb": 5,
            "same_inst_d1": 6, "same_inst_d2": 7, "same_inst_d3": 8}
LEVELS = ("same_word", "same_bit", "same_word_bit", "same_stmt", "same_inst_d1", "same_inst_d2", "same_inst_d3", "same_inst_full")
BIT_FEATS = ("same_bit", "same_word_bit", "bit_close", "carry_nb")
HDL_FEATS = ("same_word", "same_bit", "same_word_bit", "same_stmt", "same_inst_d1", "same_inst_d2", "same_inst_d3",
             "same_inst_full", "bit_close", "carry_nb")
BASE_FEATS = ("log_nshared", "series", "scrit", "shared_only", "log_minfan", "pcrit_min", "pcrit_max", "kind_ll", "kind_lf",
              "kind_ff", "kind_adder")
TRAIN_CAP = 40_000
EVAL_CAP = 300_000
N_SHUF = 200
N_SHUF_MODEL = 20
BOOT = 10000
STRATA = ((0, 0), (1, 1), (2, 3), (4, 255))


class D:
    """One design's mining data."""

    def __init__(self, design: str):
        self.design = design
        out = lib.R7 / design
        z = np.load(out / "pairs.npz")
        self.a, self.b = z["a"], z["b"]
        self.cls, self.rel, self.src = z["cls"], z["rel"], z["src"]
        self.nshared, self.series, self.scrit, self.minfan = z["nshared"], z["series"], z["scrit"], z["minfan"]
        self.dist, self.co_best = z["dist"].astype(np.float32), z["co_best"]
        self.arms = [str(x) for x in z["arms"]]
        self.co = {arm: z[f"co_{arm}"] for arm in self.arms}
        self.best_stock = [int(x) for x in z["best_stock"]]
        self.best_h = str(z["best_h"][0])
        self.bit_delta = z["bit_delta"]
        ra = np.load(out / "runatoms.npz")
        runs = [str(x) for x in ra["runs"]]
        stock_idx = [i for i, r in enumerate(runs) if r.startswith("stock.")]
        self.pcrit = ra["pcrit"][stock_idx].mean(axis=0) if stock_idx else np.zeros(ra["pcrit"].shape[1])
        self.n = len(self.pcrit)
        words, bits, stmts, insts, kinds = [], [], [], [], []
        with gzip.open(out / "atoms.tsv.gz", "rt") as fh:
            next(fh)
            for line in fh:
                f = line.rstrip("\n").split("\t")
                kinds.append(f[2])
                stmts.append(f[3])
                insts.append(tuple(c for c in f[4].split("/") if c))
                words.append(f[5])
                bits.append(int(f[6]) if f[6] != "" else -1)
        self.labels = {"word": self._ids(words), "bit": np.array(bits, dtype=np.int32), "stmt": self._ids(stmts),
                       "inst1": self._ids([i[:1] if len(i) >= 1 else None for i in insts]),
                       "inst2": self._ids([i[:2] if len(i) >= 2 else None for i in insts]),
                       "inst3": self._ids([i[:3] if len(i) >= 3 else None for i in insts]),
                       "inst": self._ids([i if i else None for i in insts])}
        self.kind = np.array([{"lut": 0, "latch": 1, "adder": 2}[k] for k in kinds], dtype=np.uint8)
        self.E = np.flatnonzero((self.src & (4 | 8)) > 0)  # pairs unbiased by co-location (uniform or connected-uniform)
        self.dist5 = self.dist[:, [s - 1 for s in self.best_stock[:5]]].mean(axis=1) if self.best_stock else self.dist.mean(axis=1)
        self.dist10 = self.dist.mean(axis=1)

    @staticmethod
    def _ids(vals: list) -> np.ndarray:
        tab: dict = {}
        return np.array([-1 if v in (None, "", ()) else tab.setdefault(v, len(tab)) for v in vals], dtype=np.int32)

    def rel_from(self, perm: np.ndarray | None, idx: np.ndarray) -> dict[str, np.ndarray]:
        """HDL relation columns of the pairs `idx` under the labels (shuffled by `perm` if given). carry_nb is structural."""
        a, b = self.a[idx], self.b[idx]
        L = self.labels if perm is None else {k: v[perm] for k, v in self.labels.items()}
        sw = (L["word"][a] >= 0) & (L["word"][a] == L["word"][b])
        sb = (L["bit"][a] >= 0) & (L["bit"][a] == L["bit"][b])
        out = {"same_word": sw, "same_bit": sb, "same_word_bit": sw & sb,
               "same_stmt": (L["stmt"][a] >= 0) & (L["stmt"][a] == L["stmt"][b]),
               "same_inst_d1": (L["inst1"][a] >= 0) & (L["inst1"][a] == L["inst1"][b]),
               "same_inst_d2": (L["inst2"][a] >= 0) & (L["inst2"][a] == L["inst2"][b]),
               "same_inst_d3": (L["inst3"][a] >= 0) & (L["inst3"][a] == L["inst3"][b]),
               "same_inst_full": (L["inst"][a] >= 0) & (L["inst"][a] == L["inst"][b]),
               "carry_nb": ((self.rel[idx] >> REL_BITS["carry_nb"]) & 1).astype(bool)}
        both = sw & (L["bit"][a] >= 0) & (L["bit"][b] >= 0)
        out["bit_close"] = np.where(both, 1.0 / (1.0 + np.abs(L["bit"][a].astype(np.int32) - L["bit"][b])), 0.0)
        return out

    def base_matrix(self, idx: np.ndarray) -> np.ndarray:
        a, b = self.a[idx], self.b[idx]
        ns = self.nshared[idx].astype(np.float32)
        ser = self.series[idx].astype(np.float32)
        mf = self.minfan[idx].astype(np.float32)
        ka, kb = self.kind[a], self.kind[b]
        lo, hi = np.minimum(ka, kb), np.maximum(ka, kb)
        cols = [np.log1p(ns), ser, self.scrit[idx], ((ns > 0) & (ser == 0)).astype(np.float32),
                np.where(mf > 0, np.log1p(mf), 0.0), np.minimum(self.pcrit[a], self.pcrit[b]),
                np.maximum(self.pcrit[a], self.pcrit[b]), ((lo == 0) & (hi == 0)).astype(np.float32),
                ((lo == 0) & (hi == 1)).astype(np.float32), ((lo == 1) & (hi == 1)).astype(np.float32), (hi == 2).astype(np.float32)]
        return np.stack(cols, axis=1).astype(np.float32)


def boot_mean_ci(vals: list[float], seed: int = lib.RNG_SEED) -> tuple[float, float]:
    v = np.array([x for x in vals if x == x], dtype=float)
    if len(v) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    m = v[rng.integers(0, len(v), size=(BOOT, len(v)))].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


# ---------------------------------------------------------------------------------------
# (e) Table XI: d_r

def d_r(dist: np.ndarray, related: np.ndarray, nshared: np.ndarray) -> float:
    """Stratified mean distance difference (related minus unrelated within each n_ij stratum, weighted by the number of related
    pairs of the stratum) over the mean distance of the unrelated pairs (round 3, H11)."""
    num = den = 0.0
    for lo, hi in STRATA:
        m = (nshared >= lo) & (nshared <= hi)
        r = m & related
        u = m & ~related
        nr, nu = int(r.sum()), int(u.sum())
        if nr == 0 or nu == 0:
            continue
        num += nr * (float(dist[r].mean()) - float(dist[u].mean()))
        den += nr
    unrel = ~related
    base = float(dist[unrel].mean()) if unrel.any() else 0.0
    return (num / den) / base if den and base else float("nan")


def table_xi(ds: list[D], shuffles: int) -> dict:
    res: dict = {}
    obs = {lv: {} for lv in LEVELS}
    nul = {lv: {d.design: [] for d in ds} for lv in LEVELS}
    for d in ds:
        E = d.E
        dist = d.dist10[E]
        rels = d.rel_from(None, E)
        ns = d.nshared[E]
        for lv in LEVELS:
            r = rels[lv]
            obs[lv][d.design] = float("nan") if r.mean() >= 0.95 or not r.any() else d_r(dist, r, ns)
        for k in range(shuffles):
            perm = np.random.default_rng(lib.RNG_SEED + k).permutation(d.n)
            rs = d.rel_from(perm, E)
            for lv in LEVELS:
                r = rs[lv]
                nul[lv][d.design].append(float("nan") if r.mean() >= 0.95 or not r.any() else d_r(dist, r, ns))
    for lv in LEVELS:
        vals = [v for v in obs[lv].values() if v == v]
        med = float(np.median(vals)) if vals else float("nan")
        null_meds = []
        for k in range(shuffles):
            col = [nul[lv][d.design][k] for d in ds if obs[lv][d.design] == obs[lv][d.design]]
            col = [c for c in col if c == c]
            if col:
                null_meds.append(float(np.median(col)))
        res[lv] = {"per_design": obs[lv], "median": med, "n_designs": len(vals), "n_negative": int(sum(1 for v in vals if v < 0)),
                   "null_median_mean": float(np.mean(null_meds)) if null_meds else None,
                   "null_lo": float(np.percentile(null_meds, 2.5)) if null_meds else None,
                   "null_hi": float(np.percentile(null_meds, 97.5)) if null_meds else None,
                   "null_le_obs": float((np.sum(np.array(null_meds) <= med) + 1) / (len(null_meds) + 1)) if null_meds else None,
                   "holds_negative_median": bool(med < 0), "shuffles": len(null_meds)}
    return res


# ---------------------------------------------------------------------------------------
# (b) disagreement, (c) stability

def disagreement(ds: list[D], shuffles: int) -> dict:
    """D+ = pairs co-CLB in the best hindsight run and not in the stock run of the same seed; D- the reverse; agree = both."""
    cnt = {"dplus": 0, "dminus": 0, "agree": 0}
    null_rows: list[dict[str, dict[str, int]]] = [{k: {lv: 0 for lv in LEVELS} for k in cnt} for _ in range(shuffles)]
    obs = {k: {lv: 0 for lv in LEVELS} for k in cnt}
    for d in ds:
        if not d.best_h:
            continue
        arm, seed = d.best_h.rsplit(".s", 1)
        bit = int(seed) - 1
        h = (d.co[arm] >> bit) & 1
        s = (d.co["stock"] >> bit) & 1
        groups = {"dplus": np.flatnonzero((h == 1) & (s == 0)), "dminus": np.flatnonzero((h == 0) & (s == 1)),
                  "agree": np.flatnonzero((h == 1) & (s == 1))}
        for k, idx in groups.items():
            cnt[k] += len(idx)
            rels = d.rel_from(None, idx)
            for lv in LEVELS:
                obs[k][lv] += int(rels[lv].sum())
        for j in range(shuffles):
            perm = np.random.default_rng(lib.RNG_SEED + j).permutation(d.n)
            for k, idx in groups.items():
                rs = d.rel_from(perm, idx)
                for lv in LEVELS:
                    null_rows[j][k][lv] += int(rs[lv].sum())
    out: dict = {"counts": cnt, "levels": {}}
    for lv in LEVELS:
        def share(c: dict, k: str) -> float:
            return c[k][lv] / cnt[k] if cnt[k] else float("nan")
        row: dict = {}
        for k in ("dplus", "dminus"):
            o = share(obs, k) / share(obs, "agree") if share(obs, "agree") else float("nan")
            nulls = [share(r, k) / share(r, "agree") for r in null_rows if share(r, "agree")]
            row[k] = {"share": share(obs, k), "agree_share": share(obs, "agree"), "enrichment": o,
                      "null_mean": float(np.mean(nulls)) if nulls else None,
                      "null_lo": float(np.percentile(nulls, 2.5)) if nulls else None,
                      "null_hi": float(np.percentile(nulls, 97.5)) if nulls else None}
        out["levels"][lv] = row
    return out


def stability(ds: list[D], shuffles: int) -> dict:
    """Pairs that share a CLB in >= 1 stock run: the share that do so in >= 8 of the 10 seeds ("knowns"), by relation and class."""
    hist = np.zeros(11, dtype=np.int64)
    inv_n = [0, 0]
    cls_stable = np.zeros((5, 2), dtype=np.int64)
    obs = {lv: np.zeros(4, dtype=np.int64) for lv in LEVELS}  # stable&rel, rel, stable&~rel, ~rel
    nul = [{lv: np.zeros(4, dtype=np.int64) for lv in LEVELS} for _ in range(shuffles)]
    for d in ds:
        cm = d.co["stock"] & 1023
        inv_n[0] += int(((cm == 0) | (cm == 1023))[cm >= 0].sum())
        inv_n[1] += len(cm)
        # near in a seed = Manhattan CLB distance <= 2 (co-located included); evaluated on the unbiased pairs
        k = np.zeros(len(cm), dtype=np.uint8)
        k[d.E] = (d.dist[d.E] <= 2).sum(axis=1)
        idx = np.flatnonzero(k >= 1)
        stable = k[idx] >= 8
        hist += np.bincount(k[idx], minlength=11)
        for c in range(5):
            m = d.cls[idx] == c
            cls_stable[c] += [int((stable & m).sum()), int(m.sum())]
        rels = d.rel_from(None, idx)
        for lv in LEVELS:
            r = rels[lv]
            obs[lv] += [int((stable & r).sum()), int(r.sum()), int((stable & ~r).sum()), int((~r).sum())]
        for j in range(shuffles):
            perm = np.random.default_rng(lib.RNG_SEED + j).permutation(d.n)
            rs = d.rel_from(perm, idx)
            for lv in LEVELS:
                r = rs[lv]
                nul[j][lv] += [int((stable & r).sum()), int(r.sum()), int((stable & ~r).sum()), int((~r).sum())]

    def diff(c: np.ndarray) -> float:
        return (c[0] / c[1] if c[1] else float("nan")) - (c[2] / c[3] if c[3] else float("nan"))

    levels = {}
    for lv in LEVELS:
        nd = [diff(r[lv]) for r in nul]
        nd = [x for x in nd if x == x]
        o = obs[lv]
        levels[lv] = {"stable_given_related": float(o[0] / o[1]) if o[1] else None, "stable_given_unrelated": float(o[2] / o[3]) if o[3] else None,
                      "diff": diff(o), "null_diff_mean": float(np.mean(nd)) if nd else None,
                      "null_lo": float(np.percentile(nd, 2.5)) if nd else None, "null_hi": float(np.percentile(nd, 97.5)) if nd else None,
                      "related_pairs": int(o[1])}
    return {"co_clb_pairs_seed_invariant_share": inv_n[0] / inv_n[1] if inv_n[1] else None,
            "definition": "near = Manhattan CLB distance <= 2 in a seed; pairs of the unbiased samples near in >= 1 seed; stable = near in >= 8 of 10",
            "hist_seeds_co_stock": hist.tolist(), "pairs": int(hist.sum()), "stable_ge8": int(hist[8:].sum()),
            "by_class_stable_share": {c: (float(cls_stable[i, 0] / cls_stable[i, 1]) if cls_stable[i, 1] else None)
                                      for i, c in enumerate(("SC", "SN", "SI", "OR", "FL"))},
            "by_class_pairs": {c: int(cls_stable[i, 1]) for i, c in enumerate(("SC", "SN", "SI", "OR", "FL"))}, "levels": levels}


# ---------------------------------------------------------------------------------------
# (a), (d) models, leave one design out

def model_loop(ds: list[D], shuffles: int) -> dict:
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.metrics import roc_auc_score, r2_score
    from sklearn.preprocessing import StandardScaler
    rng0 = np.random.default_rng(lib.RNG_SEED)
    cache: dict[str, dict] = {}

    def prep(d: D, perm: np.ndarray | None, sub: np.ndarray) -> dict:
        rel = d.rel_from(perm, sub)
        base = d.base_matrix(sub)
        hdl = np.stack([rel[f].astype(np.float32) for f in HDL_FEATS], axis=1)
        return {"base": base, "hdl": hdl}

    def subset(d: D, cap: int, seed: int) -> np.ndarray:
        E = d.E
        if len(E) > cap:
            E = np.sort(np.random.default_rng(seed).choice(E, cap, replace=False))
        return E

    designs = [d for d in ds if d.co_best.any() and d.co_best[d.E].any()]
    out: dict = {"designs": [d.design for d in designs]}
    bit_cols = [HDL_FEATS.index(f) for f in BIT_FEATS]

    def fit_eval(perm_seed: int | None, want_coef: bool) -> dict:
        data = {}
        for d in designs:
            perm = None if perm_seed is None else np.random.default_rng(lib.RNG_SEED + 1000 + perm_seed).permutation(d.n)
            tr = subset(d, TRAIN_CAP, 1)
            te = subset(d, EVAL_CAP, 2)
            data[d.design] = {"tr": tr, "te": te, "ptr": prep(d, perm, tr), "pte": prep(d, perm, te),
                              "y1tr": d.co_best[tr], "y1te": d.co_best[te], "y2tr": d.dist5[tr], "y2te": d.dist5[te]}
        res = {"auc": {}, "r2": {}, "coef": {}}
        for held in designs:
            train = [data[d.design] for d in designs if d is not held]
            te = data[held.design]
            Xs = {"base": lambda p: p["base"], "bit": lambda p: np.hstack([p["base"], p["hdl"][:, bit_cols]]),
                  "full": lambda p: np.hstack([p["base"], p["hdl"]])}
            if perm_seed is not None:
                Xs = {k: v for k, v in Xs.items() if k != "base"}
            for name, fx in Xs.items():
                Xtr = np.vstack([fx(t["ptr"]) for t in train])
                ytr = np.concatenate([t["y1tr"] for t in train])
                if ytr.min() == ytr.max() or te["y1te"].min() == te["y1te"].max():
                    continue
                sc = StandardScaler().fit(Xtr)
                lr = LogisticRegression(max_iter=300, C=1.0).fit(sc.transform(Xtr), ytr)
                p = lr.predict_proba(sc.transform(fx(te["pte"])))[:, 1]
                res["auc"].setdefault(name, {})[held.design] = float(roc_auc_score(te["y1te"], p))
                if want_coef and name == "full":
                    names = list(BASE_FEATS) + list(HDL_FEATS)
                    res["coef"][held.design] = {n: float(c) for n, c in zip(names, lr.coef_[0])}
                ytr2 = np.concatenate([t["y2tr"] for t in train])
                rg = Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr2)
                res["r2"].setdefault(name, {})[held.design] = float(r2_score(te["y2te"], rg.predict(sc.transform(fx(te["pte"])))))
        return res

    obs = fit_eval(None, True)
    out["observed"] = obs
    nulls = [fit_eval(k, False) for k in range(shuffles)]
    summ: dict = {}
    for tgt in ("auc", "r2"):
        for name in ("bit", "full"):
            dd = [obs[tgt][name][h] - obs[tgt]["base"][h] for h in obs[tgt][name] if h in obs[tgt]["base"]]
            nd = []
            for nres in nulls:
                v = [nres[tgt][name][h] - obs[tgt]["base"][h] for h in nres[tgt].get(name, {}) if h in obs[tgt]["base"]]
                if v:
                    nd.append(float(np.mean(v)))
            lo, hi = boot_mean_ci(dd)
            summ[f"{tgt}_{name}_minus_base"] = {"mean": float(np.mean(dd)) if dd else None, "ci_lo": lo, "ci_hi": hi,
                                                "n_designs": len(dd), "n_positive": int(sum(1 for x in dd if x > 0)),
                                                "null_mean": float(np.mean(nd)) if nd else None,
                                                "null_lo": float(np.percentile(nd, 2.5)) if nd else None,
                                                "null_hi": float(np.percentile(nd, 97.5)) if nd else None, "shuffles": len(nd)}
    coefs: dict = {}
    for f in HDL_FEATS:
        v = [c[f] for c in obs["coef"].values()]
        lo, hi = boot_mean_ci(v)
        coefs[f] = {"mean": float(np.mean(v)) if v else None, "ci_lo": lo, "ci_hi": hi}
    out["summary"] = summ
    out["coef_full"] = coefs
    out["auc_base_mean"] = float(np.mean(list(obs["auc"]["base"].values()))) if obs["auc"].get("base") else None
    del cache, rng0
    return out


def figure_data(ds: list[D]) -> dict:
    """Class shares of the co-CLB pairs (best stock run, best hindsight run) per design, and the distance distribution per relation."""
    shares = {}
    for d in ds:
        row = {}
        for label, arm, seed in (("stock", "stock", d.best_stock[0] if d.best_stock else 1),
                                 ("hindsight", *(d.best_h.rsplit(".s", 1) if d.best_h else ("stock", "1")))):
            m = ((d.co[arm] >> (int(seed) - 1)) & 1) == 1
            c = np.bincount(d.cls[m], minlength=5)
            row[label] = (c / c.sum()).tolist() if c.sum() else [None] * 5
        shares[d.design] = row
    bins = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 255]
    dist_rel = {}
    for lv in ("same_word", "same_bit", "same_stmt", "same_inst_d1", "same_inst_full"):
        yes = np.zeros(len(bins) - 1)
        no = np.zeros(len(bins) - 1)
        for d in ds:
            E = d.E
            r = d.rel_from(None, E)[lv]
            dd = d.dist10[E]
            yes += np.histogram(dd[r], bins=bins)[0]
            no += np.histogram(dd[~r], bins=bins)[0]
        dist_rel[lv] = {"related": (yes / max(yes.sum(), 1)).tolist(), "unrelated": (no / max(no.sum(), 1)).tolist()}
    return {"class_shares": shares, "dist_bins": bins, "dist_by_relation": dist_rel, "classes": ["SC", "SN", "SI", "OR", "FL"]}


def main(argv: list[str]) -> int:
    quick = "--quick" in argv
    designs = [a for a in argv if not a.startswith("--")] or [d for d in lib.MAIN if (lib.R7 / d / "pairs.npz").is_file()]
    ds = [D(d) for d in designs]
    ns, nm = (5, 3) if quick else (N_SHUF, N_SHUF_MODEL)
    res = {"designs": designs, "date": "2026-10-26", "exploratory": True, "shuffles": ns, "model_shuffles": nm,
           "table_xi": table_xi(ds, ns), "disagreement": disagreement(ds, ns), "stability": stability(ds, ns),
           "models": model_loop(ds, nm), "figures": figure_data(ds)}
    nl.write_json(lib.DATA7 / "mine.json", res)
    print("mine written", len(designs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
