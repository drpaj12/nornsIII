"""Round-7 driver (protocol: docs/plan/round7.md). One VPR at a time under the heavy lock, the lock taken per run.

  python scripts/r7.py stock [design ...]      the 10 stock runs per design (census on)
  python scripts/r7.py hind [design ...]       stock if missing, then the hindsight rounds h1..h5 (and `known` for n5_ designs)
  python scripts/r7.py status

Designs default to the calibration set, then the main set (smallest first). Raw VPR working directories live in a scratch
directory (path in runs/r7/scratch_path.txt); runs/r7/<design>/<arm>.s<seed>/ gets the kept files. Nothing is deleted.
"""

from __future__ import annotations

import gzip
import json
import re
import os
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

import nornlib as nl
import r7lib as lib

TIMEOUT = 7200
NORNS_VPR = Path(os.environ.get("NORNS_VPR", ""))
VPR_ARGS_NOTE = "--seed s --timing_report_npaths 200 --route_file /dev/null"


def scratch_root() -> Path:
    p = lib.R7 / "scratch_path.txt"
    if p.is_file():
        root = Path(p.read_text().strip())
        if root.is_dir():
            return root
    nl.ensure_dir(lib.R7)
    root = Path(tempfile.mkdtemp(prefix="nr7-", dir="/tmp/claude-1000"))
    p.write_text(str(root) + "\n", encoding="utf-8")
    return root


def blif_of(design: str) -> Path:
    return nl.runs_dir(design, "netlist", f"{design}.blif")


def parse_census_pins(census: Path) -> dict[str, dict[str, float]]:
    """atom -> net -> pack-time criticality, from the latest closed `P` records of an atom (as r4census.Census)."""
    latest: dict[str, int] = {}
    crit: dict[str, dict[str, float]] = {}
    with census.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("P\t"):
                continue
            f = line.rstrip("\n").split("\t")
            cseq, atom, net, c = int(f[1]), f[2], f[3], float(f[4])
            if latest.get(atom, 0) <= cseq:
                if latest.get(atom) != cseq:
                    crit[atom] = {}
                latest[atom] = cseq
                crit[atom][net] = max(c, crit[atom].get(net, 0.0))
    return crit


def gz_copy(src: Path, dst: Path) -> None:
    nl.ensure_dir(dst.parent)
    with src.open("rb") as fi, gzip.open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def run_arm(design: str, arm: str, seed: int, aff: Path | None = None, census: bool = False) -> dict:
    done = lib.read_metrics(design, arm, seed)
    if done is not None and done.get("rc") == 0:
        return done
    rd = lib.run_dir(design, arm, seed)
    sc = scratch_root() / design / f"{arm}.s{seed}"
    nl.ensure_dir(sc)
    nl.ensure_dir(rd)
    flags = ["--seed", str(seed), "--timing_report_npaths", str(lib.NPATHS), "--route_file", "/dev/null",
             "--write_initial_place_file", str(sc / "initial.place"), "--write_flat_place", str(sc / "final.flat_place")]
    if census:
        flags += ["--norns_pack_census", str(sc / "census.tsv")]
    if aff is not None:
        flags += ["--norns_affinity", str(aff), "--norns_affinity_weight", f"{lib.AFF_BETA:g}",
                  "--norns_proposal_count", "queued"]
    cmd = ["flock", "-x", str(nl.LOCK), str(NORNS_VPR), str(nl.ARCH), str(blif_of(design))] + flags
    rc = nl.run(cmd, cwd=sc, stdout=sc / "vpr.out", timeout=TIMEOUT)
    rec: dict = {"design": design, "arm": arm, "seed": seed, "rc": rc, "aff": aff.name if aff else None}
    if rc == 0:
        log = sc / "vpr.out"
        text = log.read_text(errors="replace")
        rec.update(nl.Metrics(log).values)
        for k in ("curve", "init_t"):
            rec.pop(k, None)
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        rec["pack_s"] = float(m.group(1)) if m else None
        m = re.search(r"The entire flow of VPR took [0-9.]+ seconds \(max_rss ([0-9.]+) MiB", text)
        rec["max_rss_mib"] = float(m.group(1)) if m else None
        m = re.search(r"Norns affinity: (\d+) of (\d+) file entries matched atoms, (\d+) groups", text)
        rec["affinity_matched"] = [int(x) for x in m.groups()] if m else None
        place = sc / f"{design}.place"
        rec["grid"] = list(nl.grid_size(nl.Place(place)))
        shutil.copy(place, rd / f"{design}.place")
        shutil.copy(sc / "final.flat_place", rd / "final.flat_place")
        shutil.copy(sc / "initial.place", rd / "initial.place")
        shutil.copy(log, rd / "vpr.out")
        gz_copy(sc / f"{design}.net", rd / f"{design}.net.gz")
        import r3lib
        groups = r3lib.logic_groups(rd / "final.flat_place")
        rec["logic_clbs"] = len(groups)
        paths = lib.parse_report(sc / "report_timing.setup.rpt")
        rec["paths_in_report"] = len(paths)
        with gzip.open(rd / "paths.json.gz", "wt") as fh:
            json.dump([{"arrival": p["arrival"], "slack": p["slack"], "nodes": p["nodes"]} for p in paths], fh)
        if census and (sc / "census.tsv").is_file():
            pins = parse_census_pins(sc / "census.tsv")
            with gzip.open(rd / "pincrit.tsv.gz", "wt") as fh:
                for atom, d in sorted(pins.items()):
                    for net, c in sorted(d.items()):
                        fh.write(f"{atom}\t{net}\t{c}\n")
        rec["objective"] = lib.objective(rec)
    else:
        rec["error"] = (text_tail(sc / "vpr.out"))
    nl.write_json(rd / "metrics.json", rec)
    lib.jsonl_append(lib.R7 / "runs.jsonl", rec)
    print(f"{design}/{arm}.s{seed}: rc={rc} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} W={rec.get('chan_width')} "
          f"clbs={rec.get('logic_clbs')} flow_s={rec.get('flow_s')}", flush=True)
    return rec


