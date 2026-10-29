"""Critical-heap lane: beta-0 pack census of the keep-sweep runs (docs/plan/critical-heap.md).

  python3 scripts/heap_census.py --sweep SWEEP_ROOT --out OUT_ROOT [--designs a,b] [--seeds 1,2,3]

Runs the Norns VPR binary with the E10 base flags of the keep sweep but `--pack` only (the pack does not depend on the
later stages) and `--norns_pack_census`, under the Norns VPR lock. Beta is 0 (no affinity file), so the .net must be
byte-identical to the sweep's .net (gate); the result is written to OUT/<design>/s<seed>/gate.json. Resumable.
Memory cap: RLIMIT_AS 14 GB.
"""
import argparse, fcntl, hashlib, json, os, resource, subprocess, sys, time
from pathlib import Path

LOCK = os.environ.get("NORNS_VPR_LOCK", "/tmp/claude-1000/norns-vpr.lock")
VPR = os.environ.get("NORNS_VPR", str(Path.home() / "odin3-ws/work/norns-vtr/build/vpr/vpr"))
ARCH = os.environ.get("NORNS_ARCH", str(Path.home() / "odin3-ws/external/vtr-verilog-to-routing/vtr_flow/arch/timing/k6_frac_N10_frac_chain_mem32K_40nm.xml"))
CAP = 14 * 1024 ** 3
NORNS15 = ("ch_intrinsics", "stereovision3", "mkPktMerge", "diffeq2", "diffeq1", "boundtop", "mkDelayWorker32B", "mkSMAdapter4B", "sha",
           "raygentop", "or1200", "blob_merge", "stereovision0", "stereovision1", "stereovision2")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (CAP, CAP))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--designs", default="")
    ap.add_argument("--seeds", default="1,2,3")
    a = ap.parse_args()
    sweep, out = Path(a.sweep), Path(a.out)
    order = [d for d, _ in json.loads((sweep / "order.json").read_text())]
    want = [d for d in order if d in NORNS15 and (not a.designs or d in a.designs.split(","))]
    for d in want:
        blif = sweep / "netlists" / "base" / d / "netlist" / f"{d}.blif"
        for s in [int(x) for x in a.seeds.split(",")]:
            run = out / d / f"s{s}"
            if (run / "gate.json").is_file():
                continue
            run.mkdir(parents=True, exist_ok=True)
            argv = [VPR, ARCH, str(blif), "--pack", "--seed", str(s), "--timing_report_npaths", "1000", "--norns_pack_census", str(run / "census.tsv")]
            t0 = time.time()
            with open(LOCK, "a") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                with open(run / "vpr.out", "w") as fo:
                    rc = subprocess.run(argv, cwd=run, stdout=fo, stderr=subprocess.STDOUT, preexec_fn=limit).returncode
            ref = sweep / "vpr" / "e10-base" / d / f"vpr_sa.s{s}" / f"{d}.net"
            mine = run / f"{d}.net"
            g = {"design": d, "seed": s, "rc": rc, "secs": round(time.time() - t0, 1),
                 "net_equal": bool(mine.is_file() and ref.is_file() and sha(mine) == sha(ref))}
            (run / "gate.json").write_text(json.dumps(g) + "\n")
            print(json.dumps(g), flush=True)


if __name__ == "__main__":
    main()
