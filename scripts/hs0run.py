"""HS0 runner and statistics (docs/plan/hs0-seed-gap.md): is there a gap between stock VPR's seed order and better seed orders?

  python scripts/hs0run.py gate                      # byte-identical .net gate (15 VTR designs, 5 round 9 D' x seeds 1-3)
  python scripts/hs0run.py arms [DESIGN ...]         # stock, oracle, random x8 on the round 9 D' (own C, ordered file), VPR seeds 1-3
  python scripts/hs0run.py pool [--json FILE]        # pooled gaps, bootstrap, Holm, verdicts

Reads the round 9 D' builds read only from $R9_V2 (default ~/odin3-ws/work/r9-out-v2). Writes under $HS0_OUT (default
~/odin3-ws/work/hs0-out), outside the worktree; nothing is deleted. Every VPR run is under `flock $NORNS_LOCK`
(default /tmp/claude-1000/norns-vpr.lock), with a 14 GB address-space cap. The disk guard reads /mnt/c before each design
and stops below 15 G. A run is finished if and only if its metrics.json exists (written last).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
WS = Path(os.environ.get("WS_ROOT", str(HOME / "odin3-ws")))
R9V2 = Path(os.environ.get("R9_V2", str(WS / "work" / "r9-out-v2")))
OUT = Path(os.environ.get("HS0_OUT", str(WS / "work" / "hs0-out")))
VPR = os.environ.get("NORNS_VPR", str(WS / "work" / "norns-vtr-hs0" / "build" / "vpr" / "vpr"))
LOCK = os.environ.get("NORNS_LOCK", "/tmp/claude-1000/norns-vpr.lock")
ARCH = WS / "external" / "vtr-verilog-to-routing" / "vtr_flow" / "arch" / "timing" / "k6_frac_N10_frac_chain_mem32K_40nm.xml"
SWEEP = WS / "work" / "norns-keep-sweep-out"
MEM = 14 * 1024 ** 3
TIMEOUT = 7200
SEEDS = (1, 2, 3)
R = 8
LIST_SEED = 20261030  # random orders: random.Random(LIST_SEED * 100 + r), r = 1..8
BOOT = 10000
BOOT_SEED = 20261030
NORNS15 = ("ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B", "sha",
           "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2")
GATE_DPRIME = ("ch_intrinsics", "stereovision3", "diffeq2", "diffeq1", "clma")
METRICS = ("logic_clbs", "wirelength", "cpd_ns")
LABEL = {"logic_clbs": "CLB", "wirelength": "WL", "cpd_ns": "CPD"}


def disk_free_g() -> int:
    out = subprocess.run(["df", "--output=avail", "-BG", "/mnt/c"], capture_output=True, text=True, check=True).stdout.split()[-1]
    return int(out.rstrip("G"))


def guard() -> None:
    free = disk_free_g()
    if free < 15:
        print(f"DISK GUARD: /mnt/c has {free}G free (< 15G); stopping", file=sys.stderr)
        sys.exit(3)


def run_vpr(args: list, cwd: Path, log: Path) -> int:
    cmd = ["prlimit", f"--as={MEM}", "flock", "-x", LOCK, VPR, str(ARCH)] + args
    with log.open("w") as fh:
        try:
            return subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=TIMEOUT, check=False).returncode
        except subprocess.TimeoutExpired:
            return -9


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------
# the D' builds (round 9, own C, the ordered file sh0)

def designs_by_size() -> list:
    ds = []
    for d in sorted(os.listdir(R9V2)):
        b = R9V2 / d / "own" / "sh0" / "design.blif"
        if b.is_file() and (R9V2 / d / "own" / "build.json").is_file():
            ds.append((b.stat().st_size, d))
    return [d for _s, d in sorted(ds)]


class Build:
    def __init__(self, design: str):
        self.design = design
        self.base = R9V2 / design / "own"
        self.sh = self.base / "sh0"
        self.blif = self.sh / "design.blif"
        self.build = json.loads((self.base / "build.json").read_text())
        self.n_c = self.build["K"]
        self.aff = []  # (atom, cluster label) in file order
        for line in (self.sh / "affinity.tsv").read_text().splitlines():
            a, lab = line.split("\t")
            self.aff.append((a, int(lab)))
        self.struct = json.loads((self.base / "struct.json").read_text())
        self.vatoms = json.loads((self.sh / "vatoms.json").read_text())

    def seed_atom_of_clusters(self) -> dict:
        """Oracle atom rule: per cluster of C, the vertex with the most nets (of H*) that also touch another vertex of its cluster;
        ties to the lower vertex index; the atom is the first atom of the vertex. Returns cluster -> atom name."""
        cl = self.struct["cl"]
        cnt = [0] * len(cl)
        for net in self.struct["hn"]:
            vs = set(net)
            by: dict = {}
            for v in vs:
                if 0 <= cl[v]:
                    by.setdefault(cl[v], []).append(v)
            for c, members in by.items():
                if len(members) >= 2:
                    for v in members:
                        cnt[v] += 1
        best: dict = {}
        for v, c in enumerate(cl):
            if c < 0 or not self.vatoms[v]:
                continue
            if c not in best or cnt[v] > cnt[best[c]]:
                best[c] = v
        return {c: self.vatoms[v][0] for c, v in best.items()}

    def oracle_list(self, dump: Path) -> list:
        """One seed atom per cluster of C, clusters ordered by the first position, in stock's seed order, of any of their atoms."""
        pos: dict = {}
        for line in dump.read_text().splitlines():
            parts = line.split("\t")
            p = int(parts[0])
            for a in parts[1:]:
                pos.setdefault(a, p)
        first: dict = {}
        for a, lab in self.aff:
            if a in pos:
                first[lab] = min(first.get(lab, pos[a]), pos[a])
        seed_atoms = self.seed_atom_of_clusters()
        order = sorted(seed_atoms, key=lambda c: (first.get(c, 1 << 60), c))
        return [seed_atoms[c] for c in order]

    def random_list(self, r: int) -> list:
        atoms = [a for a, _lab in self.aff]
        random.Random(LIST_SEED * 100 + r).shuffle(atoms)
        return atoms


