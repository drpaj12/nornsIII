"""Round-6 driver (protocol: docs/plan/round6.md). One VPR at a time under the heavy lock.

  python scripts/r6.py synth [design ...]     write the Verilog, run Odin III, keep check k1-k4 -> data/r6/keep.json
  python scripts/r6.py words [design ...]     word recovery, word-file purity, keep item k5, affinity files (needs the Loki venv)
  python scripts/r6.py arms [design ...]      stock / norns / known arms, 3 seeds -> data/r6/runs.jsonl
  python scripts/r6.py status
Designs default to all 105, smallest B first. Reuses the round-5 library (`r5lib`: synthesis, keep check, labels, purity);
the run loop is a copy of `r5.arm_run` because the round tag and the affinity paths are literals there.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
import types

import affinity as af
import matrix
import nornlib as nl
import r3lib  # noqa: F401  (imported for packing metrics)
import r5lib as rl
import round3 as r3

sys.path.insert(0, str(rl.ROOT / "gen"))
import r6gen  # noqa: E402

DATA6 = nl.DATA / "r6"
KEEP_JSON = DATA6 / "keep.json"
RUNS_JSONL = DATA6 / "runs.jsonl"
NORNS_VPR = r3.NORNS_VPR
ARMS = ("stock", "norns", "known")
SEEDS = (1, 2, 3)
TIMEOUT = 7200
NPATHS = 100
BETA_NORNS = 4
KEEP_FILES = ("vpr.out", "metrics.json", "final.flat_place", "initial.place", "report_timing.setup.rpt")
K5_SHARE = 0.90


def k5_ok(coverage: float) -> bool:
    return coverage >= K5_SHARE


def all_designs() -> list[str]:
    order = {t: i for i, t in enumerate(r6gen.TOPOLOGIES)}

    def key(n: str):
        topo, level, b = r6gen.parse_name(n)
        return (b, order[topo], level)

    return sorted(r6gen.names(), key=key)


def kept(design: str) -> bool:
    """KEPT after the words step (k5 decided); a design the words step has not reached yet is not kept."""
    if not KEEP_JSON.is_file():
        return False
    rec = nl.read_json(KEEP_JSON).get(design, {})
    return bool(rec.get("kept", False) and rec.get("k5") is True)


def write_sources(design: str) -> dict:
    spec = r6gen.build_spec(design)
    text = r6gen.verilog(spec)
    nl.ensure_dir(rl.src_dir(design))
    rl.verilog_path(design).write_text(text, encoding="utf-8")
    nl.write_json(rl.src_dir(design) / "spec.json", spec)
    return r6gen.summary(spec, text)


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
        rec["k5"] = None  # decided by the words step
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
    path = af.affinity_path(design, "known", "r6")
    nl.ensure_dir(path.parent)
    path.write_text("".join(f"{a}\t{k}\n" for a, k in sorted(lab.items())), encoding="utf-8")
    return len(lab)


def words(designs: list[str]) -> int:
    import build_words as bw
    rl.use_generated_sources()
    nl.Flat = lambda p: types.SimpleNamespace(atoms={})  # type: ignore[assignment,misc]
    nl.DATA = DATA6 / "words"  # build_words writes its summary under DATA/<design>/words.json
    res = nl.read_json(KEEP_JSON)
    for d in designs:
        rec = res.get(d)
        if not rec or rec.get("synth_rc") != 0 or rec.get("word_purity") is not None:
            continue
        s = bw.build(d)
        ws = word_stats(d)
        rec.update(ws)
        rec["blif_identical"] = s["blif_identical"]
        rec["k5"] = k5_ok(ws["word_coverage"])
        rec["failing"] = list(rec["failing"]) + ([] if rec["k5"] else ["k5"])
        rec["kept"] = bool(rec["kept_k1_k4"] and rec["k5"])
        if rec["kept"]:
            rec["word_entries"] = af.write(d, "word", "r6")
            rec["known_entries"] = write_known_affinity(d)
        nl.write_json(KEEP_JSON, res)
        print(f"words {d}: kept={rec['kept']} purity={ws['word_purity']:.4f} coverage={ws['word_coverage']:.3f} "
              f"words={ws['n_words']}", flush=True)
    return 0


def aff_flags(design: str, arm: str) -> list[str]:
    if arm == "stock":
        return []
    if arm == "norns":
        return ["--norns_affinity", str(af.affinity_path(design, "word", "r6")), "--norns_affinity_weight", f"{BETA_NORNS:g}",
                "--norns_proposal_count", "queued"]
    return ["--norns_affinity", str(af.affinity_path(design, "known", "r6")),
            "--norns_affinity_weight", f"{rl.BETA_KNOWN:g}", "--norns_proposal_count", "queued"]


def tag(arm: str, seed: int) -> str:
    return f"{arm}.s{seed}"


def done(design: str, arm: str, seed: int) -> bool:
    p = nl.runs_dir(design, "r6", tag(arm, seed), "metrics.json")
    return p.is_file() and nl.read_json(p).get("rc") == 0


def arm_run(design: str, arm: str, seed: int) -> dict:
    if done(design, arm, seed):
        return nl.read_json(nl.runs_dir(design, "r6", tag(arm, seed), "metrics.json"))
    cwd = nl.runs_dir(design, "r6", tag(arm, seed))
    nl.ensure_dir(cwd)  # an unfinished earlier directory is reused (VPR overwrites); nothing is deleted
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
        for arm in ARMS:
            for seed in SEEDS:
                arm_run(d, arm, seed)
    return 0


def status() -> int:
    runs = rl.jsonl(RUNS_JSONL)
    ok = [r for r in runs if r["rc"] == 0]
    if KEEP_JSON.is_file():
        k = nl.read_json(KEEP_JSON)
        print(f"keep: {sum(1 for v in k.values() if v['kept'])} of {len(k)}")
    print(f"runs: {len(runs)} ({len(ok)} ok)")
    return 0


def main(argv: list[str]) -> int:
    mode, designs = argv[0], argv[1:] or all_designs()
    fn = {"synth": synth, "words": words, "arms": arms}.get(mode)
    if mode == "status":
        return status()
    if fn is None:
        nl.die(f"unknown mode {mode}")
    return fn(designs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
