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
ODIN_BIN = Path(os.environ.get("E10_ODIN_BIN", "/tmp/claude-1000/e10-odin3-build/odin3"))
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
    "k4": {"net": "k4", "arch": "k4", "vpr": "", "arms": "vpr_sa"},
    "earch": {"net": "earch", "arch": "earch", "vpr": "", "arms": "vpr_sa"},
    "uon": {"net": "base", "arch": "norns", "vpr": "--allow_unrelated_clustering on", "arms": "vpr_sa"},
    "uoff": {"net": "base", "arch": "norns", "vpr": "--allow_unrelated_clustering off", "arms": "vpr_sa"},
    "plc": {"net": "base", "arch": "norns", "vpr": "", "arms": "vpr_ap,ext_nextpnr_heap,ext_nextpnr_sa"},
}


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
    e = rr.tool_entry(ODIN_TREE, ODIN_BIN, copy=ODIN_TREE if (same_home and newer) else None)
    e["build_facts"] = {"cmake_home_is_tree": same_home, "binary_newer_than_commit": bool(newer)}
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
    argv = [str(ODIN_BIN), "-p", script]
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
        params += [["odin.abc_script", "lib/abc/vtr.abc", "default", f"odin3 {head} lib/abc/vtr.abc:1-10 (the built-in script used when no --script is given; docs/DESIGN.md line 225)"],
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
    return subprocess.run(argv, env=env).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--stage", required=True, choices=("netlists", "order", "runs"))
    ap.add_argument("--designs", default="")
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--label", default="e10")
    ap.add_argument("--seeds", default="1,2,3")
    a = ap.parse_args()
    root = Path(a.root)
    designs = a.designs.split(",") if a.designs else list(MCNC20 + NORNS15)
    if a.stage == "netlists":
        for nk in NETKEYS:
            for d in designs:
                b = netlist(root, nk, d)
                print(nk, d, "ok" if b else "FAILED", flush=True)
    elif a.stage == "order":
        ordered, sizes = order(root, designs)
        print(json.dumps([[d, sizes[d]] for d in ordered]))
    else:
        for d in designs:
            for cfg in a.configs.split(","):
                print(f"== {a.label}-{cfg} {d}", flush=True)
                run_config(root, a.label, cfg, d, a.seeds)


if __name__ == "__main__":
    main()