# ---------------------------------------------------------------------------------------
# gate

def gate() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for d in NORNS15:
        blif = SWEEP / "netlists" / "base" / d / "netlist" / f"{d}.blif"
        ref = SWEEP / "vpr" / "e10-base" / d / "vpr_sa.s1" / f"{d}.net"
        cases.append(("vtr15", d, 1, blif, ref))
    for d in GATE_DPRIME:
        b = Build(d)
        for s in SEEDS:
            refs = sorted((b.sh).glob(f"run-*/stock.s{s}/design.net"))
            cases.append(("dprime_full", d, s, b.blif, refs[0] if refs else Path("/nonexistent")))
    results = []
    for kind, d, s, blif, ref in cases:
        guard()
        g = OUT / "gate" / kind / d / f"s{s}"
        g.mkdir(parents=True, exist_ok=True)
        rec = {"kind": kind, "design": d, "seed": s, "ref": str(ref.relative_to(WS)) if ref.exists() else None}
        (g / "empty.list").write_text("")
        for cond, extra in (("absent", []), ("empty_list_and_dump", ["--norns_seed_list", str(g / "empty.list"), "--norns_seed_dump", str(g / "dump.tsv")])):
            cdir = g / cond
            cdir.mkdir(exist_ok=True)
            net = cdir / f"{blif.stem}.net"
            if not net.is_file() or net.stat().st_size == 0:
                if kind == "vtr15":  # the sweep reference is the SA flow: pack only, as the critical-heap gate
                    base = [str(blif), "--pack", "--seed", str(s), "--timing_report_npaths", "1000"]
                else:  # the round 9 reference is the default (analytic) flow, whose packer is APPack: run the whole flow as the arms do
                    base = [str(blif), "--seed", str(s), "--timing_report_npaths", "100", "--place_file", "/dev/null", "--route_file", "/dev/null"]
                rc = run_vpr(base + extra, cdir, cdir / "vpr.out")
            else:
                rc = 0
            rec[cond] = {"rc": rc, "equal": bool(rc == 0 and ref.is_file() and net.is_file() and sha(net) == sha(ref))}
        results.append(rec)
        print(json.dumps(rec), flush=True)
    summ = {"cases": len(results), "equal_absent": sum(r["absent"]["equal"] for r in results),
            "equal_empty_list_and_dump": sum(r["empty_list_and_dump"]["equal"] for r in results),
            "vtr15": sum(1 for r in results if r["kind"] == "vtr15"), "dprime": sum(1 for r in results if r["kind"] == "dprime_full")}
    (OUT / "gate.json").write_text(json.dumps({"summary": summ, "results": results}, indent=1))
    print("GATE", json.dumps(summ))
    return 0 if summ["cases"] == summ["equal_absent"] == summ["equal_empty_list_and_dump"] else 1


