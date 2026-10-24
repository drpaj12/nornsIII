"""The run matrix: baseline, seeded arms, and the cold-start crossover sweep.

One VPR run at a time under flock /tmp/claude-1000/odin3-heavy.lock. Each run's log, final
placement and metrics are kept under runs/<design>/<arm>/<tag>/ and appended to
data/<design>/runs.jsonl, so a continuation lane resumes by re-running the same subcommand.

Arms per design:
  baseline            unseeded, VPR defaults (also dumps initial.place / flat placements)
  soft-<seed>-<var>   --read_initial_place_file seeds/<seed>-<var>.place  (var: full|inter)
  hard-<seed>         --read_vpr_constraints seeds/<seed>-hard.xml
  cold-<scale>        cold start from P*, best final placement, --anneal_auto_init_t_scale
  unseeded-<scale>    unseeded at the same auto-temperature scale
  hot-<seed>          seed's final placement at the hot scale vs unseeded at the same scale

Usage:
  python scripts/matrix.py baseline [design ...]
  python scripts/matrix.py seeds [design ...] [--seeds a,b] [--variants full,inter,hard]
  python scripts/matrix.py crossover [design ...] [--scales 1,2,4,8,16]
  python scripts/matrix.py report
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import nornlib as nl


def record_path(design: str) -> Path:
    return nl.DATA / design / "runs.jsonl"


def append_record(design: str, rec: dict[str, object]) -> None:
    path = record_path(design)
    nl.ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def load_records(design: str) -> list[dict[str, object]]:
    path = record_path(design)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def done(design: str, tag: str) -> bool:
    """A tag is done only when its kept record says the run succeeded (rc 0)."""
    path = nl.runs_dir(design, "runs", tag, "metrics.json")
    if not path.is_file():
        return False
    try:
        return nl.read_json(path).get("rc") == 0
    except (ValueError, OSError):
        return False


def blif_of(design: str) -> Path:
    return nl.runs_dir(design, "netlist", f"{design}.blif")


def _clean(cwd: Path, design: str) -> None:
    """Keep the small records; drop VPR's bulky intermediates (route, packed net)."""
    for pattern in ("*.route", "*.net", "*.net.post_routing", "chanx_occupancy.txt",
                    "chany_occupancy.txt", "vpr_stdout.log", "*.route.delay", "*.place.delay",
                    "report_timing*.rpt", "packing_pin_util.rpt", "report_unconstrained*.rpt",
                    "pre_pack.report_timing.setup.rpt"):
        for path in cwd.glob(pattern):
            path.unlink(missing_ok=True)


def run_one(design: str, tag: str, extra: list[str], *, seed_place: Path | None = None,
            region_seed: str | None = None, timeout: int | None = None,
            arm: str = "", scale: float | None = None) -> dict[str, object]:
    cwd = nl.runs_dir(design, "runs", tag)
    nl.ensure_dir(cwd)
    log = cwd / "vpr.out"
    cmd_extra = ["--seed", "1", "--write_initial_place_file", str(cwd / "initial.place"),
                 "--write_flat_place", str(cwd / "final.flat_place"),
                 "--write_legalized_flat_place", str(cwd / "legalized.flat_place")] + extra
    rc = nl.run_vpr(blif_of(design), cwd, cmd_extra, log, timeout=timeout)
    rec: dict[str, object] = {"design": design, "tag": tag, "arm": arm, "scale": scale,
                              "rc": rc}
    if rc == 0:
        metrics = nl.Metrics(log).values
        rec.update(metrics)
        final_place = cwd / f"{design}.place"
        if final_place.is_file():
            shutil.copyfile(final_place, cwd / "final.place")
        if seed_place is not None and final_place.is_file():
            retention = compute_retention(design, seed_place, cwd / "final.place", region_seed)
            rec.update(retention)
        if region_seed is None and seed_place is not None:
            pass
    nl.write_json(cwd / "metrics.json", rec)
    _clean(cwd, design)
    append_record(design, rec)
    print(f"{design}/{tag}: rc={rc} wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} "
          f"chan={rec.get('chan_width')} place_s={rec.get('place_s')} "
          f"ret={rec.get('retention')}")
    return rec


