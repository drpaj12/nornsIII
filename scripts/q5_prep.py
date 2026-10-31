"""Q-N5 pass 1 (docs/plan/q-n5-schabas-spare.md): per design the stock grid, the spare room, the fixed-layout architecture, the
stock seed-criticality dump, and the cluster budget n and threshold T of each s.

  python3 q5_prep.py --sweep SWEEP_ROOT --out OUT_ROOT [--designs a,b] [--s 2,4] [--N 10]

Reads the stock keep-sweep run (seed 1) log of each design for the auto grid ("FPGA sized to W x H") and the CLB tiles; writes
OUT/arch/<design>.xml (the architecture with <fixed_layout name="spare"> in place of the auto layout), runs the stock pack
(`--pack`, auto layout, `--norns_spare_dump`) under the Norns VPR lock to get the seed criticality of every stock logic cluster, and writes
OUT/prep.json. Resumable; nothing deleted.
"""
import argparse, fcntl, json, math, os, re, resource, subprocess
from pathlib import Path

LOCK = os.environ.get("NORNS_VPR_LOCK", "/tmp/claude-1000/norns-vpr.lock")
VPR = os.environ["NORNS_VPR"]
ARCH = Path(os.environ["NORNS_ARCH"]) if os.environ.get("NORNS_ARCH") else Path(os.environ.get("VTR_ROOT", str(Path.home() / "odin3-ws/external/vtr-verilog-to-routing"))) / "vtr_flow/arch/timing/k6_frac_N10_frac_chain_mem32K_40nm.xml"
CAP = 14 * 1024 ** 3
AUTO = re.compile(r"<auto_layout aspect_ratio=\"1.0\">(.*?)</auto_layout>", re.S)


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (CAP, CAP))


def stock_facts(text):
    m = re.search(r"FPGA sized to (\d+) x (\d+)", text)
    w, h = int(m.group(1)), int(m.group(2))
    res = text[text.index("Resource usage..."):]
    use = {}
    for mm in re.finditer(r"Netlist\s+(\d+)\s+blocks of type: (\w+)\s+Architecture\s+(\d+)\s+blocks of type: (\w+)", res):
        use[mm.group(2)] = (int(mm.group(1)), int(mm.group(3)))
    return w, h, use


def budget(spare, s, N, crits_desc):
    """(n, T): Schabas Eq. 7 with DeviceSize = the CLB tiles of the fixed grid, n = floor(spare x N / s) capped at the stock logic clusters; T = the n-th highest seed criticality."""
    n = min(spare * N // s, len(crits_desc))
    return n, (crits_desc[n - 1] if n > 0 else 1.0e9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--designs", default="")
    ap.add_argument("--s", default="2,4")
    ap.add_argument("--N", type=int, default=10)
    a = ap.parse_args()
    sweep, out = Path(a.sweep), Path(a.out)
    (out / "arch").mkdir(parents=True, exist_ok=True)
    order = [d for d, _ in json.loads((sweep / "order.json").read_text())]
    want = [d for d in order if (not a.designs or d in a.designs.split(","))]
    arch_txt = ARCH.read_text()
    mo = AUTO.search(arch_txt)
    assert mo, "auto_layout not found"
    prep_path = out / "prep.json"
    prep = json.loads(prep_path.read_text()) if prep_path.is_file() else {}
    for d in want:
        if d in prep:
            continue
        ref = (sweep / "vpr" / "e10-base" / d / "vpr_sa.s1" / "vpr.out").read_text(errors="replace")
        w, h, use = stock_facts(ref)
        clb_net, clb_tiles = use["clb"]
        spare = clb_tiles - clb_net
        ratios = {t: v[0] / v[1] for t, v in use.items() if v[1] > 0}
        binding = max(ratios, key=lambda t: ratios[t])
        fixed = arch_txt[:mo.start()] + f'<fixed_layout name="spare" width="{w}" height="{h}">' + mo.group(1) + "</fixed_layout>" + arch_txt[mo.end():]
        (out / "arch" / f"{d}.xml").write_text(fixed)
        run = out / "pass1" / d
        run.mkdir(parents=True, exist_ok=True)
        blif = sweep / "netlists" / "base" / d / "netlist" / f"{d}.blif"
        with open(LOCK, "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            with open(run / "vpr.out", "w") as fo:
                rc = subprocess.run([VPR, str(ARCH), str(blif), "--pack", "--seed", "1", "--norns_spare_dump", "pass1.dump"], cwd=run, stdout=fo, stderr=subprocess.STDOUT, preexec_fn=limit).returncode
        crits = sorted((float(l.split("\t")[1]) for l in (run / "pass1.dump").read_text().splitlines() if l), reverse=True)
        rec = {"grid": [w, h], "square": w == h, "clb_tiles": clb_tiles, "clbs_stock": clb_net, "spare": spare, "util": ratios, "binding": binding,
               "logic_clusters": len(crits), "pass1_rc": rc, "arms": {}}
        for s in [int(x) for x in a.s.split(",")]:
            n, T = budget(spare, s, a.N, crits)
            rec["arms"][str(s)] = {"n": n, "crit_min": T, "n_uncapped": spare * a.N // s}
        prep[d] = rec
        prep_path.write_text(json.dumps(prep, indent=1) + "\n")
        print(d, json.dumps({k: rec[k] for k in ("grid", "clb_tiles", "clbs_stock", "spare", "binding", "logic_clusters")}), json.dumps(rec["arms"]), flush=True)


if __name__ == "__main__":
    main()