# ---------------------------------------------------------------------------------------
# arms

def count_clbs(net: Path) -> int:
    return len(re.findall(r'<block [^>]*instance="clb\[', net.read_text(errors="replace")))


def arm_run(b: Build, arm: str, seed: int, list_atoms: list | None) -> dict:
    cwd = OUT / "runs" / b.design / f"{arm}.s{seed}"
    mp = cwd / "metrics.json"
    if mp.is_file():
        return json.loads(mp.read_text())
    cwd.mkdir(parents=True, exist_ok=True)
    args = [str(b.blif), "--seed", str(seed), "--timing_report_npaths", "100", "--place_file", "/dev/null", "--route_file", "/dev/null"]
    if arm == "stock":
        args += ["--norns_seed_dump", str(cwd / "seed_dump.tsv")]
    else:
        lst = cwd / "seed.list"
        lst.write_text("".join(a + "\n" for a in list_atoms or []))
        args += ["--norns_seed_list", str(lst)]
    log = cwd / "vpr.out"
    rc = run_vpr(args, cwd, log)
    rec: dict = {"design": b.design, "arm": arm, "vseed": seed, "rc": rc, "n_c": b.n_c, "blif_sha": b.build["shuffles"]["0"]["sha256"]}
    if rc == 0:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import nornlib as nl
        rec.update({k: v for k, v in nl.Metrics(log).values.items() if k in ("wirelength", "cpd_ns", "chan_width", "flow_s")})
        net = cwd / f"{b.blif.stem}.net"
        rec["logic_clbs"] = count_clbs(net)
        text = log.read_text(errors="replace")
        m = re.search(r"Norns seed list: (\d+) entries, (\d+) unmatched, (\d+) distinct molecules", text)
        if m:
            rec["seed_list"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
        rec["net_sha"] = sha(net)
    mp.write_text(json.dumps(rec, sort_keys=True))
    with (OUT / "runs.jsonl").open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{b.design}/{arm}.s{seed}: rc={rc} clbs={rec.get('logic_clbs')} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} list={rec.get('seed_list')}", flush=True)
    return rec


def arms(designs: list) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for d in (designs or designs_by_size()):
        guard()
        if (guard_w := weekly()) >= 97:
            print(f"WEEKLY METER {guard_w} >= 97; stopping", file=sys.stderr)
            return 4
        b = Build(d)
        for s in SEEDS:
            arm_run(b, "stock", s, None)
        for s in SEEDS:
            dump = OUT / "runs" / d / f"stock.s{s}" / "seed_dump.tsv"
            if not dump.is_file():
                print(f"{d}: no stock seed dump for seed {s}; oracle skipped", file=sys.stderr)
                continue
            arm_run(b, "oracle", s, b.oracle_list(dump))
        for s in SEEDS:
            for r in range(1, R + 1):
                arm_run(b, f"rand{r}", s, b.random_list(r))
    return 0