def compute_retention(design: str, seed_place: Path, final_place: Path,
                      region_seed: str | None) -> dict[str, object]:
    """Seed retention (inside its cluster's region) and mean displacement, at CLB level."""
    seed = nl.Place(seed_place).coords()
    final = nl.Place(final_place).coords()
    clusters_path = nl.runs_dir(design, "seeds", "clusters.json")
    seed_name = region_seed or ""
    regions: dict[str, list[int]] = {}
    clb_cluster: dict[str, str] = {}
    if clusters_path.is_file() and seed_name:
        data = nl.read_json(clusters_path).get("seeds", {}).get(seed_name, {})
        regions = {str(k): v for k, v in data.get("regions", {}).items()}
        for cl, names in data.get("clbs", {}).items():
            for name in names:
                clb_cluster[name] = str(cl)
    displ = []
    inside = total = 0
    for name, (x, y, _s, _l) in seed.items():
        if name not in final or name not in clb_cluster:
            continue
        fx, fy, _fs, _fl = final[name]
        displ.append(((fx - x) ** 2 + (fy - y) ** 2) ** 0.5)
        cluster = clb_cluster.get(name)
        if cluster is not None and cluster in regions:
            lox, loy, hix, hiy = regions[cluster]
            total += 1
            if lox <= fx <= hix and loy <= fy <= hiy:
                inside += 1
    return {"displacement": sum(displ) / len(displ) if displ else None,
            "retention": (inside / total) if total else None}


def baseline(design: str, timeout: int | None = None) -> dict[str, object]:
    tag = "baseline"
    if done(design, tag):
        print(f"{design}/{tag}: already done")
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    return run_one(design, tag, [], arm="baseline", timeout=timeout)


def soft(design: str, seed: str, variant: str, timeout: int | None = None) -> dict[str, object]:
    tag = f"soft-{seed}-{variant}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    place = nl.runs_dir(design, "seeds", f"{seed}-{variant}.place")
    if not place.is_file():
        print(f"{design}/{tag}: no seed file")
        return {"design": design, "tag": tag, "rc": 2}
    return run_one(design, tag, ["--read_initial_place_file", str(place)],
                   seed_place=place, region_seed=seed, arm="soft", timeout=timeout)


def hard(design: str, seed: str, timeout: int | None = None) -> dict[str, object]:
    tag = f"hard-{seed}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    xml = nl.runs_dir(design, "seeds", f"{seed}-hard.xml")
    if not xml.is_file():
        print(f"{design}/{tag}: no constraints file")
        return {"design": design, "tag": tag, "rc": 2}
    rec = run_one(design, tag, ["--read_vpr_constraints", str(xml)],
                  arm="hard", timeout=timeout)
    return rec


def best_final(design: str) -> dict[str, object] | None:
    recs = [r for r in load_records(design)
            if r.get("rc") == 0 and r.get("arm") in ("soft", "hard")
            and r.get("wirelength")]
    if not recs:
        return None
    return min(recs, key=lambda r: float(r["wirelength"]))


def unseeded(design: str, scale: float, timeout: int | None = None) -> dict[str, object]:
    tag = f"unseeded-{scale:g}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    return run_one(design, tag, ["--anneal_auto_init_t_scale", f"{scale:g}"],
                   arm="unseeded", scale=scale, timeout=timeout)


def cold(design: str, scale: float, pstar: Path, region_seed: str | None = None,
         timeout: int | None = None) -> dict[str, object]:
    tag = f"cold-{scale:g}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    return run_one(design, tag, ["--read_initial_place_file", str(pstar),
                                 "--anneal_auto_init_t_scale", f"{scale:g}"],
                   seed_place=pstar, region_seed=region_seed, arm="cold", scale=scale,
                   timeout=timeout)


def crossover(design: str, scales: list[float], timeout: int | None = None) -> dict[str, object]:
    best = best_final(design)
    if best is None:
        print(f"{design}: no seed runs for P*")
        return {}
    src = nl.runs_dir(design, "runs", str(best["tag"]), "final.place")
    pstar = nl.runs_dir(design, "crossover", "Pstar.place")
    nl.ensure_dir(pstar.parent)
    shutil.copyfile(src, pstar)
    region_seed = str(best["tag"]).split("-")[1] if str(best["tag"]).startswith("soft") else \
        str(best["tag"]).split("-", 1)[1]
    rows = []
    for scale in scales:
        u = unseeded(design, scale, timeout=timeout)
        c = cold(design, scale, pstar, region_seed=region_seed, timeout=timeout)
        rows.append({"scale": scale, "unseeded": u.get("wirelength"), "cold": c.get("wirelength"),
                     "cold_t": c.get("init_t"), "unseeded_ret": u.get("retention"),
                     "cold_ret": c.get("retention")})
    wins = [r["scale"] for r in rows if r["cold"] and r["unseeded"]
            and float(r["cold"]) < float(r["unseeded"])]
    result = {"design": design, "pstar": str(best["tag"]), "region_seed": region_seed,
              "scales": rows, "crossover_scale": max(wins) if wins else None,
              "wins_all": len(wins) == len(rows)}
    nl.write_json(nl.runs_dir(design, "crossover", "crossover.json"), result)
    print(f"{design}: P*={best['tag']} crossover_scale={result['crossover_scale']}")
    return result


