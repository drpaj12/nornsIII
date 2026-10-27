"""Round-7 first mining (EXPLORATORY, docs/plan/round7.md Stage 3). Reads runs/r7/<d>/pairs.npz (built by r7corpus.py)
and writes data/r7/mine.json. Every association is paired with the same statistic on HDL labels shuffled within the
design (one joint permutation of the atom to (word, bit, construct, instance) assignment per shuffle).

  python scripts/r7mine.py [--quick]      (--quick: fewer shuffles, for tests)
"""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

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
              "kind_ff", "kind_adder", "co_stock", "log_dist_stock")
TRAIN_CAP = 40_000
EVAL_CAP = 300_000
N_SHUF = 200
N_SHUF_MODEL = 200
BOOT = 10000
STRATA = ((0, 0), (1, 1), (2, 3), (4, 255))
NEAR_DIST = 2    # stability: near in a seed = Manhattan CLB distance <= this
STABLE_MIN = 8   # stable = near in at least this many seeds
R7F = nl.RUNS / "r7f"


def family(design: str) -> str:
    """Design family for the leave-out: designs of one family share code, so a model must not train on a sibling of the
    held-out design. stereovision0-3, diffeq1-2 and the mk* modules (mkPktMerge, mkSMAdapter4B, mkDelayWorker32B) are families;
    every other design, and every calibration construction, is its own family (the n5_ constructions of one topology and style
    but another size are one family). boundtop and raygentop are separate families: their Verilog shares no module name
    (5 and 5 modules) and only 2 non-trivial source lines (fix round 2, item 20)."""
    if design.startswith("stereovision"):
        return "stereovision"
    if design.startswith("diffeq"):
        return "diffeq"
    if design.startswith("mk"):
        return "mk"
    if design.startswith("n5_"):
        return design.rsplit("_", 1)[0]
    return design


