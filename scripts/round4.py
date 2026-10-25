"""Round 4 runs (VPR, one at a time under the heavy lock; protocol: docs/plan/round4.md).

  python scripts/round4.py gate [design ...]      Stage-1 gates (a) (b) (c) -> data/analysis/r4-gate.json
  python scripts/round4.py join [design ...]      affinity join: matched fraction per design and source,
                                                  round-3 files against round-4 files -> data/analysis/r4-join.json
  python scripts/round4.py census [design ...]    Stage-2 pack-and-place runs with the census (stock, r3, r4)
  python scripts/round4.py arms [design ...]      Stage-2b/5 arms with timing reports
  python scripts/round4.py status

The stock arm runs the stock vpr ($VPR); Norns arms run $NORNS_VPR. Gate scratch: /tmp/claude-1000/nr4-gate/.
"""

from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import sys
from pathlib import Path

import affinity as af
import matrix
import nornlib as nl
import round3 as r3

TMP = Path("/tmp/claude-1000/nr4-gate")
OLD_VPR = Path(os.environ.get("NORNS_VPR_R3", "/tmp/claude-1000/nr4-w/vpr-r3"))
NORNS_VPR = r3.NORNS_VPR
BETA = 4.0
SOURCE = "word"
TIMEOUT = 7200
MATCH = re.compile(r"Norns affinity: (\d+) of (\d+) file entries matched atoms, (\d+) groups")


def vrun(binary: Path, design: str, cwd: Path, flags: list[str], log_name: str = "vpr.out") -> int:
    if cwd.exists():
        shutil.rmtree(cwd)
    nl.ensure_dir(cwd)
    return nl.run(r3.cmd_for(binary, matrix.blif_of(design), flags), cwd=cwd, stdout=cwd / log_name,
                  timeout=TIMEOUT)


def same(a: Path, b: Path) -> bool:
    """Byte comparison; for a flat placement the `#` header lines (they carry a creation time) are skipped."""
    if not (a.is_file() and b.is_file()):
        return False
    if a.name.endswith("flat_place"):
        def body(p: Path) -> list[str]:
            return [x for x in p.read_text(errors="replace").splitlines() if not x.startswith("#")]
        return body(a) == body(b)
    return filecmp.cmp(a, b, shallow=False)


def aff_args(design: str, source: str, beta: float, rnd: str) -> list[str]:
    return ["--norns_affinity", str(af.affinity_path(design, source, rnd)),
            "--norns_affinity_weight", f"{beta:g}"]


def matched(log: Path) -> tuple[int, int] | None:
    m = MATCH.search(log.read_text(errors="replace"))
    return (int(m.group(1)), int(m.group(2))) if m else None


# ---------------------------------------------------------------------------------------
# Stage-1 gates

def ensure_affinity(design: str) -> None:
    for source in af.SOURCES:
        if not af.affinity_path(design, source, "r4").is_file():
            af.write(design, source, "r4")


