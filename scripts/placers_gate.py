"""Dispatch 3 first gate: VPR arms and nextpnr (k6 viaduct uarch) arms, one design, seeds given (docs/plan/placers.md section 9).

Usage: . scripts/env.sh; NORNS_LOCK=/tmp/claude-1000/norns-vpr.lock python3 scripts/placers_gate.py WORKDIR DESIGN [SEEDS e.g. 1,2,3]
WORKDIR is a fresh `mktemp -d /tmp/claude-1000/npl-XXXX` (raw outputs stay there; nothing is deleted). Every VPR run takes
the Norns lock; nextpnr runs take none. Writes data/placers/gate_<DESIGN>.json (metrics only).
Environment: NORNS_TMP (default /tmp/claude-1000), NEXTPNR_K6 (default $NORNS_TMP/nextpnr-k6-build/nextpnr-generic), NEXTPNR_LIBS
(default $NORNS_TMP/nextpnr-deps/prefix/lib).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import nornlib as nl

WORK = Path(sys.argv[1])
DESIGN = sys.argv[2]
SEEDS = [int(s) for s in (sys.argv[3] if len(sys.argv) > 3 else "1,2,3").split(",")]
BLIF = nl.runs_dir(DESIGN, "netlist", f"{DESIGN}.blif")
VPR = Path(os.environ["NORNS_VPR"])
TMP = os.environ.get("NORNS_TMP", "/tmp/claude-1000")
NPNR = os.environ.get("NEXTPNR_K6", f"{TMP}/nextpnr-k6-build/nextpnr-generic")
LIBS = os.environ.get("NEXTPNR_LIBS", f"{TMP}/nextpnr-deps/prefix/lib")
HERE = Path(__file__).resolve().parent
RX = {
    "pack_s": re.compile(r"#+ Packing took ([0-9.]+) seconds"),
    "ap_s": re.compile(r"Analytical Placement took ([0-9.]+) seconds"),
    "sa_place_s": re.compile(r"# SA Placement took ([0-9.]+) seconds"),
    "route_s": re.compile(r"# Routing took ([0-9.]+) seconds"),
    "flow_s": re.compile(r"The entire flow of VPR took ([0-9.]+) seconds"),
    "wl": re.compile(r"\tTotal wirelength: ([0-9.]+),"),
    "cpd_ns": re.compile(r"Final critical path delay \(least slack\): ([0-9.]+) ns"),
    "W": re.compile(r"Best routing used a channel width factor of ([0-9]+)\."),
    "clbs": re.compile(r"(\d+)\s+blocks of type: clb"),
}
SA = ["--pack", "--place", "--route", "--analysis"]


def vpr(tag, flags, seed, write=None, read=None):
    cwd = WORK / tag
    nl.ensure_dir(cwd)
    flags = flags + ["--seed", str(seed), "--timing_report_npaths", str(nl.npaths(200)), "--route_file", "/dev/null"]
    if write:
        flags += ["--write_flat_place", str(cwd / write)]
    if read:
        flags += ["--read_flat_place", str(read)]
    log = cwd / "vpr.out"
    cmd = ["flock", "-x", str(nl.LOCK), str(VPR), str(nl.ARCH), str(BLIF)] + flags
    rc = nl.run(cmd, cwd=cwd, stdout=log, timeout=7200)
    text = log.read_text(errors="replace")
    rec = {"arm": tag.split(".s")[0], "seed": seed, "rc": rc}
    for k, rx in RX.items():
        m = rx.search(text)
        rec[k] = float(m.group(1)) if m else None
    rec["routed_ok"] = "Circuit successfully routed" in text
    if rc == 0:
        rec["keep"] = nl.keep_timing(cwd, cwd, DESIGN, BLIF, nl.name_map_of(BLIF))
    rec["reader_warnings"] = len(re.findall(r"Flat placement file, line", text))
    m = re.search(r"FPGA sized to (\d+) x (\d+)", text)
    rec["grid"] = [int(m.group(1)), int(m.group(2))] if m else None
    print(tag, {k: rec[k] for k in ("rc", "routed_ok", "wl", "W", "cpd_ns", "reader_warnings")}, flush=True)
    return rec


def run_py(script, *args):
    t = time.time()
    p = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    if p.returncode:
        print(p.stdout, p.stderr, file=sys.stderr)
    return p.returncode, time.time() - t, p.stdout


out = {"design": DESIGN, "seeds": SEEDS, "runs": [], "nextpnr": [], "converter": {}}
ref = None
for s in SEEDS:
    r = vpr(f"vpr_ap.s{s}", [], s, write="final.flat_place")
    out["runs"].append(r)
    if s == 1 or ref is None:
        ref = WORK / f"vpr_ap.s{s}" / "final.flat_place"
        grid = r["grid"]
        refseed = s
out["reference"] = {"arm": "vpr_ap", "seed": refseed, "grid": grid}
for s in SEEDS:
    out["runs"].append(vpr(f"vpr_ap_reread.s{s}", [], s, read=WORK / f"vpr_ap.s{s}" / "final.flat_place"))
    out["runs"].append(vpr(f"vpr_sa.s{s}", SA, s, write="final.flat_place"))
    out["runs"].append(vpr(f"vpr_sa_reread.s{s}", [], s, read=WORK / f"vpr_sa.s{s}" / "final.flat_place"))
nl.ensure_dir(WORK / "ext")
js = WORK / "ext" / f"{DESIGN}.json"
rc, sec, so = run_py("nextpnr_blif2json.py", "--blif", str(BLIF), "--ref", str(ref), "--out", str(js),
                     "--stats", str(WORK / "ext" / "convert_stats.json"))
out["converter"] = {"rc": rc, "seconds": sec, **json.loads((WORK / "ext" / "convert_stats.json").read_text())}
if rc:
    sys.exit("converter failed")
env = dict(os.environ, LD_LIBRARY_PATH=LIBS)
for placer in ("heap", "sa"):
    for s in SEEDS:
        tag = f"ext_nextpnr_{placer}.s{s}"
        cwd = WORK / tag
        nl.ensure_dir(cwd)
        t0 = time.time()
        p = subprocess.run(["/usr/bin/time", "-v", NPNR, "--uarch", "k6", "--vopt", f"width={grid[0]}", "--vopt",
                            f"height={grid[1]}", "--json", str(js), "--no-route", "--placer", placer, "--seed", str(s),
                            "--write", str(cwd / "placed.json")], capture_output=True, text=True, env=env)
        wall = time.time() - t0
        (cwd / "nextpnr.log").write_text(p.stdout + p.stderr)
        txt = p.stdout + p.stderr
        g = lambda rx: (float(m.group(1)) if (m := re.search(rx, txt)) else None)
        rec = {"arm": f"ext_nextpnr_{placer}", "seed": s, "rc": p.returncode, "wall_s": wall,
               "heap_s": g(r"HeAP Placer Time: ([0-9.]+)s"), "sa_s": g(r"SA placement time ([0-9.]+)s"),
               "init_s": g(r"Initial placement time ([0-9.]+)s"), "max_rss_kb": g(r"Maximum resident set size \(kbytes\): (\d+)"),
               "hpwl_final": None}
        m = re.findall(r"wirelen = (\d+)", txt)
        rec["hpwl_final"] = int(m[-1]) if m else None
        rc2 = 1
        if p.returncode == 0:
            rc2, sec2, so2 = run_py("nextpnr_readback.py", "--json", str(cwd / "placed.json"), "--ref", str(ref),
                                    "--out", str(cwd / "ext.flat_place"), "--stats", str(cwd / "rb.json"))
            rec["readback"] = json.loads((cwd / "rb.json").read_text())
            rec["readback_s"] = sec2
        out["nextpnr"].append(rec)
        print(tag, {k: rec[k] for k in ("rc", "wall_s", "heap_s", "sa_s", "hpwl_final")}, rec.get("readback"), flush=True)
        if rc2 == 0:
            out["runs"].append(vpr(tag + ".vpr", [], s, read=cwd / "ext.flat_place") | {"arm": f"ext_nextpnr_{placer}"})
dst = nl.DATA / "placers" / f"gate_{DESIGN}.json"
dst.write_text(json.dumps(out, indent=1) + "\n")
print("wrote", dst)