def disjoint_dist(dist: np.ndarray, best_stock: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """(R2 target, baseline feature) of the stock arm: mean distance over the 5 best stock seeds, and over the other seeds. The two seed
    sets are disjoint (item 9); with no ordering both are the mean over all seeds, with no other seeds the baseline is 0."""
    if not best_stock:
        m = dist.mean(axis=1)
        return m, m
    top = [s - 1 for s in best_stock[:5]]
    other = [s - 1 for s in best_stock[5:]]
    assert not set(top) & set(other)
    return dist[:, top].mean(axis=1), (dist[:, other].mean(axis=1) if other else np.zeros(len(dist), dtype=np.float32))


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
        words, bits, stmts, insts, kinds, names = [], [], [], [], [], []
        with gzip.open(out / "atoms.tsv.gz", "rt") as fh:
            next(fh)
            for line in fh:
                f = line.rstrip("\n").split("\t")
                names.append(f[1])
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
        self.dist5, self.dist_other = disjoint_dist(self.dist, self.best_stock)
        self.dist10 = self.dist.mean(axis=1)   # Table XI and the figures only; NOT used as a model feature (see below)
        # Item 9 (fix round 2): the baseline distance feature and the R2 target use DISJOINT seed sets. Target 'aff' (stock arm):
        # baseline = mean over the stock seeds that are NOT among the best 5 (dist5, the R2 target). Target 'net' (the .net arms,
        # same flow as the target): baseline = net0 seeds 1-5, R2 target = net0 seeds 6-10 (the held-out seeds).
        self._net0: dict[str, np.ndarray | None] = {}
        # the stock clustering is seed-invariant; its co-CLB flag and mean distance are baseline features (B5)
        sb = (self.best_stock[0] if self.best_stock else 1) - 1
        self.co_stock = ((self.co["stock"] >> sb) & 1).astype(np.float32)
        self.max_inst_depth = max((len(i) for i in insts), default=0)
        self.names = names
        rp = lib.R7 / design / "rounds.json"
        self.aff_gain = bool(rp.is_file() and nl.read_json(rp).get("hindsight_arm", "stock") != "stock")
        self.co_net = self._co_net()

    def _co_net(self) -> np.ndarray | None:
        """Pairs that share a CLB in the .net hindsight clustering H (runs/r7f; identical in every seed), for designs where H beat net0."""
        rp = R7F / self.design / "rounds.json"
        if not rp.is_file():
            return None
        r = nl.read_json(rp)
        harm = r.get("hindsight_arm")
        if not harm or harm == "net0":
            return None
        fp = R7F / self.design / f"{harm}.s{1}" / "final.flat_place"
        if not fp.is_file():
            return None
        idx = {n: i for i, n in enumerate(self.names)}
        clb = np.full(self.n, -1, dtype=np.int64)
        for a, row in nl.Flat(fp).atoms.items():
            i = idx.get(lib.base_name(a))
            if i is not None:
                clb[i] = int(str(row[4]).lstrip("#"))
        return ((clb[self.a] == clb[self.b]) & (clb[self.a] >= 0)).astype(np.uint8)

    def target(self, name: str) -> np.ndarray | None:
        return {"aff": self.co_best, "net": self.co_net}[name]

    def _flat_xy(self, fp: Path) -> tuple[np.ndarray, np.ndarray]:
        idx = {n: i for i, n in enumerate(self.names)}
        x = np.full(self.n, -1000, dtype=np.int32)
        y = np.full(self.n, -1000, dtype=np.int32)
        for a, row in nl.Flat(fp).atoms.items():
            i = idx.get(lib.base_name(a))
            if i is not None:
                x[i], y[i] = int(row[0]), int(row[1])
        return x, y

    def net0_dist(self, seeds: tuple[int, ...]) -> np.ndarray | None:
        """Mean Manhattan CLB distance of every pair over the net0 runs of `seeds` (the .net flow of the 'net' target); None if a run is missing."""
        key = ",".join(map(str, seeds))
        if key in self._net0:
            return self._net0[key]
        acc = []
        for s in seeds:
            fp = R7F / self.design / f"net0.s{s}" / "final.flat_place"
            if not fp.is_file():
                self._net0[key] = None
                return None
            x, y = self._flat_xy(fp)
            d = np.abs(x[self.a] - x[self.b]) + np.abs(y[self.a] - y[self.b])
            acc.append(np.minimum(np.where((x[self.a] < 0) | (x[self.b] < 0), 254, d), 254).astype(np.float32))
        self._net0[key] = np.mean(acc, axis=0)
        return self._net0[key]

    def dist_base(self, target: str) -> np.ndarray:
        """Distance feature of the baseline model (disjoint from dist_r2)."""
        if target == "net":
            d = self.net0_dist(lib.NET_SEEDS)
            if d is not None:
                return d
        return self.dist_other

    def dist_r2(self, target: str) -> np.ndarray:
        """Regression target of the R2 comparison (disjoint from dist_base)."""
        if target == "net":
            d = self.net0_dist(lib.HELD_SEEDS)
            if d is not None:
                return d
        return self.dist5

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
        carry = ((self.rel[idx] >> REL_BITS["carry_nb"]) & 1).astype(bool)
        if perm is not None:  # the null shuffles the carry flag over the pairs as well (it is a structural label, not an atom label)
            carry = carry[np.random.default_rng(int(perm[:16].sum()) * 7919 + len(idx)).permutation(len(idx))]
        out = {"same_word": sw, "same_bit": sb, "same_word_bit": sw & sb,
               "same_stmt": (L["stmt"][a] >= 0) & (L["stmt"][a] == L["stmt"][b]),
               "same_inst_d1": (L["inst1"][a] >= 0) & (L["inst1"][a] == L["inst1"][b]),
               "same_inst_d2": (L["inst2"][a] >= 0) & (L["inst2"][a] == L["inst2"][b]),
               "same_inst_d3": (L["inst3"][a] >= 0) & (L["inst3"][a] == L["inst3"][b]),
               "same_inst_full": (L["inst"][a] >= 0) & (L["inst"][a] == L["inst"][b]),
               "carry_nb": carry}
        both = sw & (L["bit"][a] >= 0) & (L["bit"][b] >= 0)
        out["bit_close"] = np.where(both, 1.0 / (1.0 + np.abs(L["bit"][a].astype(np.int32) - L["bit"][b])), 0.0)
        return out

    def base_matrix(self, idx: np.ndarray, target: str = "aff") -> np.ndarray:
        a, b = self.a[idx], self.b[idx]
        ns = self.nshared[idx].astype(np.float32)
        ser = self.series[idx].astype(np.float32)
        mf = self.minfan[idx].astype(np.float32)
        ka, kb = self.kind[a], self.kind[b]
        lo, hi = np.minimum(ka, kb), np.maximum(ka, kb)
        cols = [np.log1p(ns), ser, self.scrit[idx], ((ns > 0) & (ser == 0)).astype(np.float32),
                np.where(mf > 0, np.log1p(mf), 0.0), np.minimum(self.pcrit[a], self.pcrit[b]),
                np.maximum(self.pcrit[a], self.pcrit[b]), ((lo == 0) & (hi == 0)).astype(np.float32),
                ((lo == 0) & (hi == 1)).astype(np.float32), ((lo == 1) & (hi == 1)).astype(np.float32), (hi == 2).astype(np.float32),
                self.co_stock[idx], np.log1p(self.dist_base(target)[idx])]
        return np.stack(cols, axis=1).astype(np.float32)


def boot_mean_ci(vals: list[float], groups: list[str] | None = None, seed: int = lib.RNG_SEED) -> tuple[float, float]:
    """95% percentile bootstrap interval of the mean. With `groups` (the family of each value) the resampling unit is the FAMILY:
    families are drawn with replacement and all their designs enter (item 16, fix round 2); without, the values are the units."""
    pairs = [(x, g) for x, g in zip(vals, groups if groups is not None else range(len(vals))) if x == x]
    if len(pairs) < 2:
        return float("nan"), float("nan")
    by: dict = {}
    for x, g in pairs:
        by.setdefault(g, []).append(x)
    fam = [np.array(v, dtype=float) for v in by.values()]
    if len(fam) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    sums = np.array([f.sum() for f in fam])
    cnts = np.array([len(f) for f in fam], dtype=float)
    pick = rng.integers(0, len(fam), size=(BOOT, len(fam)))
    m = sums[pick].sum(axis=1) / cnts[pick].sum(axis=1)
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
    same_ok: dict[tuple[str, str], bool] = {}
    nonempty = {lv: False for lv in LEVELS}
    for d in ds:
        E = d.E
        dist = d.dist10[E]
        rels = d.rel_from(None, E)
        ns = d.nshared[E]
        for i, lv in enumerate(LEVELS):
            nonempty[lv] |= bool(rels[lv].any())
            for earlier in LEVELS[:i]:
                same_ok[(lv, earlier)] = same_ok.get((lv, earlier), True) and bool(np.array_equal(rels[lv], rels[earlier]))
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
                   "holds_negative_median": bool(med < 0), "shuffles": len(null_meds),
                   "same_as": next((e for e in LEVELS if (lv, e) in same_ok and same_ok[(lv, e)] and nonempty[lv]), None),
                   "max_inst_depth": {d.design: d.max_inst_depth for d in ds}}
    return res


