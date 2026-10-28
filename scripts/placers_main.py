"""Dispatch 4 driver: VPR arms and nextpnr (k6 viaduct uarch, rule H0) arms for one or more designs (docs/plan/placers.md section 10).

Usage: . scripts/env.sh; NORNS_LOCK=/tmp/claude-1000/norns-vpr.lock python3 scripts/placers_main.py \
         --work WORKDIR --tag TAG --designs d1,d2 [--seeds 1,2,3] [--arms vpr_ap,vpr_ap_reread,vpr_sa,vpr_sa_reread,ext_nextpnr_heap,ext_nextpnr_sa] \
         [--temps 1,3,10] [--sa-temp T]
WORKDIR is a fresh `mktemp -d /tmp/claude-1000/npl-XXXX` (raw outputs stay there; nothing is deleted). Every VPR run takes the Norns
lock; a nextpnr run takes it too when an earlier run of the same arm and design lasted over 10 min. Metrics go to data/placers/<TAG>_<design>.json (no absolute paths, no atom names). The file is rewritten
after every run and a re-run with the same WORKDIR and TAG skips the records already present (resume).
The reference of all external arms (pads, hard-block positions, atom list) is the `vpr_ap` seed-1 final.flat_place of the same design
(run first and always, whether or not `vpr_ap` is among the arms). `ext_nextpnr_sa` runs once per value of --temps (default: --sa-temp,
default 1; nextpnr's default), the others once. Environment: NEXTPNR_K6, NEXTPNR_LIBS as in placers_gate.py; NORNS_TMP (default /tmp/claude-1000) is the base of their defaults.
Dedicated fix round (section 10.10): use --tag fix1 and --work runs-fix1 (a path under the checkout, not committed).
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

ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True)
ap.add_argument("--tag", required=True)
ap.add_argument("--designs", required=True)
ap.add_argument("--seeds", default="1,2,3")
ap.add_argument("--arms", default="vpr_ap,vpr_ap_reread,vpr_sa,vpr_sa_reread,ext_nextpnr_heap,ext_nextpnr_sa")
ap.add_argument("--temps", default=None, help="comma list of --starttemp values for ext_nextpnr_sa (default: --sa-temp)")
ap.add_argument("--sa-temp", type=float, default=1.0)
ap.add_argument("--redo-failed", action="store_true", help="drop failed records (kept under first_attempt_failures) and, for a converter older than section 10.7, all ext_* records")
ap.add_argument("--max-rss-gb", type=float, default=13.0)
args = ap.parse_args()

WORK = Path(args.work)
SEEDS = [int(s) for s in args.seeds.split(",")]
ARMS = args.arms.split(",")
TEMPS = [float(t) for t in (args.temps or str(args.sa_temp)).split(",")]
VPR = Path(os.environ["NORNS_VPR"])
TMP = os.environ.get("NORNS_TMP", "/tmp/claude-1000")  # base of the third-party build trees and the locks (default: the value used so far)
NPNR = os.environ.get("NEXTPNR_K6", f"{TMP}/nextpnr-k6-build/nextpnr-generic")
LIBS = os.environ.get("NEXTPNR_LIBS", f"{TMP}/nextpnr-deps/prefix/lib")
NP_LOCK_AFTER_S = 600.0  # a nextpnr run expected to exceed this (an earlier run of the same arm and design did) takes the Norns lock, like VPR
HERE = Path(__file__).resolve().parent
NEXTPNR_SRC = Path(os.environ.get("NEXTPNR_SRC", str(nl.WS_ROOT / "external" / "nextpnr")))  # the clone nextpnr-k6 was exported from (read only)
VPR_TREE = Path(os.environ.get("NORNS_VTR", str(VPR.parents[2])))  # source tree of the VPR binary
STEPS: list[dict] = []  # tool steps since the last record was written (see write_record)
TOOLS: dict[str, dict] = {}  # tool entries, computed once per process
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
FAMILY = {"vpr_ap": "analytic", "vpr_ap_reread": "analytic", "vpr_sa": "annealing", "vpr_sa_reread": "annealing", "ext_nextpnr_heap": "analytic", "ext_nextpnr_sa": "annealing"}  # placer family of the arm
PERSEED_ARMS = ("vpr_ap", "vpr_ap_reread", "vpr_sa", "vpr_sa_reread", "ext_nextpnr_heap", "ext_nextpnr_sa")


def vpr(cwd, flags, seed, blif, write=None, read=None):
    nl.ensure_dir(cwd)
    flags = flags + ["--seed", str(seed), "--timing_report_npaths", "200", "--route_file", "/dev/null"]
    if write:
        flags += ["--write_flat_place", str(cwd / write)]
    if read:
        flags += ["--read_flat_place", str(read)]
    log = cwd / "vpr.out"
    argv = [str(VPR), str(nl.ARCH), str(blif)] + flags
    tfile = cwd / "time.txt"
    cmd = ["flock", "-x", str(nl.LOCK), "/usr/bin/time", "-v", "-o", str(tfile)] + argv
    rc = nl.run(cmd, cwd=cwd, stdout=log, timeout=7200)
    secs, rss = rr.parse_time_v(tfile.read_text(errors="replace")) if tfile.exists() else (0.0, 0.0)
    STEPS.append({"kind": "vpr", "argv": argv, "rc": rc, "secs": secs, "rss": rss, "log": log})
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
        # the lines matching analytical_placement|conflicts|Error, each with the line that follows (section 10.10)
        ls = text.splitlines()
        keep = []
        for i, ln in enumerate(ls):
            if re.search(r"analytical_placement|conflicts|Error", ln):
                keep.append(ln.strip()[:400])
                if i + 1 < len(ls) and ls[i + 1].strip():
                    keep.append(ls[i + 1].strip()[:400])
        rec["error"] = " | ".join(keep[:8]).replace(str(nl.WS_ROOT), "$WS").replace(str(Path.home()), "~")  # no absolute home paths in committed records
    return rec


def tool(name):
    """The run-record entry of a tool (HEAD of its tree, clean flag, binary sha256, --version text); once per process."""
    if name not in TOOLS:
        if name == "vpr":
            TOOLS[name] = rr.tool_entry(VPR_TREE, VPR)
        elif name == "nextpnr":
            TOOLS[name] = rr.tool_entry(NEXTPNR_SRC, Path(NPNR), env={"LD_LIBRARY_PATH": LIBS})
        else:  # the Norns scripts, run from this checkout
            TOOLS[name] = rr.tool_entry(nl.WS, Path(__file__), version_args=None)
    return TOOLS[name]


def write_record(cwd, design, arm, seed, family, blif, roles=None, inputs=None, artifacts=None, placer=None):
    """Write <cwd>/mimir-run.json from the tool steps run since the last record (docs/specs/2026-10-28-mimir-run-record.md in mimirIII)."""
    steps, STEPS[:] = list(STEPS), []
    r = rr.RunRecorder(f"norns-placers-{args.tag}", design, arm, seed, family, nl.ARCH.stem,
                       roots={"run": cwd, "work": WORK, "norns_vtr": VPR_TREE, "vtr": nl.VTR_ROOT, "runs": nl.RUNS, "tmp": Path(TMP)},
                       roles={Path(NPNR): "<nextpnr>", VPR: "<vpr>", nl.ARCH: "<arch>", blif: "<blif>"} | {Path(k): v for k, v in (roles or {}).items()})
    for s in steps:
        r.add_step(s["kind"], s["argv"], s["rc"], s["secs"], s["rss"], locked=True)
    kinds = {s["kind"] for s in steps}
    for k in ("vpr", "nextpnr"):
        if k in kinds:
            r.add_tool(k, tool(k))
    r.add_tool("norns", tool("norns"))
    vsteps = [s for s in steps if s["kind"] == "vpr"]
    if vsteps:
        r.add_vpr_params(vsteps[-1]["argv"], vsteps[-1]["log"], VPR_TREE / "vpr/src/base/read_options.cpp", "vtr-tree")
    nsteps = [s for s in steps if s["kind"] == "nextpnr"]
    if nsteps:
        r.add_nextpnr_params(nsteps[-1]["argv"], NEXTPNR_SRC, "nextpnr", placer)
    r.add_input("netlist", blif)
    r.add_input("arch", nl.ARCH)
    for role, path in (inputs or {}).items():
        r.add_input(role, path)
    for role, path in (artifacts or {}).items():
        r.add_artifact(role, path)
    r.write(cwd / "mimir-run.json")


def run_py(script, *a):
    t = time.time()
    p = subprocess.run([sys.executable, str(HERE / script), *a], capture_output=True, text=True)
    if p.returncode:
        print(p.stdout, p.stderr, file=sys.stderr)
    return p.returncode, time.time() - t


def nextpnr(cwd, js, anchors, grid, placer, seed, temp, n=10, locked=False):
    nl.ensure_dir(cwd)
    argv = [NPNR, "--uarch", "k6", "--vopt", f"width={grid[0]}", "--vopt", f"height={grid[1]}", "--vopt", f"n={n}"]
    if anchors.exists() and anchors.stat().st_size:
        argv += ["--vopt", f"anchors={anchors}"]
    argv += ["--json", str(js), "--no-route", "--placer", placer, "--seed", str(seed), "--write", str(cwd / "placed.json")]
    if placer == "sa":
        argv += ["--starttemp", str(temp)]
    cmd = (["flock", "-x", str(nl.LOCK)] if locked else []) + ["/usr/bin/time", "-v"] + argv
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, LD_LIBRARY_PATH=LIBS), timeout=14400)
    wall = time.time() - t0
    txt = p.stdout + p.stderr
    (cwd / "nextpnr.log").write_text(txt)
    secs, rss = rr.parse_time_v(txt)
    STEPS.append({"kind": "nextpnr", "argv": argv, "rc": p.returncode, "secs": secs, "rss": rss, "log": cwd / "nextpnr.log"})
    g = lambda rx: (float(m.group(1)) if (m := re.search(rx, txt)) else None)
    rec = {"rc": p.returncode, "wall_s": wall, "ble_per_tile": n, "no_bels": "no BELs remaining" in txt, "heap_s": g(r"HeAP Placer Time: ([0-9.]+)s"), "sa_s": g(r"SA placement time ([0-9.]+)s"),
           "init_s": g(r"Initial placement time ([0-9.]+)s"), "max_rss_kb": g(r"Maximum resident set size \(kbytes\): (\d+)")}
    m = re.findall(r"wirelen = (\d+)", txt)
    rec["hpwl_final"] = int(m[-1]) if m else None
    return rec


def process(design):
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    dst = nl.DATA / "placers" / f"{args.tag}_{design}.json"
    out = json.loads(dst.read_text()) if dst.exists() else {"design": design, "tag": args.tag, "runs": [], "converter": {}}
    if args.redo_failed:
        old_conv = "chain_ffs" not in out.get("converter", {})
        bad = [r for r in out["runs"] if r["rc"] != 0 or not r.get("routed_ok") or (old_conv and r["arm"].startswith("ext_"))]
        if bad:
            ff = out.setdefault("first_attempt_failures", [])
            for r in bad:
                e = {k: r.get(k) for k in ("arm", "seed", "starttemp", "rc", "error")} | {"reason": "failed" if (r["rc"] != 0 or not r.get("routed_ok")) else "converter predates 10.7"}
                if (r.get("nextpnr") or {}).get("no_bels"):
                    e["no_bels"] = True
                if e not in ff:  # no duplicate entries (a repeated --redo-failed pass must not add the same failure twice)
                    ff.append(e)
            out["runs"] = [r for r in out["runs"] if r not in bad]
        if old_conv:
            out["converter"] = {}
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
        STEPS.clear()
        rec = vpr(cwd, flags, seed, blif, write=write, read=read)
        if rec["rc"]:  # a failed run is retried once (Section 5 rule 4)
            rec = vpr(cwd, flags, seed, blif, write=write, read=read) | {"retried": True}
        rec |= {"arm": arm, "seed": seed} | (extra or {})
        write_record(cwd, design, arm, seed, FAMILY[arm], blif, roles={read: "<read_flat_place>"} if read else None,
                     inputs={"read_flat_place": read} if read else None,
                     artifacts={"vpr_out": cwd / "vpr.out", **({"flat_place": cwd / write} if write else {})})
        record(rec)
        return rec

    def collapsed(p):
        q = p.with_name("final.collapsed.flat_place")
        run_py("flatplace_chains.py", "--blif", str(blif), "--in", str(p), "--out", str(q))
        return q

    # reference run (also the shared vpr_ap seed-1 run)
    r1 = vrun("vpr_ap", 1, [], write="final.flat_place")
    ref = wd / "vpr_ap.s1" / "final.flat_place"
    grid = r1["grid"]
    out["reference"] = {"arm": "vpr_ap", "seed": 1, "grid": grid}
    if r1["rc"] or not ref.exists():
        out["error"] = "reference run failed"
        save()
        return
    refc = wd / "ref.collapsed.flat_place"
    run_py("flatplace_chains.py", "--blif", str(blif), "--in", str(ref), "--out", str(refc), "--stats", str(wd / "ref.collapse.json"))
    out["chain_collapse_ref"] = json.loads((wd / "ref.collapse.json").read_text())
    ext = nl.ensure_dir(wd / "ext")
    js, anchors = ext / f"{design}.json", ext / f"{design}.json.anchors.txt"
    ref_sha = hashlib.sha256(refc.read_bytes()).hexdigest()
    # the converter output is valid only for the reference file it was built from (a stale JSON gave anchor_moved 1404 on stereovision2, section 10.10)
    if not out["converter"].get("ok") or not js.exists() or out["converter"].get("ref_sha256") != ref_sha:
        rc, sec = run_py("nextpnr_blif2json.py", "--blif", str(blif), "--ref", str(refc), "--out", str(js),
                         "--stats", str(ext / "convert_stats.json"), "--anchors", str(anchors))
        st = json.loads((ext / "convert_stats.json").read_text()) if (ext / "convert_stats.json").exists() else {}
        out["converter"] = {"rc": rc, "seconds": sec, "ref_sha256": ref_sha, **{k: v for k, v in st.items() if k != "ref_atoms_without_cell"}}
        save()
        if rc:
            out["error"] = "converter failed"
            save()
            return
    # BLE slots per tile (section 10.8): 10 (Section 9.2) unless the design has more BLE cells than slots, then 20 (two LUT5 per fle).
    # Decided once per design by a quick HeAP probe, because nextpnr's SA does not stop on an over-full device.
    probe = nextpnr(wd / "probe_n10", js, anchors, grid, "heap", 1, None, n=10)
    n_ble = 20 if (probe["rc"] and probe["no_bels"]) else 10
    out["ble_per_tile"] = n_ble
    out["probe"] = {k: probe[k] for k in ("rc", "no_bels", "wall_s")}
    save()
    for s in SEEDS:
        for arm in ARMS:
            if arm == "vpr_ap":
                vrun("vpr_ap", s, [], write="final.flat_place")
            elif arm == "vpr_ap_reread":
                vrun("vpr_ap", s, [], write="final.flat_place")
                vrun("vpr_ap_reread", s, [], read=collapsed(wd / f"vpr_ap.s{s}" / "final.flat_place"))
            elif arm == "vpr_sa":
                vrun("vpr_sa", s, SA, write="final.flat_place")
            elif arm == "vpr_sa_reread":
                vrun("vpr_sa", s, SA, write="final.flat_place")
                vrun("vpr_sa_reread", s, [], read=collapsed(wd / f"vpr_sa.s{s}" / "final.flat_place"))
            elif arm in ("ext_nextpnr_heap", "ext_nextpnr_sa"):
                placer = arm.rsplit("_", 1)[1]
                for T in (TEMPS if placer == "sa" else [None]):
                    extra = {"starttemp": T} if T is not None else {}
                    if (arm, s, T) in done:
                        continue
                    tag = f"{arm}.s{s}" + (f".t{T:g}" if T is not None else "")
                    cwd = wd / tag
                    STEPS.clear()
                    slow = any((r.get("nextpnr") or {}).get("wall_s", 0) > NP_LOCK_AFTER_S for r in out["runs"] if r["arm"] == arm)
                    def npr(T=T, s=s, arm=arm, placer=placer, cwd=cwd):
                        ovl = Path(NPNR).resolve().parent.parent / "nextpnr-k6-src/generic/viaduct/k6/k6.cc"  # the overlay copy that was compiled
                        write_record(cwd, design, arm + (f"-t{T:g}" if T is not None else ""), s, FAMILY[arm], blif, placer=placer,
                                     roles={js: "<json>", anchors: "<anchors>", cwd / "placed.json": "<placed>", cwd / "ext.flat_place": "<read_flat_place>"},
                                     inputs={"nextpnr_json": js, "anchors": anchors, "reference_flat_place": refc, "overlay_k6cc_built": ovl,
                                             "overlay_k6cc_repo": HERE.parent / "placers/nextpnr_k6/k6.cc", "read_flat_place": cwd / "ext.flat_place"},
                                     artifacts={"placed_json": cwd / "placed.json", "nextpnr_log": cwd / "nextpnr.log", "vpr_out": cwd / "vpr" / "vpr.out"})
                    np_rec = nextpnr(cwd, js, anchors, grid, placer, s, T, n=n_ble, locked=slow)
                    if np_rec["rc"]:
                        np_rec = nextpnr(cwd, js, anchors, grid, placer, s, T, n=n_ble, locked=slow) | {"retried": True}
                    rec = {"arm": arm, "seed": s, "nextpnr": np_rec} | extra
                    if np_rec["max_rss_kb"] and np_rec["max_rss_kb"] > args.max_rss_gb * 1e6:
                        rec |= {"rc": -1, "routed_ok": False, "error": "nextpnr memory over the stop limit"}
                        npr()
                        record(rec)
                        sys.exit("memory stop rule")
                    if np_rec["rc"]:
                        rec |= {"rc": np_rec["rc"], "routed_ok": False, "error": "nextpnr failed"}
                        npr()
                        record(rec)
                        continue
                    rc2, sec2 = run_py("nextpnr_readback.py", "--json", str(cwd / "placed.json"), "--ref", str(refc), "--fixed", str(js) + ".fixed.txt",
                                       "--out", str(cwd / "ext.flat_place"), "--stats", str(cwd / "rb.json"))
                    rec["readback"] = json.loads((cwd / "rb.json").read_text()) if (cwd / "rb.json").exists() else {}
                    rec["readback_s"] = sec2
                    bad_rb = {k: rec["readback"].get(k) for k in ("fallback_ref", "const_verbatim", "anchor_moved", "pad_moved") if rec["readback"].get(k)}
                    if bad_rb:  # section 10.4(a): a pipeline fault stops the arm for this seed; VPR does not see the file
                        rec |= {"rc": -2, "routed_ok": False, "error": f"readback fault {bad_rb}"}
                        npr()
                        record(rec)
                        continue
                    if rc2:
                        rec |= {"rc": rc2, "routed_ok": False, "error": "readback failed"}
                        npr()
                        record(rec)
                        continue
                    v = vpr(cwd / "vpr", [], s, blif, read=cwd / "ext.flat_place")
                    if v["rc"]:
                        v = vpr(cwd / "vpr", [], s, blif, read=cwd / "ext.flat_place") | {"retried": True}
                    rec |= v
                    npr()
                    record(rec)
            else:
                sys.exit(f"unknown arm {arm}")


for d in args.designs.split(","):
    process(d)
print("done", args.designs)