def weekly() -> int:
    try:
        return int(json.loads((HOME / ".claude" / "usage-state" / "latest.json").read_text())["week"])
    except (OSError, ValueError, KeyError):
        return 0


# ---------------------------------------------------------------------------------------
# statistics (design is the unit)

def holm(ps: list) -> list:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj = [1.0] * len(ps)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def boot(vals: list, rnd: random.Random) -> tuple:
    n = len(vals)
    means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    lo, hi = means[int(0.05 * BOOT)], means[int(0.95 * BOOT) - 1]
    p = min(1.0, 2 * min(sum(1 for m in means if m <= 0) / BOOT, sum(1 for m in means if m >= 0) / BOOT))
    return sum(vals) / n, lo, hi, p


def fmt_p(p: float) -> str:
    return f"< {1 / BOOT:g}" if p < 1 / BOOT else f"{p:.4f}"


def read_runs() -> dict:
    """(design, arm, vseed) -> record, only rc 0 runs of the current build."""
    out: dict = {}
    p = OUT / "runs.jsonl"
    for x in (p.read_text(errors="replace").splitlines() if p.is_file() else []):
        try:
            r = json.loads(x)
        except ValueError:
            continue
        if r.get("rc") == 0 and "logic_clbs" in r:
            out[(r["design"], r["arm"], r["vseed"])] = r
    return out


def gm_log(xs: list) -> float:
    return sum(xs) / len(xs)


