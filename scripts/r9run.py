"""Round 9 runner and statistics (docs/plan/round9-tpeko-real.md). One VPR at a time under the Norns VPR lock.

  python scripts/r9run.py arms DESIGN [DESIGN ...] [--cons own,foreign] [--shuffles 1,2,3] [--seeds 1,2,3] [--ordered]
  python scripts/r9run.py summary [DESIGN ...]

Run outputs are under $R9_OUT (default ~/odin3-ws/work/r9-out), outside the worktree, never deleted. A finished run is skipped.
Arms: `stock` (stock vpr) and `known` (Norns vpr, affinity = C, beta 100, queued proposals). Metrics per run come from the
VPR log and the packed `.net`: CLBs, cut (logic nets), purity, exact clusters, WL, channel width, CPD.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import nornlib as nl
import r9build as rb

OUT = rb.OUT_ROOT
NORNS_VPR = Path(os.environ.get("NORNS_VPR", str(rb.WS_ROOT / "work" / "norns-vtr" / "build" / "vpr" / "vpr")))
LOCK = rb.LOCK
MEM_BYTES = 14 * 1024 ** 3
TIMEOUT = 7200
NPATHS = 100
BETA_KNOWN = 100
BOOT = 10000
BOOT_SEED = 20261029
SEEDS = (1, 2, 3)


def read_clbs(net: Path) -> tuple:
    """(atom -> cluster index over all top-level blocks, set of logic cluster indices)."""
    root = ET.parse(net).getroot()
    atom_cl: dict = {}
    logic = set()
    for k, top in enumerate(root.findall("block")):
        if top.get("instance", "").startswith("clb["):
            logic.add(k)
        stack = [top]
        while stack:
            x = stack.pop()
            kids = x.findall("block")
            if kids:
                stack += kids
            elif x.get("name") != "open":
                atom_cl[x.get("name")] = k
    return atom_cl, logic


def pack_metrics(net: Path, aff: dict, struct: dict, vatoms: list) -> dict:
    atom_cl, logic = read_clbs(net)
    per_clb: dict = collections.defaultdict(collections.Counter)
    for a, lab in aff.items():
        c = atom_cl.get(a)
        if c in logic:
            per_clb[c][lab] += 1
    total = sum(sum(v.values()) for v in per_clb.values())
    purity = sum(max(v.values()) for v in per_clb.values()) / total if total else float("nan")
    where: dict = collections.defaultdict(set)
    size_c = collections.Counter(aff.values())
    for c, cnt in per_clb.items():
        for lab in cnt:
            where[lab].add(c)
    exact = 0
    for lab, cs in where.items():
        if len(cs) == 1:
            c = next(iter(cs))
            if per_clb[c][lab] == size_c[lab] == sum(per_clb[c].values()):
                exact += 1
    # cut over the logic hypergraph H*: a vertex sits where its last atom sits
    vclb = []
    for atoms in vatoms:
        vclb.append(atom_cl.get(atoms[-1], -1) if atoms else -1)
    cut = sum(1 for vs in struct["hn"] if len({vclb[v] for v in vs}) > 1)
    return {"logic_clbs": len(logic), "purity": purity, "exact_clusters": exact, "reproduction": exact / struct["K"],
            "cut_star": cut, "cut_ratio": cut / struct["cut_star_C"] if struct["cut_star_C"] else float("nan"),
            "labelled_atoms": total}


def run_dir(design: str, cons: str, sh: int, arm: str, seed: int) -> Path:
    return OUT / design / cons / f"sh{sh}" / "run" / f"{arm}.s{seed}"


def arm_run(design: str, cons: str, sh: int, arm: str, seed: int) -> dict:
    cwd = run_dir(design, cons, sh, arm, seed)
    mp = cwd / "metrics.json"
    if mp.is_file():
        return json.loads(mp.read_text())
    cwd.mkdir(parents=True, exist_ok=True)
    base = OUT / design / cons
    shd = base / f"sh{sh}"
    blif = shd / "design.blif"
    flags = ["--seed", str(seed), "--timing_report_npaths", str(NPATHS), "--write_initial_place_file", str(cwd / "initial.place"),
             "--write_flat_place", str(cwd / "final.flat_place")]
    if arm == "known":
        flags += ["--norns_affinity", str(shd / "affinity.tsv"), "--norns_affinity_weight", f"{BETA_KNOWN:g}",
                  "--norns_proposal_count", "queued"]
    binary = rb.STOCK_VPR if arm == "stock" else NORNS_VPR
    cmd = ["prlimit", f"--as={MEM_BYTES}", "flock", "-x", LOCK, str(binary), str(rb.ARCH), str(blif)] + flags
    log = cwd / "vpr.out"
    with log.open("w") as fh:
        try:
            rc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=TIMEOUT, check=False).returncode
        except subprocess.TimeoutExpired:
            rc = -9
    rec: dict = {"design": design, "cons": cons, "shuffle": sh, "arm": arm, "vseed": seed, "rc": rc}
    if rc == 0:
        rec.update(nl.Metrics(log).values)
        rec.pop("init_t", None)
        text = log.read_text(errors="replace")
        import re
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        if m:
            rec["pack_s"] = float(m.group(1))
        aff = {}
        for line in (shd / "affinity.tsv").read_text().splitlines():
            a, lab = line.split("\t")
            aff[a] = int(lab)
        struct = json.loads((base / "struct.json").read_text())
        struct["cut_star_C"] = json.loads((base / "build.json").read_text())["cut_star_C"]
        vatoms = json.loads((shd / "vatoms.json").read_text())
        net = cwd / (blif.stem + ".net")
        if net.is_file():
            rec.update(pack_metrics(net, aff, struct, vatoms))
        m = re.search(r"Norns affinity: (\d+) of (\d+) file entries matched atoms, (\d+) groups", text)
        rec["affinity_matched"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))] if m else None
    else:
        rec["error"] = "timeout" if rc == -9 else "see vpr.out"
    mp.write_text(json.dumps(rec, sort_keys=True))
    with (OUT / "runs.jsonl").open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{design}/{cons}/sh{sh}/{arm}.s{seed}: rc={rc} clbs={rec.get('logic_clbs')} cut={rec.get('cut_star')} "
          f"purity={rec.get('purity')} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} W={rec.get('chan_width')}", flush=True)
    return rec


def arms(designs: list, cons: list, shuffles: list, seeds: list, ordered: bool) -> int:
    for d in designs:
        for c in cons:
            for sh in shuffles:
                for seed in seeds:
                    for arm in ("stock", "known"):
                        arm_run(d, c, sh, arm, seed)
            if ordered:
                for seed in seeds:
                    arm_run(d, c, 0, "stock", seed)
    return 0


# ---------------------------------------------------------------------------------------
# statistics

def gmean(xs: list) -> float:
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def boot_p_ci(logs: list, rnd: random.Random) -> tuple:
    n = len(logs)
    means = sorted(sum(logs[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    lo, hi = means[int(0.05 * BOOT)], means[int(0.95 * BOOT) - 1]
    p_le = sum(1 for m in means if m <= 0) / BOOT
    p_ge = sum(1 for m in means if m >= 0) / BOOT
    return min(1.0, 2 * min(p_le, p_ge)), lo, hi


def holm(ps: list) -> list:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj = [1.0] * len(ps)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def status(gm: float, lo: float, hi: float, p_adj: float) -> str:
    excludes0 = p_adj < 0.10
    if gm >= 1.05 and excludes0:
        return "ROOM"
    if gm <= 1.02 or (lo > math.log(0.98) and hi < math.log(1.02)):
        return "NO ROOM"
    return "INCONCLUSIVE"


def summary(designs: list) -> int:
    runs = [json.loads(x) for x in (OUT / "runs.jsonl").read_text().splitlines() if x.strip()] if (OUT / "runs.jsonl").is_file() else []
    runs = [r for r in runs if r["rc"] == 0 and (not designs or r["design"] in designs)]
    by = collections.defaultdict(dict)
    for r in runs:
        by[(r["design"], r["cons"])][(r["shuffle"], r["arm"], r["vseed"])] = r
    rnd = random.Random(BOOT_SEED)
    rows = []
    for (d, c), recs in sorted(by.items()):
        pairs = [(sh, s) for (sh, arm, s) in recs if arm == "stock" and sh != 0 and (sh, "known", s) in recs]
        if not pairs:
            continue
        build = json.loads((OUT / d / c / "build.json").read_text())
        out = {"design": d, "cons": c, "n": len(pairs), "K": build["K"], "K_vpr": build["K_vpr"], "dummies": build["dummies"],
               "cut_star_C": build["cut_star_C"]}
        ps, res = [], {}
        for m in ("logic_clbs", "wirelength", "cpd_ns"):
            logs = [math.log(recs[(sh, "stock", s)][m] / recs[(sh, "known", s)][m]) for sh, s in pairs]
            p, lo, hi = boot_p_ci(logs, rnd)
            res[m] = (math.exp(sum(logs) / len(logs)), lo, hi, p)
            ps.append(p)
        adj = holm(ps)
        for (m, (gm, lo, hi, _p)), pa in zip(res.items(), adj):
            out[m] = {"gm": gm, "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "status": status(gm, lo, hi, pa)}
        for arm in ("stock", "known"):
            sel = [recs[(sh, arm, s)] for sh, s in pairs]
            out[arm] = {"clbs": sum(r["logic_clbs"] for r in sel) / len(sel), "purity": sum(r["purity"] for r in sel) / len(sel),
                        "cut_ratio": sum(r["cut_ratio"] for r in sel) / len(sel),
                        "reproduction": sum(r["reproduction"] for r in sel) / len(sel),
                        "exact_max": max(r["reproduction"] for r in sel)}
        ordered = [r for (sh, arm, s), r in recs.items() if sh == 0]
        if ordered:
            out["ordered_stock"] = {"n": len(ordered), "purity": sum(r["purity"] for r in ordered) / len(ordered),
                                    "clbs": sum(r["logic_clbs"] for r in ordered) / len(ordered)}
        rows.append(out)
    print(json.dumps(rows, indent=1))
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--cons", default="own,foreign")
    ap.add_argument("--shuffles", default="1,2,3")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--ordered", action="store_true")
    a = ap.parse_args(argv)
    if a.mode == "arms":
        return arms(a.designs, a.cons.split(","), [int(x) for x in a.shuffles.split(",")], [int(x) for x in a.seeds.split(",")], a.ordered)
    if a.mode == "summary":
        return summary(a.designs)
    print("unknown mode", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
