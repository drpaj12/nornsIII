"""Dispatch 4 driver: VPR arms and nextpnr (k6 viaduct uarch, rule H0) arms for one or more designs (docs/plan/placers.md section 10).

Usage: . scripts/env.sh; NORNS_LOCK=/tmp/claude-1000/norns-vpr.lock python3 scripts/placers_main.py \
         --work WORKDIR --tag TAG --designs d1,d2 [--seeds 1,2,3] [--arms vpr_ap,vpr_ap_reread,vpr_sa,vpr_sa_reread,ext_nextpnr_heap,ext_nextpnr_sa] \
         [--temps 1,3,10] [--sa-temp T]
WORKDIR is a fresh `mktemp -d /tmp/claude-1000/npl-XXXX` (raw outputs stay there; nothing is deleted). Every VPR run takes the Norns
lock; nextpnr runs take none. Metrics go to data/placers/<TAG>_<design>.json (no absolute paths, no atom names). The file is rewritten
after every run and a re-run with the same WORKDIR and TAG skips the records already present (resume).
The reference of all external arms (pads, hard-block positions, atom list) is the `vpr_ap` seed-1 final.flat_place of the same design
(run first and always, whether or not `vpr_ap` is among the arms). `ext_nextpnr_sa` runs once per value of --temps (default: --sa-temp,
default 1; nextpnr's default), the others once. Environment: NEXTPNR_K6, NEXTPNR_LIBS as in placers_gate.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import nornlib as nl

ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True)
ap.add_argument("--tag", required=True)
ap.add_argument("--designs", required=True)
ap.add_argument("--seeds", default="1,2,3")
ap.add_argument("--arms", default="vpr_ap,vpr_ap_reread,vpr_sa,vpr_sa_reread,ext_nextpnr_heap,ext_nextpnr_sa")
ap.add_argument("--temps", default=None, help="comma list of --starttemp values for ext_nextpnr_sa (default: --sa-temp)")
ap.add_argument("--sa-temp", type=float, default=1.0)
ap.add_argument("--max-rss-gb", type=float, default=13.0)
args = ap.parse_args()

WORK = Path(args.work)
SEEDS = [int(s) for s in args.seeds.split(",")]
ARMS = args.arms.split(",")
TEMPS = [float(t) for t in (args.temps or str(args.sa_temp)).split(",")]
VPR = Path(os.environ["NORNS_VPR"])
NPNR = os.environ.get("NEXTPNR_K6", "/tmp/claude-1000/nextpnr-k6-build/nextpnr-generic")
LIBS = os.environ.get("NEXTPNR_LIBS", "/tmp/claude-1000/nextpnr-deps/prefix/lib")
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
PERSEED_ARMS = ("vpr_ap", "vpr_ap_reread", "vpr_sa", "vpr_sa_reread", "ext_nextpnr_heap", "ext_nextpnr_sa")


def vpr(cwd, flags, seed, blif, write=None, read=None):
    nl.ensure_dir(cwd)
    flags = flags + ["--seed", str(seed), "--timing_report_npaths", "200", "--route_file", "/dev/null"]
    if write:
        flags += ["--write_flat_place", str(cwd / write)]
    if read:
        flags += ["--read_flat_place", str(read)]
    log = cwd / "vpr.out"
    cmd = ["flock", "-x", str(nl.LOCK), str(VPR), str(nl.ARCH), str(blif)] + flags
    rc = nl.run(cmd, cwd=cwd, stdout=log, timeout=7200)
    text = log.read_text(errors="replace")
    rec = {"rc": rc}
    for k, rx in RX.items():
        m = rx.search(text)
        rec[k] = float(m.group(1)) if m else None
    rec["routed_ok"] = "Circuit successfully routed" in text
    rec["reader_warnings"] = len(re.findall(r"Flat placement file, line", text))
    m = re.search(r"FPGA sized to (\d+) x (\d+)", text)
    rec["grid"] = [int(m.group(1)), int(m.group(2))] if m else None
    if rc or not rec["routed_ok"]:
        errs = [ln for ln in text.splitlines() if "Error" in ln or "error" in ln][:3]
        rec["error"] = " | ".join(e.strip()[:300] for e in errs)
    return rec


def run_py(script, *a):
    t = time.time()
    p = subprocess.run([sys.executable, str(HERE / script), *a], capture_output=True, text=True)
    if p.returncode:
        print(p.stdout, p.stderr, file=sys.stderr)
    return p.returncode, time.time() - t


def nextpnr(cwd, js, anchors, grid, placer, seed, temp):
    nl.ensure_dir(cwd)
    cmd = ["/usr/bin/time", "-v", NPNR, "--uarch", "k6", "--vopt", f"width={grid[0]}", "--vopt", f"height={grid[1]}"]
    if anchors.exists() and anchors.stat().st_size:
        cmd += ["--vopt", f"anchors={anchors}"]
    cmd += ["--json", str(js), "--no-route", "--placer", placer, "--seed", str(seed), "--write", str(cwd / "placed.json")]
    if placer == "sa":
        cmd += ["--starttemp", str(temp)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, LD_LIBRARY_PATH=LIBS), timeout=14400)
    wall = time.time() - t0
    txt = p.stdout + p.stderr
    (cwd / "nextpnr.log").write_text(txt)
    g = lambda rx: (float(m.group(1)) if (m := re.search(rx, txt)) else None)
    rec = {"rc": p.returncode, "wall_s": wall, "heap_s": g(r"HeAP Placer Time: ([0-9.]+)s"), "sa_s": g(r"SA placement time ([0-9.]+)s"),
           "init_s": g(r"Initial placement time ([0-9.]+)s"), "max_rss_kb": g(r"Maximum resident set size \(kbytes\): (\d+)")}
    m = re.findall(r"wirelen = (\d+)", txt)
    rec["hpwl_final"] = int(m[-1]) if m else None
    return rec


def process(design):
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    dst = nl.DATA / "placers" / f"{args.tag}_{design}.json"
    out = json.loads(dst.read_text()) if dst.exists() else {"design": design, "tag": args.tag, "runs": [], "converter": {}}
    done = {(r["arm"], r["seed"], r.get("starttemp")): r for r in out["runs"]}
    wd = nl.ensure_dir(WORK / design)

    def save():
        dst.write_text(json.dumps(out, indent=1) + "\n")

    def record(rec):
        out["runs"].append(rec)
        done[(rec["arm"], rec["seed"], rec.get("starttemp"))] = rec
        save()
        keys = ("rc", "routed_ok", "wl", "W", "cpd_ns", "reader_warnings", "wall_s", "sa_s", "heap_s", "error")
        print(design, rec["arm"], "s%d" % rec["seed"], "T=%s" % rec.get("starttemp"), {k: rec[k] for k in keys if k in rec}, flush=True)

    def vrun(arm, seed, flags, write=None, read=None, extra=None, tdir=None):
        key = (arm, seed, (extra or {}).get("starttemp"))
        if key in done:
            return done[key]
        cwd = wd / (tdir or f"{arm}.s{seed}")
        rec = vpr(cwd, flags, seed, blif, write=write, read=read)
        if rec["rc"]:  # a failed run is retried once (Section 5 rule 4)
            rec = vpr(cwd, flags, seed, blif, write=write, read=read) | {"retried": True}
        rec |= {"arm": arm, "seed": seed} | (extra or {})
        record(rec)
        return rec

    # reference run (also the shared vpr_ap seed-1 run)
    r1 = vrun("vpr_ap", 1, [], write="final.flat_place")
    ref = wd / "vpr_ap.s1" / "final.flat_place"
    grid = r1["grid"]
    out["reference"] = {"arm": "vpr_ap", "seed": 1, "grid": grid}
    if r1["rc"] or not ref.exists():
        out["error"] = "reference run failed"
        save()
        return
    ext = nl.ensure_dir(wd / "ext")
    js, anchors = ext / f"{design}.json", ext / f"{design}.json.anchors.txt"
    if not out["converter"].get("ok") or not js.exists():
        rc, sec = run_py("nextpnr_blif2json.py", "--blif", str(blif), "--ref", str(ref), "--out", str(js),
                         "--stats", str(ext / "convert_stats.json"), "--anchors", str(anchors))
        st = json.loads((ext / "convert_stats.json").read_text()) if (ext / "convert_stats.json").exists() else {}
        out["converter"] = {"rc": rc, "seconds": sec, **{k: v for k, v in st.items() if k != "ref_atoms_without_cell"}}
        save()
        if rc:
            out["error"] = "converter failed"
            save()
            return
    for s in SEEDS:
        for arm in ARMS:
            if arm == "vpr_ap":
                vrun("vpr_ap", s, [], write="final.flat_place")
            elif arm == "vpr_ap_reread":
                vrun("vpr_ap", s, [], write="final.flat_place")
                vrun("vpr_ap_reread", s, [], read=wd / f"vpr_ap.s{s}" / "final.flat_place")
            elif arm == "vpr_sa":
                vrun("vpr_sa", s, SA, write="final.flat_place")
            elif arm == "vpr_sa_reread":
                vrun("vpr_sa", s, SA, write="final.flat_place")
                vrun("vpr_sa_reread", s, [], read=wd / f"vpr_sa.s{s}" / "final.flat_place")
            elif arm in ("ext_nextpnr_heap", "ext_nextpnr_sa"):
                placer = arm.rsplit("_", 1)[1]
                for T in (TEMPS if placer == "sa" else [None]):
                    extra = {"starttemp": T} if T is not None else {}
                    if (arm, s, T) in done:
                        continue
                    tag = f"{arm}.s{s}" + (f".t{T:g}" if T is not None else "")
                    cwd = wd / tag
                    np_rec = nextpnr(cwd, js, anchors, grid, placer, s, T)
                    if np_rec["rc"]:
                        np_rec = nextpnr(cwd, js, anchors, grid, placer, s, T) | {"retried": True}
                    rec = {"arm": arm, "seed": s, "nextpnr": np_rec} | extra
                    if np_rec["max_rss_kb"] and np_rec["max_rss_kb"] > args.max_rss_gb * 1e6:
                        rec |= {"rc": -1, "routed_ok": False, "error": "nextpnr memory over the stop limit"}
                        record(rec)
                        sys.exit("memory stop rule")
                    if np_rec["rc"]:
                        rec |= {"rc": np_rec["rc"], "routed_ok": False, "error": "nextpnr failed"}
                        record(rec)
                        continue
                    rc2, sec2 = run_py("nextpnr_readback.py", "--json", str(cwd / "placed.json"), "--ref", str(ref),
                                       "--out", str(cwd / "ext.flat_place"), "--stats", str(cwd / "rb.json"))
                    rec["readback"] = json.loads((cwd / "rb.json").read_text()) if (cwd / "rb.json").exists() else {}
                    rec["readback_s"] = sec2
                    if rc2:
                        rec |= {"rc": rc2, "routed_ok": False, "error": "readback failed"}
                        record(rec)
                        continue
                    v = vpr(cwd / "vpr", [], s, blif, read=cwd / "ext.flat_place")
                    if v["rc"]:
                        v = vpr(cwd / "vpr", [], s, blif, read=cwd / "ext.flat_place") | {"retried": True}
                    rec |= v
                    record(rec)
            else:
                sys.exit(f"unknown arm {arm}")


for d in args.designs.split(","):
    process(d)
print("done", args.designs)
