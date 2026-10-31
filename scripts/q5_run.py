"""Q-N5 arms (docs/plan/q-n5-schabas-spare.md): stock, s = 2, s = 4 on the fixed grid of each design, two channel-width settings, seeds 1-3, smallest first.

  python3 q5_run.py --root OUT_ROOT [--designs a,b] [--seeds 1,2,3]

OUT_ROOT holds netlists/ (symlink to the keep sweep), order.json, arch/<design>.xml and prep.json (q5_prep.py). Per design and seed:
setting a = E10 base flow (minimum-width search; each arm measured at its own Wmin), then setting b = the same arms at the fixed
W = ceil(1.2 x Wmin of the stock arm of setting a, same design and seed). One placers_main.py process per run, so the resume key is the run.
Guards before each design: /mnt/c free >= 15 GB, weekly meter < 100. Resumable; nothing is deleted.
"""
import argparse, json, math, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nornlib as nl

LOCK = "/tmp/claude-1000/norns-vpr.lock"
ARCH_FALLBACK = None


def free_gb():
    r = subprocess.run(["df", "--output=avail", "-BG", "/mnt/c"], capture_output=True, text=True).stdout.splitlines()[-1]
    return int("".join(c for c in r if c.isdigit()))


def week():
    return json.loads((Path.home() / ".claude/usage-state/latest.json").read_text())["week"]


def one(root, label, d, seed, extra, prep):
    work = root / "vpr" / label
    env = dict(os.environ, NORNS_RUNS=str(root / "netlists" / "base"), NORNS_ARCH=str(root / "arch" / f"{d}.xml"), NORNS_DATA=str(root / "data"), NORNS_LOCK=LOCK)
    argv = [sys.executable, str(HERE / "placers_main.py"), "--work", str(work), "--tag", label, "--designs", d, "--seeds", str(seed), "--arms", "vpr_sa",
            "--odin-meta", str(root / "netlists" / "base" / d / "netlist" / "odin-meta.json"), "--vpr-extra", extra]
    rc = subprocess.run(argv, env=env).returncode
    return rc


def wmin(root, d, seed):
    f = root / "vpr" / "q5a-stock" / d / f"vpr_sa.s{seed}" / "vpr.out"
    if not f.is_file():
        return None
    m = re.search(r"Best routing used a channel width factor of (\d+)\.", f.read_text(errors="replace"))
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--designs", default="")
    ap.add_argument("--seeds", default="1,2,3")
    a = ap.parse_args()
    root = Path(a.root)
    prep = json.loads((root / "prep.json").read_text())
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
        arms = {"stock": "--device spare"}
        for s in ("2", "4"):
            r = prep[d]["arms"][s]
            arms[f"s{s}"] = f"--device spare --norns_spare_bles {s} --norns_spare_clusters {r['n']} --norns_spare_crit_min {r['crit_min']:.9g} --norns_spare_dump spare.dump"
        for seed in [int(x) for x in a.seeds.split(",")]:
            for arm, extra in arms.items():
                rc = one(root, f"q5a-{arm}", d, seed, extra, prep)
                print(f"{d} s{seed} a-{arm} rc {rc}", flush=True)
            w = wmin(root, d, seed)
            if w is None:
                print(f"{d} s{seed}: stock Wmin unknown, setting b skipped", flush=True)
                continue
            W = math.ceil(1.2 * w)
            for arm, extra in arms.items():
                rc = one(root, f"q5b-{arm}", d, seed, f"{extra} --route_chan_width {W}", prep)
                print(f"{d} s{seed} b-{arm} W={W} rc {rc}", flush=True)
    print("## all designs done", flush=True)


if __name__ == "__main__":
    main()