# ---------------------------------------------------------------------------------------
# (b) disagreement, (c) stability

def disagreement(ds: list[D], shuffles: int) -> dict:
    """D+ = pairs co-CLB in the best hindsight run and not in the stock run of the same seed; D- the reverse; agree = both."""
    cnt = {"dplus": 0, "dminus": 0, "agree": 0, "univ": 0}
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
                  "agree": np.flatnonzero((h == 1) & (s == 1)), "univ": d.E}
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
            # baseline = the relation's share among the pairs of the universe (unbiased samples), as the protocol says;
            # the share among the pairs both clusterings join is kept as `enrichment_vs_agree` (the earlier, deviating baseline)
            o = share(obs, k) / share(obs, "univ") if share(obs, "univ") else float("nan")
            nulls = [share(r, k) / share(r, "univ") for r in null_rows if share(r, "univ")]
            oa = share(obs, k) / share(obs, "agree") if share(obs, "agree") else float("nan")
            row[k] = {"share": share(obs, k), "universe_share": share(obs, "univ"), "agree_share": share(obs, "agree"), "enrichment": o,
                      "enrichment_vs_agree": oa,
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
        k[d.E] = (d.dist[d.E] <= NEAR_DIST).sum(axis=1)
        idx = np.flatnonzero(k >= 1)
        stable = k[idx] >= STABLE_MIN
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
            "definition": f"near = Manhattan CLB distance <= {NEAR_DIST} in a seed; pairs of the unbiased samples near in >= 1 seed; stable = near in >= {STABLE_MIN} of {len(lib.SEEDS)}",
            "hist_seeds_co_stock": hist.tolist(), "pairs": int(hist.sum()), "stable_ge8": int(hist[STABLE_MIN:].sum()), "stable_min": STABLE_MIN, "near_dist": NEAR_DIST, "n_seeds": len(lib.SEEDS),
            "by_class_stable_share": {c: (float(cls_stable[i, 0] / cls_stable[i, 1]) if cls_stable[i, 1] else None)
                                      for i, c in enumerate(("SC", "SN", "SI", "OR", "FL"))},
            "by_class_pairs": {c: int(cls_stable[i, 1]) for i, c in enumerate(("SC", "SN", "SI", "OR", "FL"))}, "levels": levels}


