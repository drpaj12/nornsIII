"""Round 3 runs (VPR, one at a time under the heavy lock; protocol: docs/plan/round3.md).

  python scripts/round3.py gate [design ...]     control gate: stock vs Norns packer .net, 15 designs
  python scripts/round3.py pilot [design ...]    beta pilot (pack + place, no route, seed 1) on the 4 smallest
  python scripts/round3.py grid                  freeze the beta grid from the pilot -> data/analysis/r3-grid.json
  python scripts/round3.py arms [design ...]     Stage-4 arms (analytic, then word-seed start), 3 VPR seeds
  python scripts/round3.py status                runs done per design

The stock arm runs the stock vpr ($VPR); Norns arms run $NORNS_VPR. Run directory of a run:
runs/<d>/r3/<tag>/, record in data/<d>/r3runs.jsonl (pilot: r3pilot.jsonl).
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import affinity as af
import matrix
import nornlib as nl
import r3lib

PILOT = ("ch_intrinsics", "stereovision3", "diffeq2", "diffeq1")
CHECKPOINT = nl.DESIGN_ORDER[:8]
BETAS = (0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 4.0)
SEEDS = (1, 2, 3)
NORNS_VPR = Path(os.environ.get("NORNS_VPR", str(nl.WS_ROOT / "work" / "norns-vtr" / "build" / "vpr" / "vpr")))
GRID = nl.DATA / "analysis" / "r3-grid.json"
TIMEOUT = 3600


def r3dir(design: str, tag: str) -> Path:
    return nl.runs_dir(design, "r3", tag)


def records(design: str, name: str = "r3runs.jsonl") -> list[dict]:
    path = nl.DATA / design / name
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def append(design: str, rec: dict, name: str = "r3runs.jsonl") -> None:
    path = nl.DATA / design / name
    nl.ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def cmd_for(binary: Path, blif: Path, extra: list[str]) -> list[str]:
    base = [str(binary), str(nl.ARCH), str(blif)] + extra
    if os.environ.get("NORNS_LOCK_HELD") == "1":
        return base
    return ["flock", "-x", str(nl.LOCK)] + base


def is_done(design: str, tag: str) -> bool:
    p = r3dir(design, tag) / "metrics.json"
    if not p.is_file():
        return False
    try:
        return nl.read_json(p).get("rc") == 0
    except (ValueError, OSError):
        return False


def packing_metrics(design: str, cwd: Path, source_levels: bool = True) -> dict:
    flat = cwd / "final.flat_place"
    atoms, cls = r3lib.clb_atoms_of(flat)
    out = {"clbs": len(atoms), "logic_clbs": sum(1 for c in cls.values() if c == "logic")}
    extra = {}
    if source_levels:
        try:
            extra = {"wordio": af.labels(design, "wordio")}
        except (OSError, ValueError):
            extra = {}
    out["purity"] = r3lib.design_purity(design, flat, ("word", "module") + tuple(extra), extra)
    init = cwd / "initial.place"
    if init.is_file():
        w, h = nl.grid_size(nl.Place(init))
        out["grid"] = [w, h]
    return out


def vpr_run(design: str, tag: str, binary: Path, extra: list[str], *, route: bool = True,
            record: str = "r3runs.jsonl", meta: dict | None = None) -> dict:
    """One VPR run of the default (analytical-placement) flow in runs/<d>/r3/<tag>/."""
    if is_done(design, tag):
        return nl.read_json(r3dir(design, tag) / "metrics.json")
    cwd = r3dir(design, tag)
    if cwd.exists():
        shutil.rmtree(cwd)
    nl.ensure_dir(cwd)
    log = cwd / "vpr.out"
    args = (extra + ["--write_initial_place_file", str(cwd / "initial.place"),
                     "--write_flat_place", str(cwd / "final.flat_place")])
    if not route:
        args = args + ["--analytical_place"]
    rc = nl.run(cmd_for(binary, matrix.blif_of(design), args), cwd=cwd, stdout=log, timeout=TIMEOUT)
    rec: dict = {"design": design, "tag": tag, "rc": rc, **(meta or {})}
    if rc == 0:
        rec.update(nl.Metrics(log).values)
        text = log.read_text(encoding="utf-8", errors="replace")
        import re
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        if m:
            rec["pack_s"] = float(m.group(1))
        placed = cwd / f"{design}.place"
        if placed.is_file():
            shutil.copyfile(placed, cwd / "final.place")
        rec.update(packing_metrics(design, cwd))
    else:
        rec["error"] = matrix.vpr_error(log) or "VPR exited non-zero"
    nl.write_json(cwd / "metrics.json", rec)
    matrix._clean(cwd, design)
    append(design, rec, record)
    print(f"{design}/{tag}: rc={rc} wl={rec.get('wirelength')} chan={rec.get('chan_width')} "
          f"clbs={rec.get('clbs')} flow_s={rec.get('flow_s')}", flush=True)
    return rec


# ---------------------------------------------------------------------------------------
# control gate

def gate_one(design: str) -> list[dict]:
    """Stock vs Norns .net, absent option and beta 0, in --pack and in the analytical flow."""
    root = Path("/tmp/claude-1000/nr3-gate") / design
    blif = matrix.blif_of(design)
    aff = af.affinity_path(design, "word")
    if not aff.is_file():
        af.write(design, "word")
    rows = []
    variants = {"stock": (nl.VPR, []), "norns-absent": (NORNS_VPR, []),
                "norns-b0": (NORNS_VPR, ["--norns_affinity", str(aff), "--norns_affinity_weight", "0"])}
    for flow, flags in (("pack", ["--pack"]), ("ap", ["--analytical_place"])):
        nets = {}
        for name, (binary, extra) in variants.items():
            cwd = root / f"{flow}-{name}"
            if cwd.exists():
                shutil.rmtree(cwd)
            nl.ensure_dir(cwd)
            rc = nl.run(cmd_for(binary, blif, ["--seed", "1"] + flags + extra), cwd=cwd,
                        stdout=cwd / "vpr.out", timeout=TIMEOUT)
            nets[name] = (rc, cwd / f"{design}.net")
        ref = nets["stock"][1]
        for name in ("norns-absent", "norns-b0"):
            rc, net = nets[name]
            same = bool(nets["stock"][0] == 0 and rc == 0 and ref.is_file() and net.is_file()
                        and filecmp.cmp(ref, net, shallow=False))
            rows.append({"design": design, "flow": flow, "variant": name, "identical": same,
                         "rc_stock": nets["stock"][0], "rc": rc,
                         "net_bytes": ref.stat().st_size if ref.is_file() else None})
            print(f"gate {design} {flow} {name}: identical={same}", flush=True)
        if os.environ.get("NORNS_GATE_KEEP") != "1":
            for name in variants:
                (root / f"{flow}-{name}" / f"{design}.net").unlink(missing_ok=True)
    return rows


def gate(designs: list[str]) -> int:
    path = nl.DATA / "analysis" / "r3-gate.json"
    res = nl.read_json(path) if path.is_file() else {}
    for design in designs:
        res[design] = gate_one(design)
        nl.write_json(path, res)
    ok = all(r["identical"] for rows in res.values() for r in rows)
    print("CONTROL GATE", "PASS" if ok and len(res) == len(nl.DESIGN_ORDER) else "incomplete/fail")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------
# pilot, grid

def pilot(designs: list[str]) -> int:
    for design in designs:
        for source in af.SOURCES:
            if not af.affinity_path(design, source).is_file():
                af.write(design, source)
        vpr_run(design, "pilot-stock", nl.VPR, ["--seed", "1"], route=False, record="r3pilot.jsonl",
                meta={"arm": "pilot-stock"})
        for source in af.SOURCES:
            for beta in BETAS:
                vpr_run(design, f"pilot-{source}-b{beta:g}", NORNS_VPR,
                        ["--seed", "1", "--norns_affinity", str(af.affinity_path(design, source)),
                         "--norns_affinity_weight", f"{beta:g}"], route=False,
                        record="r3pilot.jsonl", meta={"arm": "pilot", "source": source, "beta": beta})
    return 0


def freeze_grid() -> int:
    import statistics
    grid: dict[str, object] = {"rule": "beta_m = largest beta in B with median CLB growth <= 5% over the "
                                       "pilot designs; grid = neighbours in B", "betas": list(BETAS),
                               "pilot_designs": list(PILOT), "sources": {}}
    for source in af.SOURCES:
        growth = {}
        gain = {}
        for beta in BETAS:
            g, p = [], []
            for design in PILOT:
                rs = {r["tag"]: r for r in records(design, "r3pilot.jsonl") if r["rc"] == 0}
                st, ar = rs.get("pilot-stock"), rs.get(f"pilot-{source}-b{beta:g}")
                if not st or not ar:
                    continue
                g.append(ar["clbs"] / st["clbs"] - 1)
                lev = "module" if source == "module" else ("word" if source == "word" else "wordio")
                p.append(ar["purity"][lev]["share"] - st["purity"][lev]["share"])
            growth[beta] = statistics.median(g) if len(g) == len(PILOT) else None
            gain[beta] = statistics.median(p) if len(p) == len(PILOT) else None
        ok = [b for b in BETAS if growth[b] is not None and growth[b] <= 0.05]
        bm = max(ok) if ok else BETAS[0]
        i = BETAS.index(bm)
        lo = min(max(i - 1, 0), len(BETAS) - 3)
        betas = list(BETAS[lo:lo + 3])
        grid["sources"][source] = {"beta_m": bm, "grid": betas, "median_clb_growth": growth,
                                   "median_purity_gain": gain}
        print(source, "beta_m", bm, "grid", betas, "growth", growth)
    nl.write_json(GRID, grid)
    return 0


# ---------------------------------------------------------------------------------------
# Stage-4 arms

def configs() -> list[tuple[str, str, float | None]]:
    grid = nl.read_json(GRID)["sources"]
    out: list[tuple[str, str, float | None]] = [("stock", "stock", None)]
    for source in af.SOURCES:
        for beta in grid[source]["grid"]:
            out.append((f"{source}-b{beta:g}", source, beta))
    return out


def seed_for(design: str, cfg: str, seed: int) -> Path:
    """The round-2 words_partial seed rebuilt on the packing of the analytic run (cfg, seed)."""
    import build_seeds as bs
    import build_word_seeds as bw
    base = r3dir(design, f"{cfg}.analytic.s{seed}")
    out = r3dir(design, f"{cfg}.seed.s{seed}-seed")
    target = out / "words_partial-full.place"
    if target.is_file():
        return target
    real_runs_dir, real_paths = nl.runs_dir, bs.baseline_paths

    def patched(design_: str, *parts: str) -> Path:
        if parts and parts[0] == "seeds":
            return out.joinpath(*parts[1:])
        return real_runs_dir(design_, *parts)

    nl.runs_dir = patched
    bs.baseline_paths = lambda d: (base / "initial.place", base / "final.flat_place", base / "vpr.out")
    try:
        nl.ensure_dir(out)
        bw.build(design, {"words_partial"})
    finally:
        nl.runs_dir, bs.baseline_paths = real_runs_dir, real_paths
    return target


def arm_cmds(design: str, cfg: str, source: str, beta: float | None, seed: int) -> tuple[Path, list[str]]:
    if source == "stock":
        return nl.VPR, ["--seed", str(seed)]
    return NORNS_VPR, ["--seed", str(seed), "--norns_affinity", str(af.affinity_path(design, source)),
                       "--norns_affinity_weight", f"{beta:g}"]


def arms(design: str) -> None:
    for source in af.SOURCES:
        if not af.affinity_path(design, source).is_file():
            af.write(design, source)
    cfgs = configs()
    for start in ("analytic", "seed"):
        for cfg, source, beta in cfgs:
            for seed in SEEDS:
                binary, extra = arm_cmds(design, cfg, source, beta, seed)
                meta = {"arm": cfg, "source": source, "beta": beta, "start": start, "vseed": seed}
                tag = f"{cfg}.{start}.s{seed}"
                if start == "seed":
                    place = seed_for(design, cfg, seed)
                    if not place.is_file():
                        print(f"{design}/{tag}: no seed file")
                        continue
                    extra = extra + ["--read_initial_place_file", str(place)]
                vpr_run(design, tag, binary, extra, meta=meta)


def long_run(design: str) -> bool:
    """Designs whose stock flow exceeds 15 s keep the per-run lock (a design chunk would hold it > 20 min)."""
    base = nl.runs_dir(design, "runs", "baseline", "metrics.json")
    return bool(base.is_file() and float(nl.read_json(base).get("flow_s", 0)) > 15.6)


def chunk(mode: str, designs: list[str]) -> int:
    here = nl.WS / "scripts"
    worst = 0
    for design in designs:
        if long_run(design):
            rc = subprocess.run([sys.executable, str(here / "round3.py"), mode, design]).returncode
        else:
            env = dict(os.environ, NORNS_LOCK_HELD="1")
            rc = subprocess.run(["flock", "-x", str(nl.LOCK), sys.executable, str(here / "round3.py"),
                                 mode, design], env=env).returncode
        print(f"{design}: {mode} chunk rc={rc}", flush=True)
        worst = max(worst, rc)
    return worst


def status() -> int:
    for design in nl.DESIGN_ORDER:
        rs = records(design)
        print(design, len([r for r in rs if r["rc"] == 0]), "ok", len([r for r in rs if r["rc"] != 0]), "failed")
    return 0


def main(argv: list[str]) -> int:
    mode = argv[0]
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    if mode == "chunk":
        return chunk(argv[1], argv[2:] or list(nl.DESIGN_ORDER))
    if mode == "gate":
        return gate(designs)
    if mode == "pilot":
        return pilot(argv[1:] or list(PILOT))
    if mode == "grid":
        return freeze_grid()
    if mode == "arms":
        for d in designs:
            arms(d)
        return 0
    if mode == "status":
        return status()
    nl.die(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