def gate_one(design: str) -> list[dict]:
    """Gates (a), (b), (c) of docs/plan/round4.md for one design, seed 1."""
    ensure_affinity(design)
    root = TMP / design
    rows: list[dict] = []

    def rec(gate: str, flow: str, variant: str, ref: Path, other: Path, rc_ref: int, rc: int,
            extra: dict | None = None) -> None:
        ok = rc_ref == 0 and rc == 0 and same(ref, other)
        rows.append({"design": design, "gate": gate, "flow": flow, "variant": variant, "identical": ok,
                     "rc_ref": rc_ref, "rc": rc, **(extra or {})})
        print(f"gate {gate} {design} {flow} {variant}: identical={ok}", flush=True)

    net = f"{design}.net"
    head_args = aff_args(design, SOURCE, BETA, "r4")
    for flow, fl in (("pack", ["--pack"]), ("ap", ["--analytical_place"])):
        base = ["--seed", "1"] + fl
        census = lambda tag: ["--norns_pack_census", str(root / f"{flow}-{tag}" / "census.tsv")]  # noqa: E731
        d = {t: root / f"{flow}-{t}" for t in ("stock", "absent", "b0", "stock-census", "head", "head-census")}
        rc = {}
        rc["stock"] = vrun(nl.VPR, design, d["stock"], base)
        rc["absent"] = vrun(NORNS_VPR, design, d["absent"], base)
        if flow == "pack":
            rc["b0"] = vrun(NORNS_VPR, design, d["b0"], base + aff_args(design, SOURCE, 0, "r4"))
        rc["stock-census"] = vrun(NORNS_VPR, design, d["stock-census"], base + census("stock-census"))
        rc["head"] = vrun(NORNS_VPR, design, d["head"], base + head_args)
        rc["head-census"] = vrun(NORNS_VPR, design, d["head-census"], base + head_args + census("head-census"))
        if flow == "pack":  # (a): stock against the Norns binary, option absent and beta 0
            for v in ("absent", "b0"):
                rec("a", flow, v, d["stock"] / net, d[v] / net, rc["stock"], rc[v])
        # (b): census on against off, for the stock arm and the headline arm
        rec("b", flow, "stock-census", d["absent"] / net, d["stock-census"] / net, rc["absent"], rc["stock-census"])
        rec("b", flow, "head-census", d["head"] / net, d["head-census"] / net, rc["head"], rc["head-census"])
        # the census must have written something
        c = d["head-census"] / "census.tsv"
        rows[-1]["census_bytes"] = c.stat().st_size if c.is_file() else 0
        if flow == "ap":
            for t in ("stock", "stock-census", "head-census"):
                (d[t] / net).unlink(missing_ok=True)
    # (c): proposal count 'attempted' against the previous (round-3 fix) binary, 3 sources, beta 4, AP flow
    for source in af.SOURCES:
        args = ["--seed", "1", "--analytical_place", "--write_flat_place", "FLAT"] + aff_args(design, source, BETA, "r3")
        dold, dnew = root / f"c-old-{source}", root / f"c-new-{source}"
        fl_old = [str(dold / "final.flat_place") if a == "FLAT" else a for a in args]
        fl_new = [str(dnew / "final.flat_place") if a == "FLAT" else a for a in args]
        rco = vrun(OLD_VPR, design, dold, fl_old)
        rcn = vrun(NORNS_VPR, design, dnew, fl_new + ["--norns_proposal_count", "attempted"])
        rec("c", "ap", f"{source}-net", dold / net, dnew / net, rco, rcn)
        rec("c", "ap", f"{source}-flat", dold / "final.flat_place", dnew / "final.flat_place", rco, rcn)
        # information, not a gate: the round-4 affinity file (absorbed buffers, swept dead logic dropped, adders
        # named after their cout net) against the round-3 file, with the same binary and flags
        dfix = root / f"c-fix-{source}"
        args4 = ["--seed", "1", "--analytical_place"] + aff_args(design, source, BETA, "r4") + \
            ["--norns_proposal_count", "attempted"]
        rcf = vrun(NORNS_VPR, design, dfix, args4)
        info_same = rcf == 0 and rco == 0 and same(dold / net, dfix / net)
        rows.append({"design": design, "gate": "info", "flow": "ap", "variant": f"{source}-r4file-vs-r3file",
                     "identical": True, "same_packing": info_same, "rc_ref": rco, "rc": rcf})
        print(f"info {design} {source}: round-4 affinity file packs like round 3's: {info_same}", flush=True)
        shutil.rmtree(dold, ignore_errors=True)
        shutil.rmtree(dnew, ignore_errors=True)
        shutil.rmtree(dfix, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)
    return rows


GATE = nl.DATA / "analysis" / "r4-gate.json"


def gate(designs: list[str]) -> int:
    res = nl.read_json(GATE) if GATE.is_file() else {}
    for design in designs:
        if design in res and all(r["identical"] for r in res[design]) and len(res[design]) >= 15:
            continue
        res[design] = gate_one(design)
        nl.write_json(GATE, res)
    ok = all(r["identical"] for rows in res.values() for r in rows)
    n = sum(len(rows) for rows in res.values())
    print("STAGE-1 GATES", "PASS" if ok and len(res) == len(nl.DESIGN_ORDER) else "incomplete/fail",
          f"{sum(r['identical'] for rows in res.values() for r in rows)} of {n} comparisons identical")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------
# affinity join (Stage 1, item 2)

JOIN = nl.DATA / "analysis" / "r4-join.json"


def join(designs: list[str]) -> int:
    """Matched fraction per design and source: the round-3 files (r3) against the round-4 files (r4)."""
    res = nl.read_json(JOIN) if JOIN.is_file() else {}
    for design in designs:
        ensure_affinity(design)
        res[design] = {}
        for source in af.SOURCES:
            res[design][source] = {}
            for rnd in ("r3", "r4"):
                d = TMP / "join" / design
                rc = vrun(NORNS_VPR, design, d, ["--seed", "1", "--pack"] + aff_args(design, source, 0, rnd))
                m = matched(d / "vpr.out")
                res[design][source][rnd] = {"matched": m[0], "entries": m[1]} if m else None
                if rc != 0 or not m:
                    print(f"join {design} {source} {rnd}: rc={rc} no match line", flush=True)
                shutil.rmtree(d, ignore_errors=True)
            print(f"join {design} {source}: {res[design][source]}", flush=True)
        nl.write_json(JOIN, res)
    return 0


