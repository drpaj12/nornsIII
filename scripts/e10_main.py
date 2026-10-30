"""E10 sweep driver (docs/plan/e10.md): Odin III netlists, VPR / nextpnr runs through placers_main.py, structure rows.

Usage: . scripts/env.sh; python3 scripts/e10_main.py --root RUNROOT --stage netlists|runs|structures [--designs a,b] [--configs c1,c2]
       [--label e10|e10gate]

Everything is resumable (a finished record is skipped). Nothing is deleted. Layout under RUNROOT:
  netlists/<netkey>/<design>/netlist/<design>.blif (+ .names, odin.log, odin-meta.json)   one Odin III run per netkey and design
  vpr/<label>-<config>/<design>/<arm>.s<seed>/...                                         placers_main.py work dirs (records, .net, .place)
  struct/<label>-<config>/<design>/<arm>.s<seed>/                                         extended name map of the run
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import nornlib as nl
import runrecord as rr

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VTR = nl.VTR_ROOT
ARCH_DIR = VTR / "vtr_flow" / "arch" / "timing"
ARCHS = {"norns": ARCH_DIR / "k6_frac_N10_frac_chain_mem32K_40nm.xml", "k4": ARCH_DIR / "k4_N4_90nm.xml", "earch": ARCH_DIR / "EArch.xml"}
ODIN_TREE = Path(os.environ.get("E10_ODIN_TREE", str(nl.WS_ROOT / "odin3")))
ODIN_BIN = Path(os.environ.get("E10_ODIN_BIN", str(nl.WS_ROOT / "work" / "e10-odin3-build" / "odin3")))
ODIN_BUILD = ODIN_BIN.parent
ABC_DIR = REPO / "data" / "e10" / "abc"
MCNC_DIR = VTR / "vtr_flow" / "benchmarks" / "blif"
NORNS15 = ("ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B", "sha",
           "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2")
MCNC20 = tuple(n.strip()[:-5] for n in (MCNC_DIR / "circuits.txt").read_text().split() if n.strip())
PLACE_LOCK = "/tmp/claude-1000/norns-vpr.lock"

# netkey: what changes the netlist (ABC script, K, the architecture Odin III reads)
NETKEYS = {
    "base": {"abc": None, "k": 6, "arch": "norns"},
    "abc1": {"abc": "abc1", "k": 6, "arch": "norns"},
    "abc2": {"abc": "abc2", "k": 6, "arch": "norns"},
    "k4": {"abc": None, "k": 4, "arch": "k4"},
    "earch": {"abc": None, "k": 6, "arch": "earch"},
}
# config: netlist, architecture VPR reads, extra VPR flags, arms (placers.md section 4 names)
CONFIGS = {
    "base": {"net": "base", "arch": "norns", "vpr": "", "arms": "vpr_sa"},
    "abc1": {"net": "abc1", "arch": "norns", "vpr": "", "arms": "vpr_sa"},
    "abc2": {"net": "abc2", "arch": "norns", "vpr": "", "arms": "vpr_sa"},
    "k4": {"net": "k4", "arch": "k4", "vpr": "", "arms": "vpr_sa", "extra": ["--vpr-timeout", "900"]},
    "earch": {"net": "earch", "arch": "earch", "vpr": "", "arms": "vpr_sa"},
    "uon": {"net": "base", "arch": "norns", "vpr": "--allow_unrelated_clustering on", "arms": "vpr_sa"},
    "uoff": {"net": "base", "arch": "norns", "vpr": "--allow_unrelated_clustering off", "arms": "vpr_sa"},
    "rc1": {"net": "base", "arch": "norns", "vpr": "--norns_refresh_crit 1", "arms": "vpr_sa"},  # H-refresh (docs/plan/refresh-crit.md), k = 1
    "rc8": {"net": "base", "arch": "norns", "vpr": "--norns_refresh_crit 8", "arms": "vpr_sa"},  # H-refresh, k = 8
    "h1": {"net": "base", "arch": "norns", "vpr": "--norns_2hop_weight 0.1", "arms": "vpr_sa"},    # Q-N3b (docs/plan/q-n3b-2hop-gain.md), w = 0.1
    "h25": {"net": "base", "arch": "norns", "vpr": "--norns_2hop_weight 0.25", "arms": "vpr_sa"},  # Q-N3b, w = 0.25
    "plc": {"net": "base", "arch": "norns", "vpr": "", "arms": "vpr_ap,ext_nextpnr_heap,ext_nextpnr_sa", "extra": ["--sa-temp", "100"]}  # T = 100: placers.md section 10.5,
}


_MODULE = re.compile(r"^\s*module\s+(\w+)", re.M)


def find_top(design):
    """The module no other module of the file instantiates (the last one when several); the rule of mimir.structbatch.find_top, which the structure flow uses."""
    text = nl.design_verilog(design).read_text(encoding="utf-8", errors="replace")
    mods = _MODULE.findall(text)
    free = [m for m in mods if not re.search(rf"^\s*{re.escape(m)}\s+(?:#\s*\(.*?\)\s*)?\w+\s*\(", text, re.M | re.S)]
    return (free or mods)[-1]


def src_of(design):
    return (MCNC_DIR / f"{design}.blif") if design in MCNC20 else nl.design_verilog(design)


def suite_of(design):
    return "mcnc20" if design in MCNC20 else "norns15"


def abc_file(key):
    return ABC_DIR / f"{key}.abc" if key else None


def odin_script(netkey, design, out):
    nk = NETKEYS[netkey]
    abc = f"abc {'--script ' + str(abc_file(nk['abc'])) + ' ' if nk['abc'] else ''}--lut {nk['k']}"
    src = src_of(design)
    arch = ARCHS[nk["arch"]]
    if design in MCNC20:  # pre-mapped 4-LUT BLIF, re-mapped by ABC (the Pprime leg of vtr-qor); no HDL, no name map
        return f"read_arch {arch}; read_blif {src}; {abc}; stats; write_blif --vtr --lut-k {nk['k']} {out}"
    return (f"read_arch {arch}; read_verilog --nolatches --vtr-compat --prov-ast refs {src}; proc; fsm; opt; flatten; opt -full; wreduce; hardmap; lower; "
            f"{abc}; stats; write_blif --vtr --lut-k {nk['k']} --name-style hash --prov-map {out}")


def odin_tool_entry():
    """Tool entry of the Odin III binary. The build is out of tree from the main checkout; the commit is `given` only when the checkout is clean,
    the build directory was configured from it and the binary is newer than HEAD (the same three facts as mimir.structrun.build_check)."""
    cache = (ODIN_BUILD / "CMakeCache.txt").read_text(errors="replace") if (ODIN_BUILD / "CMakeCache.txt").is_file() else ""
    m = re.search(r"CMAKE_HOME_DIRECTORY:INTERNAL=(.*)", cache)
    same_home = bool(m) and Path(m.group(1)).resolve() == ODIN_TREE.resolve()
    ct = rr.git(ODIN_TREE, "log", "-1", "--format=%ct")
    newer = ODIN_BIN.is_file() and ct.isdigit() and ODIN_BIN.stat().st_mtime > int(ct)
    e = rr.tool_entry(ODIN_TREE, ODIN_BIN)  # odin3 --version prints no commit, so it cannot name HEAD itself
    e["build_facts"] = {"cmake_home_is_tree": same_home, "binary_newer_than_commit": bool(newer)}
    if same_home and newer and e["clean"] is True and e["built_dirty"] is False:
        e["version_names_commit"] = True  # stands for: tree clean at record time, build dir configured from it, binary newer than HEAD (build_facts)
        e["commit_how"] = "git rev-parse HEAD of the source tree; checked: tree clean, build directory configured from it, binary newer than HEAD"
    return e


def ph(text):
    """Placeholders for the paths in an Odin III command text."""
    for root, name in ((str(ARCH_DIR), "<vtr>/vtr_flow/arch/timing"), (str(MCNC_DIR), "<vtr>/vtr_flow/benchmarks/blif"),
                       (str(nl.BENCH), "<vtr>/vtr_flow/benchmarks/verilog"), (str(ABC_DIR), "<norns>/data/e10/abc")):
        text = text.replace(root, name)
    return text


def netlist(root, netkey, design):
    """Run Odin III once for (netkey, design); returns the BLIF path (None on failure). Writes odin-meta.json."""
    d = root / "netlists" / netkey / design / "netlist"
    blif, meta = d / f"{design}.blif", d / "odin-meta.json"
    if blif.is_file() and meta.is_file():
        return blif
    d.mkdir(parents=True, exist_ok=True)
    script = odin_script(netkey, design, blif)
    argv = [str(ODIN_BIN)] + ([] if design in MCNC20 else ["--top", find_top(design)]) + ["-p", script]
    t0 = time.time()
    p = subprocess.run(["/usr/bin/time", "-v", "-o", str(d / "odin.time"), *argv], capture_output=True, text=True, cwd=d, env=dict(os.environ, ODIN3_ROOT=str(ODIN_TREE)))
    secs = time.time() - t0
    (d / "odin.log").write_text(f"$ {ph(' '.join(argv)).replace(str(ODIN_BIN), 'odin3')}\n{p.stdout}{p.stderr}")
    s2, rss = rr.parse_time_v((d / "odin.time").read_text()) if (d / "odin.time").is_file() else (None, None)
    nk = NETKEYS[netkey]
    af = abc_file(nk["abc"])
    default_abc = ODIN_TREE / "lib" / "abc" / "vtr.abc"
    head = rr.git(ODIN_TREE, "rev-parse", "HEAD")[:8]
    params = [
        ["odin.lut_k", str(nk["k"]), "given", "command line (abc --lut)"],
        ["odin.arch_file", ph(str(ARCHS[nk["arch"]])).replace("<vtr>/vtr_flow/arch/timing/", ""), "given", "command line (read_arch)"],
        ["odin.script", ph(script).replace(str(d) + "/", "<out>/"), "given", "command line (odin3 -p)"],
        ["odin.input_kind", "blif" if design in MCNC20 else "verilog", "given", "the run's command line (read_blif or read_verilog)"],
    ]
    if af:
        params += [["odin.abc_script", af.name, "given", "command line (abc --script)"], ["odin.abc_script_sha256", rr.file_sha256(af), "given", "sha256 of the script file as committed in nornsIII data/e10/abc"]]
    else:
        line = rr.line_of(default_abc, "strash") if default_abc.is_file() else 0
        params += [["odin.abc_script", "lib/abc/vtr.abc", "default", f"odin3 {head} lib/abc/vtr.abc:1-10"],
                   ["odin.abc_script_sha256", rr.file_sha256(default_abc), "default", f"odin3 {head} lib/abc/vtr.abc:1-10"]]
    ok = p.returncode == 0 and blif.is_file()
    m = {"argv": [ph(a).replace(str(ODIN_BIN), "<odin3>").replace(str(d) + "/", "<out>/") if a != script else ph(script).replace(str(d) + "/", "<out>/") for a in argv], "rc": p.returncode, "secs": secs if s2 is None else s2, "rss": (rss / 1024.0 if rss else None),
         "tool": odin_tool_entry(), "params": params, "ok": ok}
    meta.write_text(json.dumps(m, indent=1) + "\n")
    return blif if ok else None


def lut_count(blif):
    return sum(1 for ln in blif.read_text(errors="replace").splitlines() if ln.startswith(".names") and len(ln.split()) >= 3)


def order(root, designs):
    """Designs smallest first by the LUT count of their base netlist (docs/plan/e10.md)."""
    sizes = {}
    for d in designs:
        b = netlist(root, "base", d)
        sizes[d] = lut_count(b) if b else 10**9
    return sorted(designs, key=lambda d: (sizes[d], d)), sizes


def run_config(root, label, cfg, design, seeds):
    c = CONFIGS[cfg]
    net = root / "netlists" / c["net"]
    blif = netlist(root, c["net"], design)
    if blif is None:
        print(f"{label}-{cfg} {design}: NETLIST FAILED", flush=True)
        return 1
    work = root / "vpr" / f"{label}-{cfg}"
    env = dict(os.environ, NORNS_RUNS=str(net), NORNS_ARCH=str(ARCHS[c["arch"]]), NORNS_DATA=str(root / "data"), NORNS_LOCK=PLACE_LOCK)
    argv = [sys.executable, str(HERE / "placers_main.py"), "--work", str(work), "--tag", f"{label}-{cfg}", "--designs", design, "--seeds", seeds,
            "--arms", c["arms"], "--odin-meta", str(root / "netlists" / c["net"] / design / "netlist" / "odin-meta.json")]
    if c["vpr"]:
        argv += ["--vpr-extra", c["vpr"]]
    argv += c.get("extra", [])
    return subprocess.run(argv, env=env).returncode


def run_dirs(root, label, cfg, design):
    """(record path, VPR run dir) of every finished run of (label, config, design)."""
    base = root / "vpr" / f"{label}-{cfg}" / design
    out = []
    for rec in sorted(base.glob("*/mimir-run.json")):
        d = rec.parent
        v = d / "vpr" if (d / "vpr").is_dir() and not list(d.glob("*.net")) else d
        if list(v.glob("*.net")) and list(v.glob("*.place")):
            out.append((rec, v))
    return out


def odin_top(root, netkey, design):
    m = re.search(r"stats: design: modules \d+, top (\S+)", (root / "netlists" / netkey / design / "netlist" / "odin.log").read_text())
    return m.group(1) if m else ""


INFRA_RC = (125, 127)  # /usr/bin/time could not run its command (125) or the command was not found (127): the tool did not run


def is_infra_record(r):
    """An infrastructure failure (docs/plan/e10.md section 12): a step exited 125 or 127, or the run took no time. The tool did not run; this says nothing about the design."""
    return any(st.get("exit_code") in INFRA_RC for st in r.get("steps", [])) or not r.get("time_s")


def quarantine_failed_records(root, label, cfg, design):
    """Guard (docs/plan/e10.md sections 11 and 12): a run record of an infrastructure failure (a step exit code 125 or 127, or time_s 0) never reaches the store.
    The record file is renamed to mimir-run.json.failed (not deleted) and logged in <root>/failed-records.log. A run that ran and failed (rc other than 0, 125, 127; for example
    a VPR error or a readback fault) is a result: its record stays and is stored as a run row (rc, time) without quality records."""
    for rec in sorted((root / "vpr" / f"{label}-{cfg}" / design).glob("*/mimir-run.json")):
        try:
            bad = is_infra_record(json.loads(rec.read_text()))
        except (OSError, ValueError):
            bad = True
        if bad:
            rec.rename(rec.with_name("mimir-run.json.failed"))
            with open(root / "failed-records.log", "a") as f:
                f.write(f"{time.strftime('%FT%TZ', time.gmtime())} {label}-{cfg} {design} {rec.parent.name}: record not imported (infrastructure failure)\n")
            print(f"{label}-{cfg} {design} {rec.parent.name}: infrastructure failure, record not imported", flush=True)


def structures(root, label, cfg, design, db):
    """Extend the name map of every run of a Norns design with its packing and placement (odin3 prov_post), then store the structure rows."""
    net = CONFIGS[cfg]["net"]
    nd = root / "netlists" / net / design / "netlist"
    quarantine_failed_records(root, label, cfg, design)
    jobs = []
    for rec, v in ([] if design in MCNC20 else run_dirs(root, label, cfg, design)):  # MCNC circuits have no HDL: run records only, no structure rows
        r = json.loads(rec.read_text())
        w = root / "struct" / f"{label}-{cfg}" / design / rec.parent.name
        mp = w / "odin3" / f"{design}.blif.names"
        if not mp.is_file():
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_bytes((nd / f"{design}.blif.names").read_bytes())
            p = subprocess.run([sys.executable, str(ODIN_TREE / "tools/flow/prov_post.py"), str(w), "--blif", str(nd / f"{design}.blif"), "--map", str(mp), "--run-dir", str(v),
                                "--top", odin_top(root, net, design)], capture_output=True, text=True)
            (w / "prov-post.log").write_text(p.stdout + p.stderr)
            if p.returncode:
                print(f"{rec.parent.name}: prov_post FAILED", flush=True)
                mp.rename(mp.with_name(mp.name + ".failed"))
                continue
        jobs.append({"source": r["source"], "design": design, "arch": r["arch"], "seed": r["seed"], "arm": r["arm"], "slug": f"e10/{design}",
                     "blif": str(nd / f"{design}.blif"), "map": str(mp), "files": [str(nl.design_verilog(design))], "suite": "norns-e10"})
    quarantine_failed_records(root, label, cfg, design)
    jf = root / "struct" / f"{label}-{cfg}" / design / "jobs.json"
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text(json.dumps(jobs, indent=1))
    env = dict(os.environ, PYTHONPATH=str(MIMIR), MIMIR_ODIN3_TREE=str(ODIN_TREE), MIMIR_LOKI_SRC=str(nl.WS_ROOT / "loki"), VTR_ROOT=str(VTR))
    rc1 = subprocess.run([MIMIR_PY, "-m", "mimir.cli", "import-runrecords", str(db), str(root / "vpr" / f"{label}-{cfg}" / design)], env=env, capture_output=True, text=True)
    (jf.parent / "import-runrecords.log").write_text(rc1.stdout + rc1.stderr)
    rc2 = subprocess.run([MIMIR_PY, "-m", "mimir.structnorns", str(db), str(jf)], env=env, capture_output=True, text=True)
    (jf.parent / "structnorns.log").write_text(rc2.stdout + rc2.stderr)
    print(f"{label}-{cfg} {design}: {len(jobs)} runs; import-runrecords rc {rc1.returncode}, structnorns rc {rc2.returncode}", flush=True)
    return rc1.returncode or rc2.returncode


def is_infra_result(r):
    """A result of data/placers whose tool did not run (exit code 125 or 127, in the result or in its nextpnr step)."""
    return r.get("rc") in INFRA_RC or (r.get("nextpnr") or {}).get("rc") in INFRA_RC


def failures(root, label, cfg):
    """(designs done, designs failing) of a config. Done = designs with a result file; failing = a run that is not rc 0 and legally routed after its retry, or an error.
    Infrastructure failures (is_infra_result) are not design failures and do not count as failing (docs/plan/e10.md section 12)."""
    run = bad = 0
    for f in sorted((root / "data" / "placers").glob(f"{label}-{cfg}_*.json")):
        d = json.loads(f.read_text())
        run += 1
        bad += any((r["rc"] != 0 or not r.get("routed_ok")) and not is_infra_result(r) for r in d["runs"]) or bool(d.get("error"))
    return run, bad


def sweep(root, a, designs):
    import sqlite3
    stopped_f = root / "stopped-configs.json"
    stopped = json.loads(stopped_f.read_text()) if stopped_f.is_file() else {}
    cfgs = [c for c in a.configs.split(",") if c not in stopped]
    for d in designs:
        if a.no_new_design_after and time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) > a.no_new_design_after:
            print(f"## no new design after {a.no_new_design_after}: stopping before {d}", flush=True)
            return
        free_c = shutil.disk_usage("/mnt/c").free / 1e9
        if free_c < 30:
            sys.exit(f"stop rule 4: /mnt/c has {free_c:.0f} GB free")
        print(f"## {d} start {time.strftime('%FT%TZ', time.gmtime())} /mnt/c free {free_c:.0f} GB; " + subprocess.run(["free", "-g"], capture_output=True, text=True).stdout.splitlines()[1], flush=True)
        for cfg in cfgs:
            print(f"== {a.label}-{cfg} {d}", flush=True)
            run_config(root, a.label, cfg, d, a.seeds)
        for cfg in cfgs:
            structures(root, a.label, cfg, d, a.db)
        subprocess.run([sys.executable, "-I", EVICT] + [str(root / "vpr" / f"{a.label}-{c}" / d) for c in cfgs] + [str(root / "netlists")])
        for cfg in list(cfgs):  # the counter is the number of designs done overall (result files), not the position in this process's list (docs/plan/e10.md section 12)
            run, bad = failures(root, a.label, cfg)
            if run >= 5 and bad / run > 0.2:
                print(f"STOP RULE 1: config {cfg} stopped, it fails on {bad} of {run} designs", flush=True)
                cfgs.remove(cfg)
                stopped[cfg] = {"after_design": d, "designs_run": run, "designs_failing": bad}
                stopped_f.write_text(json.dumps(stopped, indent=1) + "\n")
        con = sqlite3.connect(a.db)
        orphan = con.execute("select count(*) from structure_mapping m left join run r on r.run_id=m.run_id where r.run_id is null").fetchone()[0]
        con.close()
        if orphan:
            sys.exit(f"stop rule 2: {orphan} structure_mapping rows without a run record")
        print(f"## {d} done {time.strftime('%FT%TZ', time.gmtime())}", flush=True)


EVICT = os.environ.get("E10_EVICT", str(nl.WS_ROOT / "work" / "controller-scripts" / "evict.py"))
MIMIR = Path(os.environ.get("E10_MIMIR", str(nl.WS_ROOT / "work" / "mimir-e10")))
MIMIR_PY = os.environ.get("E10_MIMIR_PY", str(nl.WS_ROOT / "work" / "mimir-venv" / "bin" / "python"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage", required=True, choices=("netlists", "order", "runs", "structures", "sweep"))
    ap.add_argument("--designs", default="")
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--label", default="e10")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--db", default="")
    ap.add_argument("--no-new-design-after", default="", help="UTC time YYYY-MM-DDTHH:MM:SSZ; the sweep starts no design after it (a design that has started finishes)")
    a = ap.parse_args()
    root = Path(a.root)
    if not root.is_absolute():
        sys.exit(f"--root must be an absolute path (a relative root broke the 2026-10-28 relaunch): {a.root}")
    designs = a.designs.split(",") if a.designs else list(MCNC20 + NORNS15)
    if a.stage == "netlists":
        for nk in NETKEYS:
            for d in designs:
                b = netlist(root, nk, d)
                print(nk, d, "ok" if b else "FAILED", flush=True)
    elif a.stage == "order":
        ordered, sizes = order(root, designs)
        print(json.dumps([[d, sizes[d]] for d in ordered]))
    elif a.stage == "sweep":
        sweep(root, a, designs)
    elif a.stage == "structures":
        for d in designs:
            for cfg in a.configs.split(","):
                structures(root, a.label, cfg, d, a.db)
    else:
        for d in designs:
            for cfg in a.configs.split(","):
                print(f"== {a.label}-{cfg} {d}", flush=True)
                run_config(root, a.label, cfg, d, a.seeds)


if __name__ == "__main__":
    main()
