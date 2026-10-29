"""Round-8 driver (H22' re-run; protocol: docs/plan/round8-h22.md). One VPR at a time under the Norns VPR lock.

  python scripts/r8.py synth [design ...]    write the Verilog, run Odin III, keep checks k1-k4 -> $NORNS_DATA/r8/keep.json
  python scripts/r8.py words [design ...]    word recovery, word-file purity, keep item k5, affinity files (needs the Loki venv)
  python scripts/r8.py gate  [design ...]    control (i): chain, `--pack` only, stock vs Norns beta 0 .net sha256 -> gate.json
  python scripts/r8.py arms  [design ...]    stock / norns / known arms (control designs r6_chain_a100_*: stock, norns), seeds 1-3
  python scripts/r8.py status
Designs default to all 84 + the 7 control-(ii) designs `r6_chain_a100_<B>`, smallest B first. Every run writes a Mimir run record
(`mimir-run.json`, scripts/runrecord.py). Commit the scripts before a run batch (record `clean` flag); put NORNS_RUNS and NORNS_DATA
outside the checkout so a run never dirties it. Reuses r5lib / r6 helpers; nothing is deleted.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import sys
import types
from pathlib import Path

import affinity as af
import matrix
import nornlib as nl
import r3lib  # noqa: F401  (imported for packing metrics)
import r5lib as rl
import round3 as r3
import runrecord as rr

sys.path.insert(0, str(rl.ROOT / "gen"))
import r6gen  # noqa: E402
import r8gen  # noqa: E402

DATA8 = nl.DATA / "r8"
KEEP_JSON = DATA8 / "keep.json"
GATE_JSON = DATA8 / "gate.json"
RUNS_JSONL = DATA8 / "runs.jsonl"
NORNS_VPR = r3.NORNS_VPR
ARMS = ("stock", "norns", "known")
CONTROL_ARMS = ("stock", "norns")  # control (ii): r6_chain_a100_*
SEEDS = (1, 2, 3)
TIMEOUT = 7200
NPATHS = 1000
BETA_NORNS = 4
ROUTE_KEEP_MAX_B = 128  # the .route is written into the run directory only up to this size (larger: --route_file /dev/null)
KEEP_FILES = ("vpr.out", "metrics.json", "final.flat_place", "initial.place", "report_timing.setup.rpt")
K5_SHARE = 0.90
SOURCE = "norns-h22"
TOOLS: dict[str, dict] = {}
NORN_TREE = nl.WS
NORNS_VTR_TREE = Path(os.environ.get("NORNS_VTR", str(NORNS_VPR.parents[2])))


def is_control2(design: str) -> bool:
    return design.startswith("r6_")


def gen_of(design: str):
    return r6gen if is_control2(design) else r8gen


def b_of(design: str) -> int:
    return gen_of(design).parse_name(design)[-1]


def topo_of(design: str) -> str:
    return gen_of(design).parse_name(design)[0]


def all_designs() -> list[str]:
    order = {t: i for i, t in enumerate(r8gen.TOPOLOGIES)}
    main = [(r8gen.parse_name(n)[2], order[r8gen.parse_name(n)[0]], r8gen.parse_name(n)[1], n) for n in r8gen.names()]
    ctl = [(b, 2, 100, f"r6_chain_a100_{b}") for b in r8gen.SIZES]
    return [x[3] for x in sorted(main + ctl)]


def kept(design: str) -> bool:
    if not KEEP_JSON.is_file():
        return False
    rec = nl.read_json(KEEP_JSON).get(design, {})
    return bool(rec.get("kept", False) and rec.get("k5") is True)


def write_sources(design: str) -> dict:
    g = gen_of(design)
    spec = g.build_spec(design)
    text = g.verilog(spec)
    nl.ensure_dir(rl.src_dir(design))
    rl.verilog_path(design).write_text(text, encoding="utf-8")
    nl.write_json(rl.src_dir(design) / "spec.json", spec)
    return g.summary(spec, text)


def synth(designs: list[str]) -> int:
    res = nl.read_json(KEEP_JSON) if KEEP_JSON.is_file() else {}
    for d in designs:
        if d in res and res[d].get("synth_rc") == 0:
            continue
        write_sources(d)
        rc = rl.synth(d)
        rec = rl.keep_check(d) if rc == 0 else {"design": d, "kept": False, "failing": ["synth"]}
        rec["synth_rc"] = rc
        rec["kept_k1_k4"] = rec["kept"]
        rec["k5"] = None
        res[d] = rec
        nl.write_json(KEEP_JSON, res)
        print(f"synth {d}: rc={rc} k1-k4 kept={rec['kept']} cut {rec.get('measured_cut')}/{rec.get('designed_cut')} "
              f"fail={rec['failing']}", flush=True)
    return 0


def word_stats(design: str) -> dict:
    """Word-file coverage of the flip-flops and its purity against the blocks (the measured alignment a_m)."""
    spec = rl.read_spec(design)
    parsed = rl.parse(design)
    members = nl.read_json(nl.runs_dir(design, "words", "members.json"))
    ffs = [a["name"] for a in rl.atoms_of(parsed) if a["kind"] == "latch"]
    with_word = [a for a in ffs if a in members and members[a]["word"]]
    words: dict[str, list[int]] = collections.defaultdict(list)
    for a in with_word:
        k, _ = rl.label_of(a, spec)
        if k is not None:
            words[members[a]["word"]].append(k)
    tot = sum(len(v) for v in words.values())
    pur = sum(max(collections.Counter(v).values()) for v in words.values()) / tot if tot else float("nan")
    return {"ffs": len(ffs), "ffs_with_word": len(with_word), "word_coverage": len(with_word) / len(ffs) if ffs else 0.0,
            "n_words": len(words), "words_ge2": sum(1 for v in words.values() if len(v) >= 2), "word_purity": pur,
            "blocks_per_word": sum(len(set(v)) for v in words.values()) / len(words) if words else float("nan")}


def write_known_affinity(design: str) -> int:
    lab = rl.known_labels(design)
    path = af.affinity_path(design, "known", "r8")
    nl.ensure_dir(path.parent)
    path.write_text("".join(f"{a}\t{k}\n" for a, k in sorted(lab.items())), encoding="utf-8")
    return len(lab)


def words(designs: list[str]) -> int:
    import build_words as bw
    rl.use_generated_sources()
    nl.Flat = lambda p: types.SimpleNamespace(atoms={})  # type: ignore[assignment,misc]
    nl.DATA = DATA8 / "words"  # build_words writes its summary under DATA/<design>/words.json
    res = nl.read_json(KEEP_JSON)
    for d in designs:
        rec = res.get(d)
        if not rec or rec.get("synth_rc") != 0 or rec.get("word_purity") is not None:
            continue
        s = bw.build(d)
        ws = word_stats(d)
        rec.update(ws)
        rec["blif_identical"] = s["blif_identical"]
        rec["k5"] = ws["word_coverage"] >= K5_SHARE
        rec["failing"] = list(rec["failing"]) + ([] if rec["k5"] else ["k5"])
        rec["kept"] = bool(rec["kept_k1_k4"] and rec["k5"])
        if rec["kept"]:
            rec["word_entries"] = af.write(d, "word", "r8")
            rec["known_entries"] = write_known_affinity(d)
        nl.write_json(KEEP_JSON, res)
        print(f"words {d}: kept={rec['kept']} purity={ws['word_purity']:.4f} coverage={ws['word_coverage']:.3f} "
              f"words={ws['n_words']}", flush=True)
    return 0


def aff_flags(design: str, arm: str, weight: float | None = None) -> list[str]:
    if arm == "stock":
        return []
    if arm in ("norns", "beta0"):
        w = BETA_NORNS if weight is None else weight
        return ["--norns_affinity", str(af.affinity_path(design, "word", "r8")), "--norns_affinity_weight", f"{w:g}",
                "--norns_proposal_count", "queued"]
    return ["--norns_affinity", str(af.affinity_path(design, "known", "r8")),
            "--norns_affinity_weight", f"{rl.BETA_KNOWN:g}", "--norns_proposal_count", "queued"]


def tag(arm: str, seed: int) -> str:
    return f"{arm}.s{seed}"


def done(design: str, arm: str, seed: int) -> bool:
    p = nl.runs_dir(design, "r8", tag(arm, seed), "metrics.json")
    return p.is_file() and nl.read_json(p).get("rc") == 0


def binary_of(arm: str) -> Path:
    return nl.VPR if arm == "stock" else NORNS_VPR


def tool(name: str) -> dict:
    if name not in TOOLS:
        if name == "vpr_stock":
            TOOLS[name] = rr.tool_entry(nl.VTR_ROOT, nl.VPR)
        elif name == "vpr_norns":
            TOOLS[name] = rr.tool_entry(NORNS_VTR_TREE, NORNS_VPR, overlay_repo=NORN_TREE)
        else:
            TOOLS[name] = rr.tool_entry(NORN_TREE, Path(__file__), version_args=None)
    return TOOLS[name]


def vpr_run(design: str, arm: str, cwd: Path, flags: list[str], seed: int) -> tuple[int, list[str], float | None, float | None]:
    """One VPR run under the Norns lock with /usr/bin/time -v; returns rc, argv, wall s, peak RSS MiB."""
    argv = [str(binary_of(arm)), str(nl.ARCH), str(matrix.blif_of(design))] + flags
    tfile = cwd / "time.txt"
    cmd = ["flock", "-x", str(nl.LOCK), "/usr/bin/time", "-v", "-o", str(tfile)] + argv
    rc = nl.run(cmd, cwd=cwd, stdout=cwd / "vpr.out", timeout=TIMEOUT)
    secs, rss = rr.parse_time_v(tfile.read_text(errors="replace")) if tfile.exists() else (None, None)
    return rc, argv, secs, rss


def write_record(design: str, arm: str, seed: int, cwd: Path, argv: list[str], rc: int, secs, rss, aff: Path | None) -> None:
    blif = matrix.blif_of(design)
    stock = arm == "stock"
    vkey = "vpr_stock" if stock else "vpr_norns"
    tree = nl.VTR_ROOT if stock else NORNS_VTR_TREE
    run_id = f"{SOURCE}/{design}/{arm}/s{seed}"
    try:
        r = rr.RunRecorder(SOURCE, design, arm, seed, "analytic", nl.ARCH.stem,
                           roots={"run": cwd, "norns_vtr": NORNS_VTR_TREE, "vtr": nl.VTR_ROOT, "runs": nl.RUNS},
                           roles={binary_of(arm): "<vpr>", nl.ARCH: "<arch>", blif: "<blif>"} | ({aff: "<affinity>"} if aff else {}))
        r.add_step("vpr", argv, rc, secs, rss, True)
        r.add_tool("vpr", tool(vkey))
        r.add_tool("norns", tool("norns"))
        r.add_vpr_params(argv, cwd / "vpr.out", tree, str(tool(vkey)["commit"]))
        r.add_input("netlist", blif)
        r.add_input("arch", nl.ARCH)
        if aff:
            r.add_input("affinity", aff)
        for role, name in (("vpr_out", "vpr.out"), ("flat_place", "final.flat_place"), ("initial_place", "initial.place"),
                           ("timing_report", "report_timing.setup.rpt")):
            r.add_artifact(role, cwd / name)
        r.write(cwd / "mimir-run.json", required_inputs=("netlist", "arch"), required_artifacts=("vpr_out", "flat_place"))
    except rr.HostMapError as exc:
        print(f"run record NOT written for {run_id}: {exc}", file=sys.stderr, flush=True)
    except rr.RecordRefused as exc:
        print(f"run record NOT written for {run_id}: privacy rule(s) hit: {'; '.join(exc.hits)}", file=sys.stderr, flush=True)


def arm_run(design: str, arm: str, seed: int) -> dict:
    if done(design, arm, seed):
        return nl.read_json(nl.runs_dir(design, "r8", tag(arm, seed), "metrics.json"))
    cwd = nl.runs_dir(design, "r8", tag(arm, seed))
    nl.ensure_dir(cwd)  # an unfinished earlier directory is reused (VPR overwrites); nothing is deleted
    flags = ["--seed", str(seed), "--timing_report_npaths", str(NPATHS),
             "--write_initial_place_file", str(cwd / "initial.place"),
             "--write_flat_place", str(cwd / "final.flat_place")] + aff_flags(design, arm)
    if b_of(design) > ROUTE_KEEP_MAX_B:
        flags += ["--route_file", "/dev/null"]
    rc, argv, secs, rss = vpr_run(design, arm, cwd, flags, seed)
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
    rec["peak_rss_mib"] = rss
    nl.write_json(cwd / "metrics.json", rec)
    aff = None if arm == "stock" else Path(argv[argv.index("--norns_affinity") + 1])
    write_record(design, arm, seed, cwd, argv, rc, secs, rss, aff)
    RUNS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with RUNS_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{design}/{tag(arm, seed)}: rc={rc} clbs={rec.get('logic_clbs')} wl={rec.get('wirelength')} W={rec.get('chan_width')} "
          f"cpd={rec.get('cpd_ns')} purity={rec.get('purity')} flow_s={rec.get('flow_s')}", flush=True)
    return rec


def arms(designs: list[str]) -> int:
    for d in designs:
        if not kept(d):
            continue
        for arm in (CONTROL_ARMS if is_control2(d) else ARMS):
            for seed in SEEDS:
                arm_run(d, arm, seed)
    return 0


def gate(designs: list[str]) -> int:
    """Control (i): `--pack` only, seed 1; the Norns binary at beta 0 with the word file must write a .net byte-identical to stock."""
    res = nl.read_json(GATE_JSON) if GATE_JSON.is_file() else {}
    for d in designs:
        if topo_of(d) != "chain" or is_control2(d) or not kept(d):
            continue
        shas = {}
        for arm in ("stock", "beta0"):
            cwd = nl.runs_dir(d, "r8", f"gate.{arm}")
            nl.ensure_dir(cwd)
            flags = ["--seed", "1", "--pack"] + aff_flags(d, arm, 0.0)
            rc, _, _, _ = vpr_run(d, arm if arm == "stock" else "norns", cwd, flags, 1)
            net = cwd / f"{d}.net"
            shas[arm] = hashlib.sha256(net.read_bytes()).hexdigest() if rc == 0 and net.is_file() else None
        res[d] = {"stock_net_sha256": shas["stock"], "beta0_net_sha256": shas["beta0"],
                  "identical": shas["stock"] is not None and shas["stock"] == shas["beta0"]}
        nl.write_json(GATE_JSON, res)
        print(f"gate {d}: identical={res[d]['identical']}", flush=True)
    return 0


def status() -> int:
    runs = rl.jsonl(RUNS_JSONL)
    ok = [r for r in runs if r["rc"] == 0]
    if KEEP_JSON.is_file():
        k = nl.read_json(KEEP_JSON)
        print(f"keep: {sum(1 for v in k.values() if v['kept'])} of {len(k)}")
    if GATE_JSON.is_file():
        g = nl.read_json(GATE_JSON)
        print(f"gate: {sum(1 for v in g.values() if v['identical'])} identical of {len(g)}")
    print(f"runs: {len(runs)} ({len(ok)} ok)")
    return 0


def main(argv: list[str]) -> int:
    mode, designs = argv[0], argv[1:] or all_designs()
    fn = {"synth": synth, "words": words, "arms": arms, "gate": gate}.get(mode)
    if mode == "status":
        return status()
    if fn is None:
        nl.die(f"unknown mode {mode}")
    return fn(designs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