# ---------------------------------------------------------------------------------------
# (a), (d) models, leave one design out

def model_loop(ds: list[D], shuffles: int, target: str, designs: list[D], only_chg: bool = False) -> dict:
    """Held-out-FAMILY models for `target` ('aff': co-CLB in the best affinity-bias run; 'net': co-CLB in the .net hindsight
    clustering) on `designs`. AUC is reported per sample (connected pairs, uniform pairs), never on the mixture, because the two
    samples have different inclusion probabilities. The distance target is normalised by the design's mean distance."""
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.metrics import roc_auc_score, r2_score
    from sklearn.preprocessing import StandardScaler

    def prep(d: D, perm: np.ndarray | None, sub: np.ndarray) -> dict:
        rel = d.rel_from(perm, sub)
        base = d.base_matrix(sub, target)
        hdl = np.stack([rel[f].astype(np.float32) for f in HDL_FEATS], axis=1)
        return {"base": base, "hdl": hdl}

    def subset(d: D, cap: int, seed: int) -> np.ndarray:
        E = d.E
        if len(E) > cap:
            E = np.sort(np.random.default_rng(seed).choice(E, cap, replace=False))
        return E

    def auc(y: np.ndarray, p: np.ndarray, m: np.ndarray) -> float:
        return float(roc_auc_score(y[m], p[m])) if m.any() and y[m].min() != y[m].max() else float("nan")

    designs = [d for d in designs if d.target(target) is not None and d.target(target)[d.E].any()]
    out: dict = {"target": target, "designs": [d.design for d in designs], "families": sorted({family(d.design) for d in designs})}
    bit_cols = [HDL_FEATS.index(f) for f in BIT_FEATS]

    def fit_eval(perm_seed: int | None, want_coef: bool) -> dict:
        data = {}
        for d in designs:
            perm = None if perm_seed is None else np.random.default_rng(lib.RNG_SEED + 1000 + perm_seed).permutation(d.n)
            tr = subset(d, TRAIN_CAP, 1)
            te = subset(d, EVAL_CAP, 2)
            y1 = d.target(target)
            r2t = d.dist_r2(target)
            scale = float(r2t[d.E].mean()) or 1.0
            data[d.design] = {"ptr": prep(d, perm, tr), "pte": prep(d, perm, te), "y1tr": y1[tr], "y1te": y1[te],
                              "y2tr": r2t[tr] / scale, "y2te": r2t[te] / scale,
                              "chg_tr": (y1[tr] != d.co_stock[tr]), "chg_te": (y1[te] != d.co_stock[te]),
                              "conn": (d.src[te] & 8) > 0, "uni": ((d.src[te] & 8) == 0) & ((d.src[te] & 4) > 0)}
        res: dict = {"auc": {}, "auc_uni": {}, "auc_chg": {}, "r2": {}, "coef": {}}
        for held in designs:
            train = [data[d.design] for d in designs if family(d.design) != family(held.design)]
            if not train:
                continue
            te = data[held.design]
            Xs = {"base": lambda p: p["base"], "bit": lambda p: np.hstack([p["base"], p["hdl"][:, bit_cols]]),
                  "full": lambda p: np.hstack([p["base"], p["hdl"]])}
            if perm_seed is not None:
                Xs = {k: v for k, v in Xs.items() if k != "base"}
            if only_chg:
                Xs = {}
            for name, fx in Xs.items():
                Xtr = np.vstack([fx(t["ptr"]) for t in train])
                ytr = np.concatenate([t["y1tr"] for t in train])
                if ytr.min() == ytr.max() or te["y1te"].min() == te["y1te"].max():
                    continue
                sc = StandardScaler().fit(Xtr)
                lr = LogisticRegression(max_iter=300, C=1.0).fit(sc.transform(Xtr), ytr)
                p = lr.predict_proba(sc.transform(fx(te["pte"])))[:, 1]
                res["auc"].setdefault(name, {})[held.design] = auc(te["y1te"], p, te["conn"])
                res["auc_uni"].setdefault(name, {})[held.design] = auc(te["y1te"], p, te["uni"])
                if want_coef and name == "full":
                    names = list(BASE_FEATS) + list(HDL_FEATS)
                    res["coef"][held.design] = {n: float(c) for n, c in zip(names, lr.coef_[0])}
                ytr2 = np.concatenate([t["y2tr"] for t in train])
                rg = Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr2)
                res["r2"].setdefault(name, {})[held.design] = float(r2_score(te["y2te"], rg.predict(sc.transform(fx(te["pte"])))))
            # Item 10 (fix round 2): the pairs whose co-CLB status CHANGED between the stock clustering and the target clustering
            # (D+ joined, D- split). The stock co-CLB flag AND the stock distance are dropped: on these pairs the flag equals 1 - target
            # and the distance is 0 for every split pair (a first run with the distance kept scored AUC 1.0, pure leakage), so the model
            # must rank the joined against the split pairs from the other features alone; trained on the changed pairs of the other families.
            keep = [i for i, f in enumerate(BASE_FEATS) if f not in ("co_stock", "log_dist_stock")]
            Xc = {"base": lambda p: p["base"][:, keep], "full": lambda p: np.hstack([p["base"][:, keep], p["hdl"]])}
            if perm_seed is not None:
                Xc = {k: v for k, v in Xc.items() if k != "base"}
            ctr = np.concatenate([t["chg_tr"] for t in train])
            ytr_all = np.concatenate([t["y1tr"] for t in train])
            cte = te["chg_te"]
            if ctr.sum() >= 50 and cte.sum() >= 20 and len(set(ytr_all[ctr])) == 2 and len(set(te["y1te"][cte])) == 2:
                for name, fx in Xc.items():
                    Xtr = np.vstack([fx(t["ptr"])[t["chg_tr"]] for t in train])
                    sc = StandardScaler().fit(Xtr)
                    lr = LogisticRegression(max_iter=300, C=1.0).fit(sc.transform(Xtr), ytr_all[ctr])
                    p = lr.predict_proba(sc.transform(fx(te["pte"])[cte]))[:, 1]
                    res["auc_chg"].setdefault(name, {})[held.design] = float(roc_auc_score(te["y1te"][cte], p))
                    res.setdefault("n_chg", {})[held.design] = int(cte.sum())
        return res

    obs = fit_eval(None, True)
    out["observed"] = obs
    nulls = [fit_eval(k, False) for k in range(shuffles)]
    summ: dict = {}
    for tgt in (("auc_chg",) if only_chg else ("auc", "auc_uni", "auc_chg", "r2")):
        for name in ("bit", "full"):
            base_t = obs[tgt].get("base", {})
            hs = [h for h in obs[tgt].get(name, {}) if h in base_t and obs[tgt][name][h] == obs[tgt][name][h] and base_t[h] == base_t[h]]
            dd = [obs[tgt][name][h] - base_t[h] for h in hs]
            nd = []
            for nres in nulls:
                v = [nres[tgt][name][h] - base_t[h] for h in nres[tgt].get(name, {}) if h in base_t
                     and nres[tgt][name][h] == nres[tgt][name][h] and base_t[h] == base_t[h]]
                if v:
                    nd.append(float(np.mean(v)))
            lo, hi = boot_mean_ci(dd, [family(h) for h in hs])
            summ[f"{tgt}_{name}_minus_base"] = {"mean": float(np.mean(dd)) if dd else None, "median": float(np.median(dd)) if dd else None,
                                                "per_design": dict(zip(hs, dd)),
                                                "ci_lo": lo, "ci_hi": hi,
                                                "n_designs": len(dd), "n_positive": int(sum(1 for x in dd if x > 0)),
                                                "null_mean": float(np.mean(nd)) if nd else None,
                                                "null_lo": float(np.percentile(nd, 2.5)) if nd else None,
                                                "null_hi": float(np.percentile(nd, 97.5)) if nd else None, "shuffles": len(nd)}
    coefs: dict = {}
    for f in list(BASE_FEATS) + list(HDL_FEATS):
        v = [c[f] for c in obs["coef"].values()]
        lo, hi = boot_mean_ci(v, [family(h) for h in obs["coef"]])
        coefs[f] = {"mean": float(np.mean(v)) if v else None, "ci_lo": lo, "ci_hi": hi}
    out["summary"] = summ
    out["coef_full"] = coefs
    for key in ("auc", "auc_uni"):
        vals = [x for x in obs[key].get("base", {}).values() if x == x]
        out[f"{key}_base_mean"] = float(np.mean(vals)) if vals else None
        out[f"{key}_base_median"] = float(np.median(vals)) if vals else None
    return out


