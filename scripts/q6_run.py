"""Q-N6 driver (docs/plan/q-n6-duplication.md): arms dup and spare over the 35 designs, seeds 1-3, smallest first.

  python3 q6_run.py --root Q5_ROOT --out OUT_ROOT [--designs a,b] [--seeds 1,2,3] [--arms dup,spare]

Per design, seed, arm: q6_dup.py (setting a: rounds under the E10 min-width flow), then setting b: the paired baseline (round 0, flat-recon of the start
placement, no duplication) and the best-round result both routed at fixed W = 2 x ceil(1.2 x Wmin(stock arm of Q-N5, same design and seed) / 2).
Result dirs under OUT/vpr: q6a-<arm> (best round), q6a-<arm>-base (round 0), q6b-<arm>, q6b-<arm>-base. Guards before each design: /mnt/c >= 15G, week < 100.
Resumable (a finished dup.json is skipped); nothing is deleted.
"""
import argparse, json, math, os, re, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q6_dup as qd

HERE = Path(__file__).resolve().parent


def free_gb():
    r = subprocess.run(["df", "--output=avail", "-BG", "/mnt/c"], capture_output=True, text=True).stdout.splitlines()[-1]
    return int("".join(c for c in r if c.isdigit()))


def week():
    return json.loads((Path.home() / ".claude/usage-state/latest.json").read_text())["week"]


def keep(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("vpr.out", "report_timing.setup.rpt", "mimir-run.json"):
        if (src / f).is_file():
            shutil.copy(src / f, dst / f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--designs", default="")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--arms", default="dup,spare")
    a = ap.parse_args()
    root, out = Path(a.root), Path(a.out)
    order = [d for d, _ in json.loads((root / "order.json").read_text())]
    want = [d for d in order if (not a.designs or d in a.designs.split(","))]
    for d in want:
        if free_gb() < 15:
            print(f"STOP: /mnt/c has {free_gb()}G free", flush=True)
            sys.exit(3)
        if week() >= 100:
            print(f"STOP: weekly meter {week()}", flush=True)
            sys.exit(4)
        print(f"## {d} free {free_gb()}G week {week()}", flush=True)
        for s in [int(x) for x in a.seeds.split(",")]:
            so = (root / "vpr" / "q5a-stock" / d / f"vpr_sa.s{s}" / "vpr.out").read_text(errors="replace")
            m = re.search(r"Best routing used a channel width factor of (\d+)\.", so)
            W = 2 * math.ceil(1.2 * int(m.group(1)) / 2) if m else None
            for arm in a.arms.split(","):
                base = out / "work" / f"q6-{arm}" / d / f"s{s}"
                if not (base / "dup.json").is_file():
                    subprocess.run([sys.executable, str(HERE / "q6_dup.py"), "--root", str(root), "--out", str(out), "--arm", arm, "--design", d, "--seed", str(s)])
                if not (base / "dup.json").is_file():
                    print(f"{d} s{s} {arm}: no dup.json", flush=True)
                    continue
                log = json.loads((base / "dup.json").read_text())
                keep(base / "r0", out / "vpr" / f"q6a-{arm}-base" / d / f"vpr_sa.s{s}")
                if W is None or not (base / "r0" / "final.flat_place").is_file():
                    continue
                start = root / "vpr" / ("q5a-stock" if arm == "dup" else "q5a-s2") / d / f"vpr_sa.s{s}" / "final.flat_place"
                arch = root / "arch" / f"{d}.xml"
                blif0 = root / "netlists" / "base" / d / "netlist" / f"{d}.blif"
                r0 = qd.vpr(base / "wb0", arch, blif0, start, s, W)
                keep(base / "wb0", out / "vpr" / f"q6b-{arm}-base" / d / f"vpr_sa.s{s}")
                br = log.get("best_round", 0)
                if br == 0:
                    keep(base / "wb0", out / "vpr" / f"q6b-{arm}" / d / f"vpr_sa.s{s}")
                    r1 = r0
                else:
                    r1 = qd.vpr(base / "wb1", arch, base / f"r{br}" / f"{d}.blif", base / f"r{br}" / "in.flat_place", s, W)
                    keep(base / "wb1", out / "vpr" / f"q6b-{arm}" / d / f"vpr_sa.s{s}")
                print(f"{d} s{s} {arm} W={W} base {r0['cpd']} dup {r1['cpd']} best_round {br}", flush=True)
    print("## all designs done", flush=True)


if __name__ == "__main__":
    main()