# ---------------------------------------------------------------------------------------
# Stage 2: census runs (pack and place, no route, seed 1)

CENSUS_ARMS = {
    "stock": ("stock", None, []),
    "r3": ("word", BETA, ["--norns_proposal_count", "attempted"]),
    "r4": ("word", BETA, ["--norns_proposal_count", "queued"]),
}


def sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def census_run(design: str, arm: str) -> dict:
    source, beta, extra = CENSUS_ARMS[arm]
    cwd = nl.runs_dir(design, "r4", f"census-{arm}")
    mpath = cwd / "metrics.json"
    if mpath.is_file() and nl.read_json(mpath).get("rc") == 0:
        return nl.read_json(mpath)
    flags = ["--seed", "1", "--analytical_place", "--write_flat_place", str(cwd / "final.flat_place"),
             "--norns_pack_census", str(cwd / "census.tsv")]
    if source != "stock":
        flags += aff_args(design, source, beta, "r4")
    rc = vrun(NORNS_VPR, design, cwd, flags + extra)
    rec: dict = {"design": design, "arm": arm, "rc": rc, "source": source, "beta": beta}
    if rc == 0:
        log = cwd / "vpr.out"
        rec.update(nl.Metrics(log).values)
        text = log.read_text(errors="replace")
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        if m:
            rec["pack_s"] = float(m.group(1))
        mm = matched(log)
        rec["affinity_matched"] = list(mm) if mm else None
        net = cwd / f"{design}.net"
        rec["net_sha256"] = sha256(net) if net.is_file() else None
        net.unlink(missing_ok=True)
        rec["census_bytes"] = (cwd / "census.tsv").stat().st_size
    else:
        rec["error"] = matrix.vpr_error(cwd / "vpr.out")
    nl.write_json(mpath, rec)
    print(f"census {design} {arm}: rc={rc} pack_s={rec.get('pack_s')} bytes={rec.get('census_bytes')}", flush=True)
    return rec


def census(designs: list[str]) -> int:
    for design in designs:
        ensure_affinity(design)
        for arm in CENSUS_ARMS:
            census_run(design, arm)
    return 0


# ---------------------------------------------------------------------------------------
# Stage 2b / 5: arms with routing and the timing report

PACKS = {"stock": ("stock", None), "norns": (SOURCE, BETA)}
STARTS = ("analytic", "wordseed", "stagebit")
SEEDS = (1, 2, 3)
NPATHS = 1000
KEEP = ("vpr.out", "metrics.json", "initial.place", "final.flat_place", "final.place", "report_timing.setup.rpt",
        "paths.json.gz", "attr.json", "stagebit.info.json")
RECORDS = "r4runs.jsonl"


def r4dir(design: str, tag: str) -> Path:
    return nl.runs_dir(design, "r4", tag)


def records(design: str, name: str = RECORDS) -> list[dict]:
    path = nl.DATA / design / name
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def is_done(design: str, tag: str) -> bool:
    p = r4dir(design, tag) / "metrics.json"
    return p.is_file() and nl.read_json(p).get("rc") == 0


def wordseed_for(design: str, base: Path, out: Path) -> Path:
    """The round-2 words_partial seed rebuilt on the packing of the analytic run in `base` (as round 3)."""
    import build_seeds as bs
    import build_word_seeds as bw
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


def attribute_run(design: str, cwd: Path) -> dict:
    """Odin III attribution of the routed run (scripts/timing4.py workaround); keeps the compact paths."""
    import gzip

    import timing4
    blif = matrix.blif_of(design)
    rep = timing4.attribute(cwd, blif, netlist_json=timing4.ensure_json(design))
    paths = [{"index": p["index"], "slack": p["slack_ns"], "arrival": p["arrival_ns"],
              "nodes": [[n["atom"], n["block_type"], n["category"], n["span"], n["word"], n["delay_ns"]]
                        for n in p["nodes"]]} for p in rep["paths"]]
    with gzip.open(cwd / "paths.json.gz", "wt") as fh:
        json.dump(paths, fh)
    slim = {k: v for k, v in rep.items() if k != "paths"}
    nl.write_json(cwd / "attr.json", slim)
    return {"attr_cpd_ns": rep["timing"]["cpd_ns"], "paths_in_report": rep["timing"]["paths_in_report"],
            "paths_skipped": rep["timing"]["paths_skipped"], "matched_share": rep["coverage"]["matched_share"],
            "matched_share_excl_port": rep["coverage"]["matched_share_excl_port"],
            "critical_matched_delay_share": rep["coverage"]["critical_matched_delay_share"],
            "worst_slack_ns": rep["timing"]["worst_slack_ns"]}