def model_variants(ds: list[D], shuffles: int, only_chg: bool = False) -> dict:
    """The primary model run restricts the 'good placement' target to designs where hindsight beat stock (B5); the variant that
    keeps every design is labelled as such."""
    return {"net_gain": model_loop(ds, shuffles, "net", [d for d in ds if d.co_net is not None], only_chg),
            "aff_gain": model_loop(ds, shuffles, "aff", [d for d in ds if d.aff_gain], only_chg),
            "aff_all": model_loop(ds, shuffles, "aff", ds, only_chg)}


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


def refresh_chg(argv: list[str]) -> int:
    """--chg-only: recompute only the changed-pair AUC of each model variant and patch it into data/r7/mine.json (the rest of the file
    is kept). Same code path, seeds and shuffles as a full run; used after the changed-pair feature set was corrected."""
    designs = [a for a in argv if not a.startswith("--")] or [d for d in lib.MAIN if (lib.R7 / d / "pairs.npz").is_file()]
    ds = [D(d) for d in designs]
    res = nl.read_json(lib.DATA7 / "mine.json")
    new = model_variants(ds, N_SHUF_MODEL, only_chg=True)
    for k, v in new.items():
        res["models"][k]["observed"]["auc_chg"] = v["observed"]["auc_chg"]
        res["models"][k]["observed"]["n_chg"] = v["observed"].get("n_chg", {})
        res["models"][k]["summary"]["auc_chg_full_minus_base"] = v["summary"]["auc_chg_full_minus_base"]
    nl.write_json(lib.DATA7 / "mine.json", res)
    print("changed-pair AUC refreshed", designs)
    return 0


def main(argv: list[str]) -> int:
    if "--chg-only" in argv:
        return refresh_chg(argv)
    quick = "--quick" in argv
    designs = [a for a in argv if not a.startswith("--")] or [d for d in lib.MAIN if (lib.R7 / d / "pairs.npz").is_file()]
    ds = [D(d) for d in designs]
    ns, nm = (5, 3) if quick else (N_SHUF, N_SHUF_MODEL)
    res = {"designs": designs, "date": "2026-10-27", "exploratory": True, "shuffles": ns, "model_shuffles": nm,
           "table_xi": table_xi(ds, ns), "disagreement": disagreement(ds, ns), "stability": stability(ds, ns),
           "models": model_variants(ds, nm), "families": {d.design: family(d.design) for d in ds}, "figures": figure_data(ds)}
    nl.write_json(lib.DATA7 / "mine.json", res)
    print("mine written", len(designs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
