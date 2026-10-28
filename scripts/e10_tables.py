"""E10 summary tables (docs/plan/e10.md sections 3 and 6). Stdlib only; reads the run root and e10.db, writes CSV and JSON to data/e10/.

Usage: python3 scripts/e10_tables.py --root RUNROOT --db e10.db --out data/e10 [--label e10]
"""
import argparse
import csv
import json
import math
import random
import sqlite3
import statistics
from pathlib import Path

LEVELS = [  # (level name, config, arm)
    ("abc1", "abc1", "vpr_sa"), ("abc2", "abc2", "vpr_sa"), ("k4", "k4", "vpr_sa"), ("earch", "earch", "vpr_sa"),
    ("uon", "uon", "vpr_sa"), ("uoff", "uoff", "vpr_sa"),
    ("vpr_ap", "plc", "vpr_ap"), ("ext_nextpnr_heap", "plc", "ext_nextpnr_heap"), ("ext_nextpnr_sa", "plc", "ext_nextpnr_sa"),
]
NETKEY = {"base": "base", "abc1": "abc1", "abc2": "abc2", "k4": "k4", "earch": "earch", "uon": "base", "uoff": "base", "plc": "base"}
MEASURES = ("luts", "clbs", "cpd_ns", "wl")
BOOT_N, BOOT_SEED = 10000, 20261026


def lut_count(blif):
    return sum(1 for ln in blif.read_text(errors="replace").splitlines() if ln.startswith(".names") and len(ln.split()) >= 3)


def load_runs(root, label, designs):
    """rows: dict (config, arm, design, seed) -> metrics; failures list."""
    rows, fails = {}, []
    for f in sorted((root / "data" / "placers").glob(f"{label}-*_*.json")):
        d = json.loads(f.read_text())
        cfg = d["tag"][len(label) + 1:]
        for r in d["runs"]:
            key = (cfg, r["arm"], d["design"], r["seed"])
            ok = r["rc"] == 0 and r.get("routed_ok")
            np_s = (r.get("nextpnr") or {}).get("wall_s")
            rows[key] = {"ok": bool(ok), "wl": r.get("wl"), "W": r.get("W"), "cpd_ns": r.get("cpd_ns"), "clbs": r.get("clbs"),
                         "vpr_s": r.get("flow_s"), "nextpnr_s": np_s}
            if not ok:
                fails.append({"config": cfg, "arm": r["arm"], "design": d["design"], "seed": r["seed"], "error": r.get("error", "")})
    return rows, fails


def median_of(rows, cfg, arm, design, measure):
    v = [rows[k][measure] for k in rows if k[0] == cfg and k[1] == arm and k[2] == design and rows[k]["ok"] and rows[k].get(measure) is not None]
    return statistics.median(v) if v else None


def boot(ratios, rnd):
    g = lambda xs: math.exp(sum(math.log(x) for x in xs) / len(xs))
    est = g(ratios)
    ests = sorted(g([ratios[rnd.randrange(len(ratios))] for _ in ratios]) for _ in range(BOOT_N))
    return est, ests[int(0.025 * BOOT_N)], ests[int(0.975 * BOOT_N) - 1]


