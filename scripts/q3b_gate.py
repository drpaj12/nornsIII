"""Q-N3b gate (docs/plan/q-n3b-2hop-gain.md): --norns_2hop_weight 0 gives a .net byte-identical to the stock sweep .net.

  python3 q3b_gate.py --sweep SWEEP_ROOT --out OUT_ROOT [--designs a,b] [--seeds 1,2,3] [--w 0] [--no-option]

`--pack` only (the pack does not depend on later stages), under the Norns VPR lock, memory cap 14 GB (RLIMIT_AS).
Writes OUT/w<w>/<design>/s<seed>/gate.json ({design, seed, w, rc, secs, net_equal}). Resumable, nothing deleted.
With --no-compare the .net of the run is only kept (a k>0 run has no stock reference to equal).
"""
import argparse, fcntl, hashlib, json, os, re, resource, subprocess, time
from pathlib import Path

LOCK = os.environ.get("NORNS_VPR_LOCK", "/tmp/claude-1000/norns-vpr.lock")
VPR = os.environ["NORNS_VPR"]
ARCH = os.environ.get("NORNS_ARCH", str(Path(os.environ.get("VTR_ROOT", str(Path.home() / "odin3-ws/external/vtr-verilog-to-routing"))) / "vtr_flow/arch/timing/k6_frac_N10_frac_chain_mem32K_40nm.xml"))
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
    ap.add_argument("--w", type=float, default=0.0)
    ap.add_argument("--no-option", action="store_true", help="do not pass --norns_2hop_weight at all (w must be 0)")
    a = ap.parse_args()
    sweep, out = Path(a.sweep), Path(a.out)
    order = [d for d, _ in json.loads((sweep / "order.json").read_text())]
    want = [d for d in order if (not a.designs or d in a.designs.split(","))]
    for d in want:
        blif = sweep / "netlists" / "base" / d / "netlist" / f"{d}.blif"
        for s in [int(x) for x in a.seeds.split(",")]:
            run = out / f"w{a.w:g}{'n' if a.no_option else ''}" / d / f"s{s}"
            if (run / "gate.json").is_file():
                continue
            run.mkdir(parents=True, exist_ok=True)
            argv = [VPR, ARCH, str(blif), "--pack", "--seed", str(s)]
            if not a.no_option:
                argv += ["--norns_2hop_weight", str(a.w)]
            t0 = time.time()
            with open(LOCK, "a") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                with open(run / "vpr.out", "w") as fo:
                    rc = subprocess.run(argv, cwd=run, stdout=fo, stderr=subprocess.STDOUT, preexec_fn=limit).returncode
            ref = sweep / "vpr" / "e10-base" / d / f"vpr_sa.s{s}" / f"{d}.net"
            mine = run / f"{d}.net"
            txt = (run / "vpr.out").read_text(errors="replace")
            m = re.search(r"Norns 2hop: w=(\S+) evals=(\d+)", txt)
            g = {"design": d, "seed": s, "w": a.w, "rc": rc, "secs": round(time.time() - t0, 1),
                 "net_equal": bool(mine.is_file() and ref.is_file() and sha(mine) == sha(ref)),
                 "evals": int(m.group(2)) if m else 0}
            (run / "gate.json").write_text(json.dumps(g) + "\n")
            print(json.dumps(g), flush=True)


if __name__ == "__main__":
    main()