def arm_run(design: str, pack: str, start: str, seed: int) -> dict | None:
    tag = f"{pack}.{start}.s{seed}"
    if is_done(design, tag):
        return nl.read_json(r4dir(design, tag) / "metrics.json")
    cwd = r4dir(design, tag)
    source, beta = PACKS[pack]
    extra: list[str] = []
    meta: dict = {"design": design, "tag": tag, "pack": pack, "start": start, "vseed": seed}
    if start != "analytic":
        base = r4dir(design, f"{pack}.analytic.s{seed}")
        if not is_done(design, f"{pack}.analytic.s{seed}"):
            print(f"{design}/{tag}: base run missing", flush=True)
            return None
        sdir = r4dir(design, f"{tag}-seed")
        if start == "wordseed":
            place = wordseed_for(design, base, sdir)
        else:
            import r4stage
            nl.ensure_dir(sdir)
            place = sdir / "stagebit.place"
            info = r4stage.build(design, base, place)
            nl.write_json(sdir / "stagebit.info.json", info)
            meta["stagebit"] = info
            if info.get("status") != "ok":
                print(f"{design}/{tag}: {info.get('status')}", flush=True)
                return None
        if not place.is_file():
            print(f"{design}/{tag}: no seed file", flush=True)
            return None
        extra = ["--read_initial_place_file", str(place)]
    if cwd.exists():
        shutil.rmtree(cwd)
    nl.ensure_dir(cwd)
    flags = ["--seed", str(seed), "--timing_report_npaths", str(NPATHS),
             "--write_initial_place_file", str(cwd / "initial.place"),
             "--write_flat_place", str(cwd / "final.flat_place")] + extra
    binary = nl.VPR
    if source != "stock":
        binary = NORNS_VPR
        flags += aff_args(design, source, beta, "r4")
    rc = nl.run(r3.cmd_for(binary, matrix.blif_of(design), flags), cwd=cwd, stdout=cwd / "vpr.out", timeout=TIMEOUT)
    rec: dict = {**meta, "rc": rc}
    if rc == 0:
        log = cwd / "vpr.out"
        rec.update(nl.Metrics(log).values)
        text = log.read_text(errors="replace")
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        if m:
            rec["pack_s"] = float(m.group(1))
        net = cwd / f"{design}.net"
        rec["net_sha256"] = sha256(net) if net.is_file() else None
        placed = cwd / f"{design}.place"
        if placed.is_file():
            shutil.copyfile(placed, cwd / "final.place")
        rec.update(r3.packing_metrics(design, cwd))
        util = re.findall(r"Device Utilization: ([0-9.]+) \(target", text)
        rec["device_utilization"] = float(util[-1]) if util else None
        try:
            rec.update(attribute_run(design, cwd))
        except Exception as exc:  # noqa: BLE001 - recorded, the run itself is fine
            rec["attr_error"] = f"{type(exc).__name__}: {exc}"
    else:
        rec["error"] = matrix.vpr_error(cwd / "vpr.out")
    for f in list(cwd.iterdir()):
        if f.name not in KEEP:
            f.unlink() if f.is_file() else shutil.rmtree(f, ignore_errors=True)
    nl.write_json(cwd / "metrics.json", rec)
    with (nl.DATA / design / RECORDS).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{design}/{tag}: rc={rc} wl={rec.get('wirelength')} W={rec.get('chan_width')} cpd={rec.get('cpd_ns')} "
          f"flow_s={rec.get('flow_s')}", flush=True)
    return rec


def arms(designs: list[str], stage: str) -> int:
    """stage 2b: the analytic start of both packings; stage 5: the other starts."""
    for design in designs:
        ensure_affinity(design)
        starts = ("analytic",) if stage == "2b" else ("wordseed", "stagebit")
        for start in starts:
            for pack in PACKS:
                for seed in SEEDS:
                    arm_run(design, pack, start, seed)
    return 0


def main(argv: list[str]) -> int:
    mode = argv[0]
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    if mode == "gate":
        return gate(designs)
    if mode == "join":
        return join(designs)
    if mode == "census":
        return census(designs)
    if mode == "arms":
        return arms(argv[2:] or list(nl.DESIGN_ORDER), argv[1])
    nl.die(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