def ratio_table(rows, luts, designs, suite_of, out):
    rnd = random.Random(BOOT_SEED)
    table, excluded = [], []
    for lname, cfg, arm in LEVELS:
        for suite in ("all", "mcnc20", "norns15"):
            for m in MEASURES:
                rs, miss = [], []
                for d in designs:
                    if suite != "all" and suite_of(d) != suite:
                        continue
                    if m == "luts":
                        a, b = luts.get((NETKEY[cfg], d)), luts.get(("base", d))
                    else:
                        a, b = median_of(rows, cfg, arm, d, m), median_of(rows, "base", "vpr_sa", d, m)
                    if a and b:
                        rs.append(a / b)
                    else:
                        miss.append(d)
                if rs:
                    est, lo, hi = boot(rs, rnd)
                    table.append({"level": lname, "suite": suite, "measure": m, "n_designs": len(rs), "geomean_ratio": round(est, 6), "ci95_lo": round(lo, 6), "ci95_hi": round(hi, 6)})
                if miss and suite == "all":
                    excluded.append({"level": lname, "measure": m, "excluded": miss})
    with (out / "ratios.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]) if table else ["level"])
        w.writeheader()
        w.writerows(table)
    (out / "excluded.json").write_text(json.dumps(excluded, indent=1) + "\n")
    return table


def form_of(rows_by_level):
    def g(level, col):
        r = rows_by_level.get(level)
        return None if r is None else r[col]
    return (g("lut", "n_luts"), g("lut", "n_ffs"), g("lut", "n_carry"), g("lut", "n_pure"), g("lut", "lost_at_pass"), g("ble", "n_bles"), g("clb", "n_clbs"))


def structure_share(db, label, out):
    con = sqlite3.connect(db)
    q = ("SELECT r.source, r.arm, r.design, r.seed, m.structure_id, m.level, m.n_luts, m.n_ffs, m.n_carry, m.n_pure, m.lost_at_pass, m.n_bles, m.n_clbs "
         "FROM structure_mapping m JOIN run r ON r.run_id = m.run_id WHERE r.source LIKE ?")
    forms = {}
    for src, arm, design, seed, sid, level, *cols in con.execute(q, (f"norns-placers-{label}-%",)):
        cfg = src[len(f"norns-placers-{label}-"):]
        forms.setdefault((cfg, arm.split("-t")[0] if arm.startswith("ext_nextpnr_sa") else arm, design, seed, sid), {})[level] = dict(zip(("n_luts", "n_ffs", "n_carry", "n_pure", "lost_at_pass", "n_bles", "n_clbs"), cols))
    kind = {(d, s): k for d, s, k in con.execute("SELECT design, structure_id, kind FROM structure")}
    con.close()
    counts = {}
    for (cfg, arm, design, seed, sid), lv in forms.items():
        if (cfg, arm) == ("base", "vpr_sa"):
            continue
        base = forms.get(("base", "vpr_sa", design, seed, sid))
        if base is None or "lut" not in base:
            continue  # an instance is a structure with a lut row in the base run
        k = kind.get((f"e10/{design}", sid), "unknown")
        c = counts.setdefault((cfg, arm, k), [0, 0])
        c[1] += 1
        c[0] += form_of(lv) != form_of(base)
    with (out / "structure_form_share.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["config", "arm", "kind", "differing", "instances", "share", "note"])
        for (cfg, arm, k), (dif, n) in sorted(counts.items()):
            w.writerow([cfg, arm, k, dif, n, round(dif / n, 4), "fewer than 5 instances" if n < 5 else ""])
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="e10")
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    order = json.loads((Path(__file__).resolve().parent.parent / "data" / "e10" / "design_order.json").read_text())
    mcnc = {n.strip()[:-5] for n in (Path(__import__("os").environ["VTR_ROOT"]) / "vtr_flow/benchmarks/blif/circuits.txt").read_text().split()}
    suite_of = lambda d: "mcnc20" if d in mcnc else "norns15"
    rows, fails = load_runs(root, a.label, order)
    designs = [d for d in order if any(k[2] == d for k in rows)]
    luts = {}
    for nk in ("base", "abc1", "abc2", "k4", "earch"):
        for d in designs:
            b = root / "netlists" / nk / d / "netlist" / f"{d}.blif"
            if b.is_file():
                luts[(nk, d)] = lut_count(b)
    with (out / "runs.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["config", "arm", "design", "suite", "seed", "ok", "luts", "clbs", "cpd_ns", "wl", "W", "vpr_s", "nextpnr_s"])
        for k in sorted(rows, key=lambda k: (order.index(k[2]), k)):
            r = rows[k]
            w.writerow([k[0], k[1], k[2], suite_of(k[2]), k[3], int(r["ok"]), luts.get((NETKEY[k[0]], k[2])), r["clbs"], r["cpd_ns"], r["wl"], r["W"], r["vpr_s"], r["nextpnr_s"]])
    (out / "failures.json").write_text(json.dumps(fails, indent=1) + "\n")
    table = ratio_table(rows, luts, designs, suite_of, out)
    counts = structure_share(a.db, a.label, out)
    print(f"{len(rows)} runs, {len(fails)} failures, {len(designs)} designs, {len(table)} ratio rows, {len(counts)} structure cells")


if __name__ == "__main__":
    main()
