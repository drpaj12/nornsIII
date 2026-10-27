"""Dispatch 1 step 2: VPR-only round trip, --write_flat_place then --read_flat_place (docs/plan/placers.md).

Usage: . scripts/env.sh; NORNS_LOCK=/tmp/claude-1000/norns-vpr.lock python3 scripts/placers_rt.py WORKDIR [design] [seed]
WORKDIR is a fresh `mktemp -d /tmp/claude-1000/npl-XXXX`. Every VPR run takes the Norns lock (one at a time).
Writes data/placers/rt_<design>_s<seed>.json (metrics only; raw VPR outputs stay in WORKDIR).
"""
import json
import re
import sys
from pathlib import Path

import nornlib as nl

WORK = Path(sys.argv[1])
DESIGN = sys.argv[2] if len(sys.argv) > 2 else "ch_intrinsics"
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
BLIF = nl.runs_dir(DESIGN, "netlist", f"{DESIGN}.blif")
VPR = Path(__import__("os").environ["NORNS_VPR"])
EXTRA = {
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


def one(tag: str, flags: list[str], write: str | None, read: Path | None) -> dict:
    cwd = WORK / tag
    nl.ensure_dir(cwd)
    flags = flags + ["--seed", str(SEED), "--route_file", "/dev/null"]
    if write:
        flags += ["--write_flat_place", str(cwd / write)]
    if read:
        flags += ["--read_flat_place", str(read)]
    cmd = ["flock", "-x", str(nl.LOCK), str(VPR), str(nl.ARCH), str(BLIF)] + flags
    log = cwd / "vpr.out"
    rc = nl.run(cmd, cwd=cwd, stdout=log, timeout=1800)
    rec = {"tag": tag, "rc": rc, "flags": [f for f in flags if not f.startswith("/")]}
    text = log.read_text(errors="replace")
    for k, rx in EXTRA.items():
        m = rx.search(text)
        rec[k] = float(m.group(1)) if m else None
    rec["flat_skip_msg"] = "skipping the Global Placement" in text
    rec["flat_check_ok"] = "Completed flat placement consistency check successfully" in text
    rec["warn_flat"] = len(re.findall(r"Flat placement file, line", text))
    print(tag, {k: rec[k] for k in ("rc", "wl", "cpd_ns", "W", "flow_s")}, flush=True)
    return rec


out = []
SA = ["--pack", "--place", "--route", "--analysis"]
AP_FLAG = ["--analytical_place", "--route", "--analysis"]
out.append(one("sa_write", SA, "sa.flat_place", None))
out.append(one("ap_default_write", [], "ap_default.flat_place", None))
out.append(one("ap_flag_write", AP_FLAG, "ap_flag.flat_place", None))
out.append(one("sa_read_in_sa", SA, None, WORK / "sa_write" / "sa.flat_place"))
out.append(one("ap_read_in_ap", [], None, WORK / "ap_default_write" / "ap_default.flat_place"))
out.append(one("sa_read_in_ap", [], None, WORK / "sa_write" / "sa.flat_place"))
out.append(one("ap_read_in_sa", SA, None, WORK / "ap_default_write" / "ap_default.flat_place"))
dst = nl.DATA / "placers" / f"rt_{DESIGN}_s{SEED}.json"
dst.write_text(json.dumps({"design": DESIGN, "seed": SEED, "runs": out}, indent=1) + "\n")
print("wrote", dst)
