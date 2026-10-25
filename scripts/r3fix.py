"""Round-3 fix-round runs (pack-only style, no routing; protocol entry 2026-10-25 in docs/plan/round3.md).

  python scripts/r3fix.py ident [design ...]   new vs previous Norns vpr: .net byte-identical and flat placement
                                               identical to the Stage-4 run, 3 sources x beta 4, seed 1
  python scripts/r3fix.py stockn [design ...]  stock arm on the Norns vpr (option absent), 3 VPR seeds, pack time
  python scripts/r3fix.py gate2 [design ...]   beta-0 gate for the module and word+io affinity files (--pack flow)
  python scripts/r3fix.py timing [design ...]  interleaved pack-time runs on the Norns vpr: per design and seed, stock then
                                               module, word, word+io (beta 4) back to back, with timestamps and load
  python scripts/r3fix.py match                affinity-file entries matched to atoms, from the Stage-4 vpr.out logs (no VPR)

Every VPR call takes the heavy lock (round3.cmd_for), one run at a time. Results: data/analysis/r3fix-*.json.
The previous vpr (built before the log counter and the stoi fix) is $NORNS_VPR_OLD (a copy kept outside the repo).
"""

from __future__ import annotations

import filecmp
import os
import re
import shutil
import sys
from pathlib import Path

import affinity as af
import matrix
import nornlib as nl
import round3 as r3

TMP = Path("/tmp/claude-1000/nr3-fix")
OLD = Path(os.environ.get("NORNS_VPR_OLD", str(TMP / "vpr-old")))
OUT = nl.DATA / "analysis"
BETA = 4


def body(path: Path) -> list[str]:
    """Flat placement lines without the comment header (it carries a timestamp)."""
    return [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if not x.startswith("#")]


def pack_seconds(log: Path) -> float | None:
    m = re.search(r"### Packing took ([0-9.]+) seconds", log.read_text(encoding="utf-8", errors="replace"))
    return float(m.group(1)) if m else None


def proposals(log: Path) -> dict | None:
    m = re.search(r"Norns proposals: (\d+) calls, (\d+) with 0 queued, (\d+) molecules attempted, (\d+) queued",
                  log.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return None
    c, z, a, q = (int(x) for x in m.groups())
    return {"calls": c, "calls_zero_queued": z, "attempted": a, "queued": q}


def one(design: str, tag: str, binary: Path, extra: list[str], root: Path) -> tuple[int, Path]:
    cwd = root / design / tag
    if cwd.exists():
        shutil.rmtree(cwd)
    nl.ensure_dir(cwd)
    rc = nl.run(r3.cmd_for(binary, matrix.blif_of(design), extra), cwd=cwd, stdout=cwd / "vpr.out",
                timeout=4 * r3.TIMEOUT)
    return rc, cwd


def load(name: str) -> dict:
    p = OUT / name
    return nl.read_json(p) if p.is_file() else {}


def ident(designs: list[str]) -> int:
    res = load("r3fix-ident.json")
    for design in designs:
        rows = []
        for source in af.SOURCES:
            cfg = f"{source}-b{BETA}"
            aff = af.affinity_path(design, source)
            if not aff.is_file():
                af.write(design, source)
            args = ["--seed", "1", "--analytical_place", "--norns_affinity", str(aff),
                    "--norns_affinity_weight", str(BETA)]
            rc_o, cwd_o = one(design, f"{cfg}-old", OLD, args + ["--write_flat_place", "flat.place"], TMP / "ident")
            rc_n, cwd_n = one(design, f"{cfg}-new", r3.NORNS_VPR, args + ["--write_flat_place", "flat.place"],
                              TMP / "ident")
            net_o, net_n = cwd_o / f"{design}.net", cwd_n / f"{design}.net"
            same_net = bool(rc_o == 0 and rc_n == 0 and net_o.is_file() and net_n.is_file()
                            and filecmp.cmp(net_o, net_n, shallow=False))
            ref = r3.r3dir(design, f"{cfg}.analytic.s1") / "final.flat_place"
            same_flat = bool(rc_n == 0 and ref.is_file() and body(ref) == body(cwd_n / "flat.place"))
            row = {"design": design, "cfg": cfg, "rc_old": rc_o, "rc_new": rc_n, "net_identical_old_new": same_net,
                   "flat_identical_stage4": same_flat, "net_bytes": net_n.stat().st_size if net_n.is_file() else None,
                   "pack_s_new": pack_seconds(cwd_n / "vpr.out") if rc_n == 0 else None,
                   "pack_s_old": pack_seconds(cwd_o / "vpr.out") if rc_o == 0 else None,
                   "proposals": proposals(cwd_n / "vpr.out") if rc_n == 0 else None}
            rows.append(row)
            print(f"ident {design} {cfg}: net={same_net} flat_vs_stage4={same_flat} proposals={row['proposals']}",
                  flush=True)
            for c in (cwd_o, cwd_n):
                for f in c.glob("*.net"):
                    f.unlink()
        res[design] = rows
        nl.write_json(OUT / "r3fix-ident.json", res)
    ok = all(r["net_identical_old_new"] and r["flat_identical_stage4"] for rows in res.values() for r in rows)
    print("IDENT", "PASS" if ok else "FAIL", sum(len(r) for r in res.values()), "configs")
    return 0 if ok else 1


def stockn(designs: list[str]) -> int:
    res = load("r3fix-stockn.json")
    for design in designs:
        rows = []
        for seed in r3.SEEDS:
            rc, cwd = one(design, f"stock-s{seed}", r3.NORNS_VPR,
                          ["--seed", str(seed), "--analytical_place", "--write_flat_place", "flat.place"],
                          TMP / "stockn")
            ref = r3.r3dir(design, f"stock.analytic.s{seed}") / "final.flat_place"
            same = bool(rc == 0 and ref.is_file() and body(ref) == body(cwd / "flat.place"))
            rows.append({"design": design, "seed": seed, "rc": rc, "pack_s": pack_seconds(cwd / "vpr.out") if rc == 0 else None,
                         "flat_identical_stage4_stock": same})
            print(f"stockn {design} s{seed}: pack_s={rows[-1]['pack_s']} flat_same={same}", flush=True)
            for f in cwd.glob("*.net"):
                f.unlink()
        res[design] = rows
        nl.write_json(OUT / "r3fix-stockn.json", res)
    return 0


def gate2(designs: list[str]) -> int:
    res = load("r3fix-gate2.json")
    for design in designs:
        rc_s, cwd_s = one(design, "stock", nl.VPR, ["--seed", "1", "--pack"], TMP / "gate2")
        rows = []
        for source in ("module", "wordio"):
            aff = af.affinity_path(design, source)
            if not aff.is_file():
                af.write(design, source)
            rc, cwd = one(design, f"norns-{source}-b0", r3.NORNS_VPR,
                          ["--seed", "1", "--pack", "--norns_affinity", str(aff), "--norns_affinity_weight", "0"],
                          TMP / "gate2")
            a, b = cwd_s / f"{design}.net", cwd / f"{design}.net"
            same = bool(rc_s == 0 and rc == 0 and a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False))
            rows.append({"design": design, "source": source, "identical": same, "rc_stock": rc_s, "rc": rc,
                         "net_bytes": a.stat().st_size if a.is_file() else None})
            print(f"gate2 {design} {source}: identical={same}", flush=True)
            b.unlink(missing_ok=True)
        (cwd_s / f"{design}.net").unlink(missing_ok=True)
        res[design] = rows
        nl.write_json(OUT / "r3fix-gate2.json", res)
    ok = all(r["identical"] for rows in res.values() for r in rows)
    print("GATE2", "PASS" if ok and len(res) == len(nl.DESIGN_ORDER) else "incomplete/fail")
    return 0 if ok else 1


