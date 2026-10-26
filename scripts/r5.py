"""Round-5 driver (protocol: docs/plan/round5.md). One VPR at a time under the heavy lock.

  python scripts/r5.py synth [design ...]     write the Verilog, run Odin III, keep check -> data/r5/keep.json
  python scripts/r5.py words [design ...]     word recovery + affinity files for the kept designs (needs the Loki venv)
  python scripts/r5.py arms [design ...]      stock / norns / known arms, 3 seeds -> data/r5/runs.jsonl
  python scripts/r5.py attr [design ...]      Odin III attribution of the routed runs (no lock)
  python scripts/r5.py status
Designs default to all 72, smallest first.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
import types

import affinity as af
import matrix
import nornlib as nl
import r3lib  # noqa: F401  (imported for packing metrics)
import r5lib as rl
import round3 as r3

sys.path.insert(0, str(rl.ROOT / "gen"))
import r5gen  # noqa: E402

NORNS_VPR = r3.NORNS_VPR
ARMS = ("stock", "norns", "known")
SEEDS = (1, 2, 3)
TIMEOUT = 7200
NPATHS = 100
KEEP_FILES = ("vpr.out", "metrics.json", "final.flat_place", "initial.place", "report_timing.setup.rpt", "attr.json",
              "paths.json.gz")
KEEP_JSON = rl.DATA5 / "keep.json"
RUNS_JSONL = rl.DATA5 / "runs.jsonl"


def all_designs() -> list[str]:
    """HDL designs and netlist-level designs, smallest B first (netlist level before HDL within a size)."""
    import r5nl
    return sorted(r5nl.names() + r5gen.names(), key=lambda n: (r5gen.parse_name("r5_" + n.split("_", 1)[1])[2], not n.startswith("n5_"), n))


def kept(design: str) -> bool:
    return KEEP_JSON.is_file() and nl.read_json(KEEP_JSON).get(design, {}).get("kept", False)


def synth(designs: list[str]) -> int:
    res = nl.read_json(KEEP_JSON) if KEEP_JSON.is_file() else {}
    for d in designs:
        if d in res and res[d].get("synth_rc") == 0:
            continue
        if rl.is_nl(d):
            rc, rec = 0, rl.synth_nl(d)
        else:
            rl.write_sources(d)
            rc = rl.synth(d)
            rec = rl.keep_check(d) if rc == 0 else {"design": d, "kept": False, "failing": ["synth"]}
        rec["synth_rc"] = rc
        res[d] = rec
        nl.write_json(KEEP_JSON, res)
        print(f"synth {d}: rc={rc} kept={rec['kept']} original_rule={rec.get('kept_original_rule')} "
              f"cut {rec.get('measured_cut')}/{rec.get('designed_cut')} fail={rec['failing']}", flush=True)
    return 0


def words(designs: list[str]) -> int:
    import build_words as bw
    rl.use_generated_sources()
    nl.Flat = lambda p: types.SimpleNamespace(atoms={})  # type: ignore[assignment,misc]
    nl.DATA = rl.DATA5 / "words"  # build_words writes its summary under DATA/<design>/words.json
    out = {}
    for d in designs:
        if not kept(d) or rl.is_nl(d):
            continue
        s = bw.build(d)
        n = af.write(d, "word", "r5")
        k = rl.write_known_affinity(d)
        lab = af.labels(d, "word")
        out[d] = {"word_entries": n, "known_entries": k, "words": s["words"], "blif_identical": s["blif_identical"],
                  "labelled_luts_ffs": len(lab)}
        print(f"words {d}: {out[d]}", flush=True)
    return 0


def aff_flags(design: str, arm: str) -> list[str]:
    if arm == "stock":
        return []
    if rl.is_nl(design) and arm == "known":
        rl.write_known_affinity(design)
    if arm == "norns":
        return ["--norns_affinity", str(af.affinity_path(design, "word", "r5")), "--norns_affinity_weight", "4",
                "--norns_proposal_count", "queued"]
    return ["--norns_affinity", str(af.affinity_path(design, "known", "r5")),
            "--norns_affinity_weight", f"{rl.BETA_KNOWN:g}", "--norns_proposal_count", "queued"]


def arms_of(design: str) -> tuple[str, ...]:
    return ("stock", "known") if rl.is_nl(design) else ARMS


def tag(arm: str, seed: int) -> str:
    return f"{arm}.s{seed}"


def done(design: str, arm: str, seed: int) -> bool:
    p = nl.runs_dir(design, "r5", tag(arm, seed), "metrics.json")
    return p.is_file() and nl.read_json(p).get("rc") == 0


def arm_run(design: str, arm: str, seed: int) -> dict:
    if done(design, arm, seed):
        return nl.read_json(nl.runs_dir(design, "r5", tag(arm, seed), "metrics.json"))
    cwd = nl.runs_dir(design, "r5", tag(arm, seed))
    if cwd.exists():
        shutil.rmtree(cwd)
    nl.ensure_dir(cwd)
    flags = ["--seed", str(seed), "--timing_report_npaths", str(NPATHS),
             "--write_initial_place_file", str(cwd / "initial.place"),
             "--write_flat_place", str(cwd / "final.flat_place")] + aff_flags(design, arm)
    binary = nl.VPR if arm == "stock" else NORNS_VPR
    rc = nl.run(r3.cmd_for(binary, matrix.blif_of(design), flags), cwd=cwd, stdout=cwd / "vpr.out", timeout=TIMEOUT)
    rec: dict = {"design": design, "arm": arm, "vseed": seed, "rc": rc}
    if rc == 0:
        log = cwd / "vpr.out"
        rec.update(nl.Metrics(log).values)
        rec.pop("init_t", None)
        text = log.read_text(errors="replace")
        m = re.search(r"### Packing took ([0-9.]+) seconds", text)
        if m:
            rec["pack_s"] = float(m.group(1))
        net = cwd / f"{design}.net"
        if net.is_file():
            import hashlib
            rec["net_sha256"] = hashlib.sha256(net.read_bytes()).hexdigest()
        init = cwd / "initial.place"
        if init.is_file():
            w, h = nl.grid_size(nl.Place(init))
            rec["grid"] = [w, h]
        rec.update(rl.packing_vs_blocks(design, cwd / "final.flat_place"))
        m = re.search(r"Norns affinity: (\d+) of (\d+) file entries matched atoms, (\d+) groups", text)
        rec["affinity_matched"] = [int(m.group(1)), int(m.group(2)), int(m.group(3))] if m else None
    else:
        rec["error"] = matrix.vpr_error(cwd / "vpr.out")
    for f in list(cwd.iterdir()):
        if f.name not in KEEP_FILES:
            f.unlink() if f.is_file() else shutil.rmtree(f, ignore_errors=True)
    nl.write_json(cwd / "metrics.json", rec)
    RUNS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{design}/{tag(arm, seed)}: rc={rc} clbs={rec.get('logic_clbs')} wl={rec.get('wirelength')} W={rec.get('chan_width')} "
          f"cpd={rec.get('cpd_ns')} purity={rec.get('purity')} repro={rec.get('reproduction')} flow_s={rec.get('flow_s')}", flush=True)
    return rec


def arms(designs: list[str]) -> int:
    for d in designs:
        if not kept(d):
            continue
        for arm in arms_of(d):
            for seed in SEEDS:
                arm_run(d, arm, seed)
    return 0


def attr(designs: list[str]) -> int:
    import timing4
    rl.use_generated_sources()
    for d in designs:
        if not kept(d):
            continue
        for arm in arms_of(d):
            for seed in SEEDS:
                cwd = nl.runs_dir(d, "r5", tag(arm, seed))
                mp = cwd / "metrics.json"
                if not (mp.is_file() and nl.read_json(mp).get("rc") == 0) or (cwd / "attr.json").is_file():
                    continue
                rec = nl.read_json(mp)
                try:
                    rep = timing4.attribute(cwd, matrix.blif_of(d), netlist_json=None if rl.is_nl(d) else timing4.ensure_json(d))
                except Exception as exc:  # noqa: BLE001 - recorded
                    rec["attr_error"] = f"{type(exc).__name__}: {exc}"
                    nl.write_json(mp, rec)
                    print(f"attr {d}/{tag(arm, seed)}: {rec['attr_error']}", flush=True)
                    continue
                flat = nl.Flat(cwd / "final.flat_place")
                paths = [{"index": p["index"], "slack": p["slack_ns"], "arrival": p["arrival_ns"],
                          "nodes": [n["atom"] for n in p["nodes"]]} for p in rep["paths"]]
                hops = cross = 0
                for p in paths:
                    for a, b in zip(p["nodes"], p["nodes"][1:]):
                        ca, cb = flat.clb_of(a), flat.clb_of(b)
                        if ca and cb and flat.atoms[a][5] in ("lut", "latch") and flat.atoms[b][5] in ("lut", "latch"):
                            hops += 1
                            cross += ca != cb
                with gzip.open(cwd / "paths.json.gz", "wt") as fh:
                    json.dump(paths, fh)
                nl.write_json(cwd / "attr.json", {k: v for k, v in rep.items() if k != "paths"})
                rec.update({"attr_cpd_ns": rep["timing"]["cpd_ns"], "paths_in_report": rep["timing"]["paths_in_report"],
                            "path_hops": hops, "path_hops_crossing": cross})
                nl.write_json(mp, rec)
                print(f"attr {d}/{tag(arm, seed)}: cpd {rec.get('cpd_ns')} vs {rec['attr_cpd_ns']} hops {cross}/{hops}", flush=True)
    return 0


def status() -> int:
    runs = rl.jsonl(RUNS_JSONL)
    ok = [r for r in runs if r["rc"] == 0]
    print(f"keep: {sum(1 for v in nl.read_json(KEEP_JSON).values() if v['kept'])} of {len(nl.read_json(KEEP_JSON))}" if KEEP_JSON.is_file() else "no keep")
    print(f"runs: {len(runs)} ({len(ok)} ok)")
    return 0


def main(argv: list[str]) -> int:
    mode, designs = argv[0], argv[1:] or all_designs()
    fn = {"synth": synth, "words": words, "arms": arms, "attr": attr}.get(mode)
    if mode == "status":
        return status()
    if fn is None:
        nl.die(f"unknown mode {mode}")
    return fn(designs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
