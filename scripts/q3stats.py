"""Q-N3 statistics (docs/plan/q-n3-rank-right-atom.md): pairwise AUC and top-1 of each feature and of a combined score, on the TEST designs,
against VPR's own queue gain. Reads the per-pack files of q3feat.py. No VPR, memory small.

Usage: python q3stats.py <feat dir> <out json> [<out md>]
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

import q3feat

FEATS = q3feat.FEATS
SIGN = np.array([q3feat.SIGN[f] for f in FEATS], dtype=float)
TEST = ["bigkey", "boundtop", "ch_intrinsics", "diffeq", "diffeq1", "dsip", "elliptic", "ex1010", "frisc", "mkPktMerge", "or1200", "pdc",
        "s38584.1", "seq", "sha", "tseng"]
TUNE = ["alu4", "apex2", "apex4", "blob_merge", "clma", "des", "diffeq2", "ex5p", "misex3", "mkDelayWorker32B", "mkSMAdapter4B", "raygentop",
        "s298", "s38417", "spla", "stereovision1", "stereovision3"]
OKW = float(q3feat.SAMPLE_OK)
NB, SEED = 10000, 20261030
SCORES = list(FEATS) + ["vpr", "comb_A", "comb_B"]


# ---------------------------------------------------------------------------------------------------
def load_events(feat_dir, designs):
    """Yield event dicts with numpy arrays: F (n x 8 signed scores), FR (real view, NaN where absent), gain, right, pick, tg."""
    want = set(designs)
    for p in sorted(Path(feat_dir).glob("*.jsonl.gz")):
        design = p.name[: -len(".jsonl.gz")].rsplit(".", 2)[0]
        if design not in want:
            continue
        for line in gzip.open(p, "rt"):
            e = json.loads(line)
            yield event_arrays(e)


def event_arrays(e):
    cs = e["cands"]
    n = len(cs)
    nan = float("nan")
    F = np.array([c["f"] if c["f"] is not None else [nan] * 8 for c in cs], dtype=float).reshape(n, 8)
    FR = np.array([c["fr"] if c["fr"] is not None else [nan] * 8 for c in cs], dtype=float).reshape(n, 8)
    gain = np.array([c["gain"] for c in cs], dtype=float)
    right = np.array([c["right"] for c in cs], dtype=bool)
    pick = np.array([c["pick"] for c in cs], dtype=bool)
    tg = np.array([c["tg"] for c in cs], dtype=float)
    real_ok = np.array([c["fr"] is not None for c in cs], dtype=bool)
    ip = int(np.argmax(pick)) if pick.any() else -1
    stratum = None
    if e["kind"] == "b" and right.any() and ip >= 0:
        stratum = "time" if tg[ip] > tg[right].max() else "conn"
    return {"design": e["design"], "cons": e["cons"], "kind": e["kind"], "F": F * SIGN, "FR": FR * SIGN, "gain": gain, "right": right,
            "pick": pick, "tg": tg, "real_ok": real_ok, "stratum": stratum, "ip": ip, "tgA": e["tg_A"]}


def _clean(s):
    return np.where(np.isnan(s), -np.inf, s)


def auc_event(s, right, ip):
    sr = np.max(s[right]) if right.any() else float("nan")
    sp = s[ip]
    if np.isnan(sr) or np.isnan(sp):
        return 0.5
    return 1.0 if sr > sp else (0.5 if sr == sp else 0.0)


def top1_event(s, member):
    c = _clean(s)
    m = c.max()
    if not np.isfinite(m):
        return float(member.mean())  # all undefined: chance level
    top = c == m
    return float((top & member).sum() / top.sum())


# ---------------------------------------------------------------------------------------------------
# combined score
def pair_diffs(ev, X, rng, cap=20):
    """Pairwise ranking pairs (member - nonmember) of one event; X is the standardised feature matrix."""
    member = ev["right"] | (ev["pick"] if ev["kind"] == "ok" else np.zeros_like(ev["right"]))
    mi, ni = np.where(member)[0], np.where(~member)[0]
    if len(mi) == 0 or len(ni) == 0:
        return None
    if len(ni) > cap:
        ni = rng.choice(ni, cap, replace=False)
    d = (X[mi][:, None, :] - X[ni][None, :, :]).reshape(-1, X.shape[1])
    return d


def fit_logistic(D, W, lam=1.0, iters=50):
    """No-intercept logistic regression on pair differences d (label 1), sample weights W, L2 lam * |w|^2 / 2."""
    w = np.zeros(D.shape[1])
    for _ in range(iters):
        z = D @ w
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        g = D.T @ (W * (p - 1)) + lam * w
        H = (D * (W * p * (1 - p))[:, None]).T @ D + lam * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def view_event(e, view):
    """Event restricted to one view: dict with F, gain, right, pick, kind (None when the pick or every right atom is not in the view)."""
    if view == "full":
        return e
    ok = e["real_ok"]
    if not ok[e["ip"]] or not (e["right"] & ok).any():
        return None
    return {"kind": e["kind"], "stratum": e["stratum"], "F": e["FR"][ok], "gain": e["gain"][ok], "right": e["right"][ok], "pick": e["pick"][ok]}


def fit_models(tune_events, view="full"):
    """Fit variant A (8 C-free features) and B (A plus the VPR gain) on the TUNE connectivity wrong picks and the right picks, on the
    features of one view (full: D' as is; real: dummies deleted)."""
    tune_events = [v for v in (view_event(e, view) for e in tune_events) if v is not None]
    allx = np.vstack([np.hstack([e["F"], e["gain"][:, None]]) for e in tune_events])
    mu = np.nanmean(allx, axis=0)
    sd = np.nanstd(allx, axis=0)
    sd[sd == 0] = 1
    rng = np.random.default_rng(SEED)
    out = {}
    for name, cols in (("A", list(range(8))), ("B", list(range(9)))):
        Ds, Ws = [], []
        for e in tune_events:
            if e["kind"] == "b" and e["stratum"] != "conn":
                continue
            X = np.hstack([e["F"], e["gain"][:, None]])
            X = np.nan_to_num((X - mu) / sd, nan=0.0)[:, cols]
            d = pair_diffs(e, X, rng)
            if d is None:
                continue
            wt = (OKW if e["kind"] == "ok" else 1.0) / len(d)
            Ds.append(d)
            Ws.append(np.full(len(d), wt))
        D = np.vstack(Ds)
        W = np.concatenate(Ws)
        W = W * len(W) / W.sum()  # mean weight 1
        w = fit_logistic(D, W, lam=1.0)
        out[name] = {"cols": cols, "w": w}
    return mu, sd, out


def combined_scores(F, gain, mu, sd, models):
    X = np.hstack([F, gain[:, None]])
    X = np.nan_to_num((X - mu) / sd, nan=0.0)
    return {k: X[:, m["cols"]] @ m["w"] for k, m in models.items()}


# ---------------------------------------------------------------------------------------------------
def accumulate(events, fits):
    """acc[(view, group, stratum, score, metric)][design] = [sum, n]. metrics: auc, top1 (wrong picks), alltop1 (all decisions)."""
    acc = {}

    def add(key, design, val, wt=1.0):
        d = acc.setdefault(key, {}).setdefault(design, [0.0, 0.0])
        d[0] += val * wt
        d[1] += wt
    for e in events:
        for view in ("full", "real"):
            F = e["F"] if view == "full" else e["FR"]
            ok = np.ones(len(e["gain"]), dtype=bool) if view == "full" else e["real_ok"]
            ip = e["ip"]
            if not ok[ip] or not (e["right"] & ok).any():
                continue
            idx = np.where(ok)[0]
            right, pick, gain = e["right"][idx], e["pick"][idx], e["gain"][idx]
            Fv = F[idx]
            ipv = int(np.argmax(pick))
            sc = {f: Fv[:, i] for i, f in enumerate(FEATS)}
            sc["vpr"] = gain
            mu, sd, models = fits[view]
            sc.update({"comb_" + k: v for k, v in combined_scores(Fv, gain, mu, sd, models).items()})
            member = right | (pick if e["kind"] == "ok" else np.zeros_like(right))
            groups = ("both", e["cons"])
            for g in groups:
                for name, s in sc.items():
                    if e["kind"] == "b":
                        st = e["stratum"]
                        for strat in (st, "all"):
                            add((view, g, strat, name, "auc"), e["design"], auc_event(s, right, ipv))
                            add((view, g, strat, name, "top1"), e["design"], top1_event(s, right))
                        add((view, g, "all", name, "alltop1"), e["design"], top1_event(s, member))
                        if st == "conn":
                            add((view, g, "conn", name, "alltop1"), e["design"], top1_event(s, member))
                    else:
                        add((view, g, "all", name, "alltop1"), e["design"], top1_event(s, member), OKW)
                        add((view, g, "conn", name, "alltop1"), e["design"], top1_event(s, member), OKW)
    return acc


def design_means(acc, key):
    return {d: v[0] / v[1] for d, v in acc.get(key, {}).items() if v[1] > 0}


def boot_mean(vals, rng):
    v = np.array(list(vals))
    n = len(v)
    if n == 0:
        return None
    m = v.mean()
    bs = np.array([v[rng.integers(0, n, n)].mean() for _ in range(NB)])
    return {"mean": float(m), "lo": float(np.quantile(bs, 0.05)), "hi": float(np.quantile(bs, 0.95)), "n": n, "boot": bs}


def pval(bs, null=0.5):
    p = 2 * min((bs <= null).mean(), (bs >= null).mean())
    return max(p, 1.0 / NB)


def bh(ps):
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    m = len(ps)
    q = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        i = idx[rank - 1]
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    return q


def summarise(acc):
    rng = np.random.default_rng(SEED)
    res, tests = {}, []
    for key in sorted(acc):
        view, group, strat, name, metric = key
        dm = design_means(acc, key)
        if not dm:
            continue
        b = boot_mean(dm.values(), rng)
        rec = {"mean": b["mean"], "lo": b["lo"], "hi": b["hi"], "n_designs": b["n"]}
        if metric == "auc":
            rec["p"] = pval(b["boot"])
        res["|".join(key)] = rec
    # paired differences of the combined scores and each feature against VPR gain in top-1 over all decisions
    for view in ("full", "real"):
        for group in ("both", "own", "foreign"):
            for strat in ("all", "conn"):
                base = design_means(acc, (view, group, strat, "vpr", "alltop1"))
                for name in SCORES:
                    if name == "vpr":
                        continue
                    other = design_means(acc, (view, group, strat, name, "alltop1"))
                    ds = [d for d in base if d in other]
                    if not ds:
                        continue
                    diff = [other[d] - base[d] for d in ds]
                    b = boot_mean(diff, rng)
                    res[f"{view}|{group}|{strat}|{name}|alltop1_minus_vpr"] = {"mean": b["mean"], "lo": b["lo"], "hi": b["hi"], "n_designs": b["n"]}
    # BH over features x strata x {own, foreign}, full view
    keys = [f"full|{g}|{s}|{f}|auc" for f in FEATS for s in ("conn", "time") for g in ("own", "foreign")]
    keys = [k for k in keys if k in res]
    q = bh([res[k]["p"] for k in keys])
    for k, qq in zip(keys, q):
        res[k]["q"] = qq
    return res


def main(argv):
    feat_dir, out_json = argv[0], Path(argv[1])
    tune = list(load_events(feat_dir, TUNE))
    fits = {"full": fit_models(tune, "full"), "real": fit_models(tune, "real")}
    del tune
    test = load_events(feat_dir, TEST)
    acc = accumulate(test, fits)
    res = summarise(acc)
    # event counts (labels) over all designs, per stratum
    cnt = {}
    for side, ds in (("TUNE", TUNE), ("TEST", TEST)):
        for e in load_events(feat_dir, ds):
            k = f"{side}|{e['cons']}|{e['kind']}|{e['stratum']}"
            cnt[k] = cnt.get(k, 0) + 1
    out = {"models": {v: {k: {"w": m["w"].tolist(), "cols": m["cols"]} for k, m in fits[v][2].items()} for v in fits},
           "mu": {v: fits[v][0].tolist() for v in fits}, "sd": {v: fits[v][1].tolist() for v in fits},
           "features": list(FEATS) + ["vpr_gain"], "results": res, "event_counts": cnt}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=1))
    print("wrote", out_json)


if __name__ == "__main__":
    main(sys.argv[1:])
