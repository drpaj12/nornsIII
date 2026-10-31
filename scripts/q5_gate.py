"""Q-N5 gate (docs/plan/q-n5-schabas-spare.md): on the FIXED grid, --norns_spare_bles 0 gives a .net byte-identical to the stock sweep .net.

  python3 q5_gate.py --sweep SWEEP_ROOT --out OUT_ROOT [--designs a,b] [--seeds 1,2,3] [--mode w0|none]

mode w0: `--device spare --norns_spare_bles 0 --norns_spare_dump gate.dump` (the new code present and inert); mode none: only `--device spare`.
`--pack` only, under the Norns VPR lock, memory cap 14 GB. Needs OUT/arch/<design>.xml from q5_prep.py. Writes OUT/gate-<mode>/<design>/s<seed>/gate.json.
Resumable; nothing deleted.
"""
import argparse, fcntl, hashlib, json, os, re, resource, subprocess, time
from pathlib import Path

LOCK = os.environ.get("NORNS_VPR_LOCK", "/tmp/claude-1000/norns-vpr.lock")
VPR = os.environ["NORNS_VPR"]
CAP = 14 * 1024 ** 3


ARCH_ID = re.compile(rb'architecture_id="SHA256:[0-9a-f]+"')


def sha(p):
    """sha256 of the .net with the architecture_id attribute blanked: the fixed-layout architecture file differs from the stock one (layout section), so its hash does."""
    return hashlib.sha256(ARCH_ID.sub(b'architecture_id=""', Path(p).read_bytes())).hexdigest()


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (CAP, CAP))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--designs", default="")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--mode", default="w0", choices=("w0", "none"))
    ap.add_argument("--recheck", action="store_true", help="recompute net_equal of finished runs (no VPR run)")
    a = ap.parse_args()
    sweep, out = Path(a.sweep), Path(a.out)
    order = [d for d, _ in json.loads((sweep / "order.json").read_text())]
    want = [d for d in order if (not a.designs or d in a.designs.split(","))]
    for d in want:
        blif = sweep / "netlists" / "base" / d / "netlist" / f"{d}.blif"
        for s in [int(x) for x in a.seeds.split(",")]:
            run = out / f"gate-{a.mode}" / d / f"s{s}"
            if (run / "gate.json").is_file() and not a.recheck:
                continue
            if a.recheck:
                g = json.loads((run / "gate.json").read_text())
                ref = sweep / "vpr" / "e10-base" / d / f"vpr_sa.s{s}" / f"{d}.net"
                g["net_equal"] = bool((run / f"{d}.net").is_file() and ref.is_file() and sha(run / f"{d}.net") == sha(ref))
                g["compare"] = "architecture_id blanked"
                (run / "gate.json").write_text(json.dumps(g) + "\n")
                print(json.dumps(g), flush=True)
                continue
            run.mkdir(parents=True, exist_ok=True)
            argv = [VPR, str(out / "arch" / f"{d}.xml"), str(blif), "--pack", "--seed", str(s), "--device", "spare"]
            if a.mode == "w0":
                argv += ["--norns_spare_bles", "0", "--norns_spare_dump", "gate.dump"]
            t0 = time.time()
            with open(LOCK, "a") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                with open(run / "vpr.out", "w") as fo:
                    rc = subprocess.run(argv, cwd=run, stdout=fo, stderr=subprocess.STDOUT, preexec_fn=limit).returncode
            ref = sweep / "vpr" / "e10-base" / d / f"vpr_sa.s{s}" / f"{d}.net"
            mine = run / f"{d}.net"
            txt = (run / "vpr.out").read_text(errors="replace")
            g = {"design": d, "seed": s, "mode": a.mode, "rc": rc, "secs": round(time.time() - t0, 1),
                 "net_equal": bool(mine.is_file() and ref.is_file() and sha(mine) == sha(ref)),
                 "fixed_grid_logged": bool(re.search(r"FPGA sized to \d+ x \d+: \d+ grid tiles \(spare\)", txt))}
            (run / "gate.json").write_text(json.dumps(g) + "\n")
            print(json.dumps(g), flush=True)


if __name__ == "__main__":
    main()