def timing(designs: list[str]) -> int:
    """Stock and Norns arms on the same binary, back to back per design and seed, so a concurrent load
    (another lane running outside the lock) affects both arms alike. Records wall-clock window and loadavg."""
    import datetime
    res = load("r3fix-timing.json")
    for design in designs:
        rows = []
        for seed in r3.SEEDS:
            for arm in ("stock",) + tuple(f"{x}-b{BETA}" for x in af.SOURCES):
                extra = ["--seed", str(seed), "--analytical_place", "--write_flat_place", "flat.place"]
                if arm != "stock":
                    src = arm.split("-b")[0]
                    aff = af.affinity_path(design, src)
                    extra += ["--norns_affinity", str(aff), "--norns_affinity_weight", str(BETA)]
                t0 = datetime.datetime.now().isoformat(timespec="seconds")
                load1 = os.getloadavg()[0]
                rc, cwd = one(design, f"{arm}-s{seed}", r3.NORNS_VPR, extra, TMP / "timing")
                rows.append({"design": design, "seed": seed, "arm": arm, "rc": rc, "start": t0, "load1": load1,
                             "pack_s": pack_seconds(cwd / "vpr.out") if rc == 0 else None})
                print(f"timing {design} s{seed} {arm}: pack_s={rows[-1]['pack_s']} load1={load1:.1f}", flush=True)
                for f in cwd.glob("*.net"):
                    f.unlink()
        res[design] = rows
        nl.write_json(OUT / "r3fix-timing.json", res)
    return 0


def match(designs: list[str]) -> int:
    """Matched / total file entries per design and source, from the Stage-4 headline-config logs (beta 4, seed 1)."""
    res: dict = {}
    for design in designs:
        res[design] = {}
        for source in af.SOURCES:
            log = r3.r3dir(design, f"{source}-b{BETA}.analytic.s1") / "vpr.out"
            m = re.search(r"Norns affinity: (\d+) of (\d+) file entries matched atoms, (\d+) groups",
                          log.read_text(encoding="utf-8", errors="replace"))
            res[design][source] = {"matched": int(m.group(1)), "entries": int(m.group(2)), "groups": int(m.group(3))}
    nl.write_json(OUT / "r3fix-match.json", res)
    return 0


def main(argv: list[str]) -> int:
    mode = argv[0]
    designs = argv[1:] or list(nl.DESIGN_ORDER)
    fn = {"ident": ident, "stockn": stockn, "gate2": gate2, "match": match, "timing": timing}.get(mode)
    if fn is None:
        nl.die(f"unknown mode {mode}")
    return fn(designs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