def text_tail(p: Path, n: int = 400) -> str:
    try:
        return p.read_text(errors="replace")[-n:]
    except OSError:
        return ""


def arm_runs(design: str, arm: str, aff: Path | None, census: bool = False) -> list[dict]:
    return [run_arm(design, arm, s, aff, census) for s in lib.SEEDS]


def ok_runs(design: str, arm: str) -> list[dict]:
    out = []
    for s in lib.SEEDS:
        m = lib.read_metrics(design, arm, s)
        if m and m.get("rc") == 0:
            out.append(m)
    return out


def best(runs: list[dict]) -> dict:
    return min(runs, key=lambda m: (m["objective"], m["seed"]))


def median_obj(runs: list[dict]) -> float:
    return statistics.median(m["objective"] for m in runs)


def source_pcrit(design: str, arm: str, seed: int) -> dict[str, float]:
    with gzip.open(lib.run_dir(design, arm, seed) / "paths.json.gz", "rt") as fh:
        paths = json.load(fh)
    pc, _sl, _cpd = lib.path_crit(paths)
    return pc


def hindsight(design: str) -> dict:
    """Stage 2 for one design: stock (if missing) then rounds h1..h5; writes runs/r7/<d>/rounds.json."""
    out_path = lib.R7 / design / "rounds.json"
    arm_runs(design, "stock", None, census=True)
    stock = ok_runs(design, "stock")
    rec: dict = {"design": design, "stock_ok": len(stock), "rounds": [], "stopped": None}
    if len(stock) < 8:
        rec["stopped"] = "fewer than 8 stock runs"
        nl.write_json(out_path, rec)
        return rec
    if design.startswith("n5_"):
        import affinity as af
        import r5lib as rl
        rl.write_known_affinity(design)
        arm_runs(design, "known", af.affinity_path(design, "known", "r5"))
    view = lib.NetView(design)
    atoms = set(view.kind)
    medians = {"stock": median_obj(stock)}
    src = best(stock)
    src_arm = "stock"
    for k in range(1, lib.MAX_ROUNDS + 1):
        arm = f"h{k}"
        aff = lib.R7 / design / f"{arm}.affinity.tsv"
        stats_path = lib.R7 / design / f"{arm}.recluster.json"
        flat_path = lib.run_dir(design, src_arm, src["seed"]) / "final.flat_place"
        if aff.is_file() and stats_path.is_file():
            stats = nl.read_json(stats_path)
        else:
            flat = nl.Flat(flat_path)
            group, stats = lib.recluster(view, flat, source_pcrit(design, src_arm, src["seed"]))
            stats.update({"source_arm": src_arm, "source_seed": src["seed"]})
            lib.write_affinity(aff, group)
            nl.write_json(stats_path, stats)
            print(f"{design} {arm}: recluster {stats}", flush=True)
        runs = arm_runs(design, arm, aff)
        ok = [m for m in runs if m.get("rc") == 0]
        r: dict = {"arm": arm, "ok": len(ok), "recluster": stats}
        if len(ok) < 8:
            r["note"] = "fewer than 8 runs"
            rec["rounds"].append(r)
            rec["stopped"] = f"{arm}: fewer than 8 runs"
            break
        b = best(ok)
        real = lib.realised_groups(lib.run_dir(design, arm, b["seed"]) / "final.flat_place", atoms)
        tgt = {a: i for a, i in lib.read_aff(aff).items() if a in atoms}
        r["fidelity"] = lib.fidelity(tgt, real)
        r["median_objective"] = median_obj(ok)
        r["best_seed"] = b["seed"]
        rec["rounds"].append(r)
        prev = min(medians.values())
        medians[arm] = r["median_objective"]
        nl.write_json(out_path, rec)
        print(f"{design} {arm}: median obj {r['median_objective']:.1f} vs best earlier {prev:.1f}, fidelity {r['fidelity']['share']:.3f}", flush=True)
        if r["median_objective"] > (1.0 - lib.STOP_GAIN) * prev:
            rec["stopped"] = f"{arm}: median objective not >= 1% below the best earlier arm"
            break
        src, src_arm = b, arm
    else:
        rec["stopped"] = "K = 5 rounds"
    rec["medians"] = medians
    rec["hindsight_arm"] = min(medians, key=lambda a: medians[a])
    nl.write_json(out_path, rec)
    return rec


def default_designs() -> list[str]:
    return list(lib.CALIB) + list(lib.MAIN)


def status() -> int:
    p = lib.R7 / "runs.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []
    print(f"runs logged: {len(rows)}, failed: {sum(1 for r in rows if r['rc'] != 0)}")
    for d in default_designs():
        rp = lib.R7 / d / "rounds.json"
        if rp.is_file():
            r = nl.read_json(rp)
            print(d, r.get("hindsight_arm"), r.get("stopped"))
    return 0


def main(argv: list[str]) -> int:
    mode, designs = argv[0], argv[1:] or default_designs()
    if mode == "status":
        return status()
    for d in designs:
        if mode == "stock":
            arm_runs(d, "stock", None, census=True)
        elif mode == "hind":
            hindsight(d)
        else:
            nl.die(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