def median_log(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def per_design(runs: dict, d: str, kc: dict) -> dict | None:
    """Per-design log ratios, geometric mean over the VPR seeds that have every arm."""
    seeds = [s for s in SEEDS if (d, "stock", s) in runs and (d, "oracle", s) in runs and all((d, f"rand{r}", s) in runs for r in range(1, R + 1))]
    if not seeds:
        return None
    row: dict = {"design": d, "seeds": seeds, "n_c": runs[(d, "stock", seeds[0])]["n_c"], "n_c_corrected": kc.get(d)}
    for m in METRICS:
        lg = {"oracle": [], "best8": [], "median8": [], "chance": [], "stock_over_nc": [], "oracle_over_nc": [], "best8_over_nc": [], "median8_over_nc": []}
        for s in seeds:
            st = math.log(runs[(d, "stock", s)][m])
            orc = math.log(runs[(d, "oracle", s)][m])
            rnd = [math.log(runs[(d, f"rand{r}", s)][m]) for r in range(1, R + 1)]
            lg["oracle"].append(st - orc)
            lg["best8"].append(st - min(rnd))
            lg["median8"].append(st - median_log(rnd))
            lg["chance"].append(gm_log(rnd) - min(rnd))
            if m == "logic_clbs":
                nc = math.log(row["n_c"])
                lg["stock_over_nc"].append(st - nc)
                lg["oracle_over_nc"].append(orc - nc)
                lg["best8_over_nc"].append(min(rnd) - nc)
                lg["median8_over_nc"].append(median_log(rnd) - nc)
        for k, v in lg.items():
            if v:
                row[f"{m}:{k}"] = gm_log(v)  # log of the geometric mean over seeds
        row[f"{m}:stock"] = gm_log([math.log(runs[(d, "stock", s)][m]) for s in seeds])
    return row


def corrected_bounds(designs: list) -> dict:
    """Corrected N_C (Kc, round 9 entry 2026-10-30 (b)) of the own build, via scripts/r9pool.py (read only on r9-out-v2)."""
    os.environ["R9_OUT"] = str(R9V2)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import r9pool
        return {d: r9pool.bound_of(d, "own")["Kc"] for d in designs}
    except Exception as exc:  # noqa: BLE001
        print(f"corrected N_C unavailable: {exc}", file=sys.stderr)
        return {}


def pool(json_path: str) -> int:
    runs = read_runs()
    designs = [d for d in designs_by_size() if any(k[0] == d for k in runs)]
    kc = corrected_bounds(designs)
    rows = [r for r in (per_design(runs, d, kc) for d in designs) if r]
    rnd = random.Random(BOOT_SEED)
    res: dict = {"n_designs": len(rows), "designs": [r["design"] for r in rows], "tests": {}, "per_design": rows,
                 "dropped_designs": [d for d in designs if d not in {r["design"] for r in rows}]}
    tests = [(arm, m) for arm in ("oracle", "best8", "median8") for m in METRICS]
    tmp = {}
    ps = []
    for arm, m in tests:
        vals = [r[f"{m}:{arm}"] for r in rows]
        mean, lo, hi, p = boot(vals, rnd)
        tmp[(arm, m)] = (mean, lo, hi, p)
        ps.append(p)
    for (key, (mean, lo, hi, _p)), pa in zip(tmp.items(), holm(ps)):
        arm, m = key
        gap = math.exp(mean)
        exists = pa < 0.05 and math.exp(lo) > 1.0
        reversed_ = pa < 0.05 and math.exp(hi) < 1.0
        res["tests"][f"{arm}/{m}"] = {"gap": gap, "lo": math.exp(lo), "hi": math.exp(hi), "p_holm": pa, "p_holm_str": fmt_p(pa),
                                      "verdict": "POSSIBLY GOOD (gap exists)" if exists else ("REVERSED (arm worse than stock)" if reversed_ else "INCONCLUSIVE")}
    # chance-only reference for best-of-8 and CLB against N_C
    rnd2 = random.Random(BOOT_SEED + 1)
    extra = {}
    for m in METRICS:
        mean, lo, hi, p = boot([r[f"{m}:chance"] for r in rows], rnd2)
        extra[f"chance_mean8_over_best8/{m}"] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi)}
    for k in ("stock_over_nc", "oracle_over_nc", "best8_over_nc", "median8_over_nc"):
        mean, lo, hi, p = boot([r[f"logic_clbs:{k}"] for r in rows], rnd2)
        extra[f"clb/{k}"] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi)}
        if all(r["n_c_corrected"] for r in rows):
            adj = [r[f"logic_clbs:{k}"] + math.log(r["n_c"] / r["n_c_corrected"]) for r in rows]
            mean, lo, hi, p = boot(adj, rnd2)
            extra[f"clb/{k}/corrected"] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi)}
    # sensitivity: without clma (flagged outlier in round 9)
    sens_rows = [r for r in rows if r["design"] != "clma"]
    if len(sens_rows) >= 2 and len(sens_rows) != len(rows):
        for arm, m in tests:
            mean, lo, hi, p = boot([r[f"{m}:{arm}"] for r in sens_rows], rnd2)
            extra[f"no_clma/{arm}/{m}"] = {"gm": math.exp(mean), "lo": math.exp(lo), "hi": math.exp(hi), "p_raw": p}
    res["extra"] = extra
    if json_path:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(res, indent=1, sort_keys=True))
    print(f"designs pooled: {len(rows)} (dropped: {res['dropped_designs']})")
    for k, v in res["tests"].items():
        print(f"{k:16s} stock/arm {v['gap']:.4f} [{v['lo']:.4f}, {v['hi']:.4f}] Holm p {v['p_holm_str']}  {v['verdict']}")
    for k, v in extra.items():
        print(f"{k:34s} {v['gm']:.4f} [{v['lo']:.4f}, {v['hi']:.4f}]")
    return 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("gate", "arms", "pool"))
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    if a.mode == "gate":
        return gate()
    if a.mode == "arms":
        return arms(a.designs)
    return pool(a.json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