def unseeded_off(design: str, scale: float, timeout: int | None = None) -> dict[str, object]:
    tag = f"unseededoff-{scale:g}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    return run_one(design, tag, ["--anneal_auto_init_t_scale", f"{scale:g}",
                                 "--place_checkpointing", "off"],
                   arm="unseeded-off", scale=scale, timeout=timeout)


def cold_off(design: str, scale: float, pstar: Path, region_seed: str | None = None,
             timeout: int | None = None) -> dict[str, object]:
    tag = f"coldoff-{scale:g}"
    if done(design, tag):
        return nl.read_json(nl.runs_dir(design, "runs", tag, "metrics.json"))
    return run_one(design, tag, ["--read_initial_place_file", str(pstar),
                                 "--anneal_auto_init_t_scale", f"{scale:g}",
                                 "--place_checkpointing", "off"],
                   seed_place=pstar, region_seed=region_seed, arm="cold-off", scale=scale,
                   timeout=timeout)


def checkpoint_sweep(design: str, scales: list[float], timeout: int | None = None) -> dict[str, object]:
    """The same cold-start sweep with VPR's checkpointing disabled (the control arm).

    VPR 8's checkpointing (`--place_checkpointing`, default on) saves the best late-anneal
    placement and restores it before the quench; the design's prediction (RLPlace) is that the
    crossover moves hotter with it on. No VTR patch is needed for this arm.
    """
    best = best_final(design)
    res_path = nl.runs_dir(design, "crossover", "crossover.json")
    if best is None or not res_path.is_file():
        print(f"{design}: no P* for the checkpointing control")
        return {}
    pstar = nl.runs_dir(design, "crossover", "Pstar.place")
    region_seed = str(nl.read_json(res_path).get("region_seed", ""))
    rows = []
    for scale in scales:
        u = unseeded_off(design, scale, timeout=timeout)
        c = cold_off(design, scale, pstar, region_seed=region_seed, timeout=timeout)
        rows.append({"scale": scale, "unseeded": u.get("wirelength"), "cold": c.get("wirelength"),
                     "cold_t": c.get("init_t"), "cold_ret": c.get("retention")})
    wins = [r["scale"] for r in rows if r["cold"] and r["unseeded"]
            and float(r["cold"]) < float(r["unseeded"])]
    result = {"design": design, "pstar": str(best["tag"]), "scales": rows,
              "crossover_scale_off": max(wins) if wins else None,
              "wins_all": len(wins) == len(rows)}
    nl.write_json(nl.runs_dir(design, "crossover", "checkpoint.json"), result)
    print(f"{design}: checkpointing off crossover_scale={result['crossover_scale_off']}")
    return result


def hot(design: str, seeds: list[str], scale: float, timeout: int | None = None) -> None:
    """Each seed's final placement at the hot scale, vs the unseeded run at the same scale."""
    unseeded(design, scale, timeout=timeout)
    for seed in seeds:
        tag = f"hot-{seed}"
        if done(design, tag):
            continue
        src = nl.runs_dir(design, "runs", f"soft-{seed}-full", "final.place")
        if not src.is_file():
            continue
        hot_place = nl.runs_dir(design, "crossover", f"{seed}-P.place")
        shutil.copyfile(src, hot_place)
        run_one(design, tag, ["--read_initial_place_file", str(hot_place),
                              "--anneal_auto_init_t_scale", f"{scale:g}"],
                seed_place=hot_place, region_seed=seed, arm="hot", scale=scale,
                timeout=timeout)


def run_design(design: str, args: argparse.Namespace) -> None:
    baseline(design, timeout=args.timeout)
    seeds = args.seeds.split(",") if args.seeds else list(nl.SEED_FAMILIES)
    variants = args.variants.split(",") if args.variants else ["full", "inter", "hard"]
    if args.mode in ("seeds", "all"):
        for seed in seeds:
            for variant in variants:
                if variant == "hard":
                    hard(design, seed, timeout=args.timeout)
                else:
                    soft(design, seed, variant, timeout=args.timeout)
    if args.mode in ("crossover", "all"):
        scales = [float(x) for x in args.scales.split(",")]
        res = crossover(design, scales, timeout=args.timeout)
        if res.get("crossover_scale") is not None:
            hot(design, seeds, float(res["crossover_scale"]) * 2, timeout=args.timeout)
    if args.mode in ("checkpoint", "all") and \
            nl.runs_dir(design, "crossover", "crossover.json").is_file():
        checkpoint_sweep(design, [float(x) for x in args.scales.split(",")],
                         timeout=args.timeout)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("baseline", "seeds", "crossover", "checkpoint", "all"))
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--seeds", default="")
    ap.add_argument("--variants", default="")
    ap.add_argument("--scales", default="1,2,4,8,16")
    ap.add_argument("--timeout", type=int, default=None)
    args = ap.parse_args(argv)
    designs = args.designs or list(nl.DESIGN_ORDER)
    for design in designs:
        run_design(design, args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
