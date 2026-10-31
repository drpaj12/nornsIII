"""Q-N6 (docs/plan/q-n6-duplication.md): logic duplication after placement via VPR flat-placement reconstruction.

  python3 q6_dup.py --root Q5_ROOT --out OUT_ROOT --arm dup|spare --design D --seed S [--k 4] [--rounds 4] [--maxdist 3] [--zero]

Round 0 = flat-recon of the start run's final.flat_place with the unchanged BLIF (the gate). Round r: candidates from the previous round's
1000-path report, copies (or plain moves) written into a new BLIF and flat placement, ABC cec against the original BLIF, flat-recon + route + analysis.
The best round (lowest post-route CPD, ties to the earlier) is copied to OUT/vpr/q6a-<arm>/<design>/vpr_sa.s<seed>/. Resumable per round; nothing deleted.
"""
import argparse, fcntl, json, math, os, re, resource, shutil, subprocess, sys, time
from pathlib import Path

LOCK = os.environ.get("NORNS_VPR_LOCK", "/tmp/claude-1000/norns-vpr.lock")
VPR = os.environ.get("NORNS_VPR", "")
ABC = os.environ.get("NORNS_ABC", str(Path.home() / "odin3-ws/external/yosys/build/yosys-abc"))
CAP = 14 * 1024 ** 3
PT = re.compile(r"^(\S+) \((\.\w+)\)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*$")


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (CAP, CAP))


def parse_paths(text):
    """[(arrival, [(point, kind, incr)])] from a VPR setup report."""
    out = []
    for blk in text.split("#Path ")[1:]:
        pts, arr = [], None
        for ln in blk.splitlines():
            m = PT.match(ln)
            if m:
                pts.append((m.group(1), m.group(2), float(m.group(3))))
            a = re.match(r"data arrival time\s+(-?[\d.]+)", ln)
            if a and arr is None:
                arr = float(a.group(1))
        if arr is not None and pts:
            out.append((arr, pts))
    return out


def atom_of(point):
    return point.rsplit(".", 1)[0]


def read_flat(path):
    pos, typ, lines = {}, {}, []
    for ln in Path(path).read_text().splitlines():
        if not ln or ln.startswith("#"):
            continue
        f = ln.split("#")[0].split()
        pos[f[0]] = (int(float(f[1])), int(float(f[2])), int(float(f[4])))
        m = re.search(r"#\d+\s+(\S+)", ln)
        typ[f[0]] = m.group(1) if m else ""
    return pos, typ


def write_flat(path, pos, extra):
    with open(path, "w") as fo:
        for a, (x, y, s) in pos.items():
            fo.write(f"{a} {x} {y} 0 {s}\n")
        for a, (x, y, s) in extra.items():
            fo.write(f"{a} {x} {y} 0 {s}\n")


class Blif:
    def __init__(self, path):
        raw, acc = [], ""
        for ln in Path(path).read_text().splitlines():   # merge BLIF continuation lines (valid BLIF, same netlist)
            if ln.rstrip().endswith("\\"):
                acc += ln.rstrip()[:-1] + " "
            else:
                raw.append(acc + ln)
                acc = ""
        self.lines = raw
        self.names = {}   # output net -> (start index, end index exclusive)
        self.fan = {}     # net -> number of readers (names inputs, latch inputs, outputs)
        self.cont = False
        i = 0
        while i < len(raw):
            ln = raw[i]
            if ln.startswith(".end"):
                break   # only the first (top) model is read
            if ln.startswith(".names"):
                j = i + 1
                while j < len(raw) and not raw[j].startswith("."):
                    j += 1
                t = ln.split()[1:]
                self.names[t[-1]] = (i, j)
                for n in t[:-1]:
                    self.fan[n] = self.fan.get(n, 0) + 1
                i = j
                continue
            if ln.startswith(".latch"):
                n = ln.split()[1]
                self.fan[n] = self.fan.get(n, 0) + 1
            if ln.startswith(".outputs"):
                for n in ln.split()[1:]:
                    self.fan[n] = self.fan.get(n, 0) + 1000
            i += 1


def edit_blif(src, edits, dst):
    """edits: [(s, snew, q)]: copy the .names of s as snew (inserted right after s, inside the same .model) and make q read snew in place of s."""
    b = Blif(src)
    lines = list(b.lines)
    ins = []
    for s, snew, q in edits:
        a, e = b.names[s]
        blk = list(b.lines[a:e])
        h = blk[0].split()
        h[-1] = snew
        blk[0] = " ".join(h)
        ins.append((e, blk))
        qa, qe = b.names[q]
        hq = lines[qa].split()
        lines[qa] = " ".join(snew if (t == s and k < len(hq) - 1) else t for k, t in enumerate(hq))
    for e, blk in sorted(ins, key=lambda x: -x[0]):
        lines[e:e] = blk
    Path(dst).write_text("\n".join(lines) + "\n")


def cec(a, b):
    r = subprocess.run([ABC, "-c", f"cec {a} {b}"], capture_output=True, text=True)
    return "Networks are equivalent" in r.stdout, r.stdout.strip()[-200:]


def fit(paths, pos):
    xs, ys, intra = [], [], []
    for _, pts in paths:
        for i in range(1, len(pts)):
            p, c = pts[i - 1], pts[i]
            if p[1] in (".names", ".input", ".latch") and (".in[" in c[0] or ".D[" in c[0] or "outpad" in c[0]) and p[0].rsplit(".", 1)[1].startswith(("out", "inpad", "Q")):
                a, b = pos.get(atom_of(p[0])), pos.get(atom_of(c[0]))
                if not a or not b:
                    continue
                if a == b:
                    intra.append(c[2])
                else:
                    xs.append(abs(a[0] - b[0]) + abs(a[1] - b[1]))
                    ys.append(c[2])
    ci = sorted(intra)[len(intra) // 2] if intra else 0.1
    n = len(xs)
    if n < 3 or max(xs) == min(xs):
        return 0.3, 0.1, ci
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    b = max(b, 0.0)
    return max(my - b * mx, 0.0), b, ci


def occupancy(rd, d):
    """{(x, y, sub): occupied fle count} of the clb clusters of a run (from its .net and .place)."""
    import xml.etree.ElementTree as ET
    loc = {}
    for ln in (rd / f"{d}.place").read_text().splitlines():
        f = ln.split()
        if len(f) >= 5 and f[1].lstrip("-").isdigit():
            loc[f[0]] = (int(f[1]), int(f[2]), int(f[3]))
    occ = {}
    root = ET.parse(rd / f"{d}.net").getroot()
    for b in root.findall("block"):
        if b.get("instance", "").startswith("clb[") and b.get("name") in loc:
            occ[loc[b.get("name")]] = sum(1 for c in b.findall("block") if c.get("instance", "").startswith("fle[") and c.get("name") != "open")
    return occ


def clb_tiles(arch):
    """All clb tile coordinates of the fixed layout (interior minus the hard-block columns)."""
    x = Path(arch).read_text()
    m = re.search(r'<fixed_layout name="spare" width="(\d+)" height="(\d+)">(.*?)</fixed_layout>', x, re.S)
    w, h, body = int(m.group(1)), int(m.group(2)), m.group(3)
    cols = set()
    for c in re.finditer(r"<col ([^>]*)/>", body):
        at = dict(re.findall(r'(\w+)="([^"]*)"', c.group(1)))
        sx, rx = int(at["startx"]), int(at.get("repeatx", 0))
        cols.update(range(sx, w, rx) if rx else [sx])
    return {(i, j, 0) for i in range(1, w - 1) if i not in cols for j in range(1, h - 1)}


def candidates(paths, pos, typ, blif, maxdist, k, occ, tiles):
    a0, b0, ci = fit(paths, pos)
    worst = max(a for a, _ in paths)
    full = dict(occ)
    for key in tiles:
        full.setdefault(key, 0)
    free = {key: 10 - n for key, n in full.items() if n < 10}

    def D(u, v):
        return ci if u == v else a0 + b0 * (abs(u[0] - v[0]) + abs(u[1] - v[1]))

    cands = {}
    for arr, pts in paths:
        if arr < 0.98 * worst:
            continue
        for i in range(2, len(pts) - 1):
            if pts[i][1] != ".names" or not pts[i][0].endswith(".out[0]") or not pts[i + 1][0].count(".in[") or pts[i + 1][1] != ".names":
                continue
            s, q = atom_of(pts[i][0]), atom_of(pts[i + 1][0])
            if not pts[i - 1][0].startswith(s + ".in["):
                continue
            p = atom_of(pts[i - 2][0])
            if s not in pos or q not in pos or p not in pos or s not in blif.names or q not in blif.names:
                continue
            cs, cq, cp = pos[s], pos[q], pos[p]
            if cs == cq:
                continue
            cur = D(cp, cs) + D(cs, cq)
            for t in free:
                if t == cs or min(abs(t[0] - cq[0]) + abs(t[1] - cq[1]), abs(t[0] - cs[0]) + abs(t[1] - cs[1])) > maxdist:
                    continue
                gain = cur - (D(cp, t) + D(t, cq))
                if gain > 0.02 and gain > cands.get((s, q), (0,))[0]:
                    cands[(s, q)] = (gain, t, abs(t[0] - cq[0]) + abs(t[1] - cq[1]))
    ranked = sorted(cands.items(), key=lambda kv: (-kv[1][0], kv[1][2], kv[0]))
    chosen, used = [], set()
    for (s, q), (g, t, _) in ranked:
        if s in used or free.get(t, 0) < 1:
            continue
        used.add(s)
        free[t] -= 1
        chosen.append((s, q, t, g))
        if len(chosen) >= k:
            break
    return chosen, (a0, b0, ci)


def vpr(run, arch, blif, flat, seed, width=None):
    run.mkdir(parents=True, exist_ok=True)
    argv = [VPR, str(arch), str(blif), "--analytical_place", "--read_flat_place", str(flat), "--ap_full_legalizer", "flat-recon", "--ap_detailed_placer", "none",
            "--route", "--analysis", "--device", "spare", "--seed", str(seed), "--timing_report_npaths", "1000", "--route_file", "/dev/null",
            "--write_flat_place", str(run / "final.flat_place")]
    if width:
        argv += ["--route_chan_width", str(width)]
    t0 = time.time()
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        with open(run / "vpr.out", "w") as fo:
            rc = subprocess.run(argv, cwd=run, stdout=fo, stderr=subprocess.STDOUT, preexec_fn=limit).returncode
    secs = time.time() - t0
    txt = (run / "vpr.out").read_text(errors="replace")
    ok = "Circuit successfully routed" in txt
    (run / "mimir-run.json").write_text(json.dumps({"ok": rc == 0 and ok, "time_s": secs}))
    f = lambda pat: (re.search(pat, txt) or [None, None])[1]
    cpd = f(r"Final critical path delay \(least slack\): ([\d.]+) ns")
    return {"rc": rc, "ok": rc == 0 and ok, "cpd": float(cpd) if cpd else None, "secs": round(secs, 1),
            "wl": float(f(r"Total wirelength: (\d+)") or 0), "wmin": f(r"Best routing used a channel width factor of (\d+)\.")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm", default="dup", choices=("dup", "spare"))
    ap.add_argument("--design", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--maxdist", type=int, default=99)
    ap.add_argument("--zero", action="store_true", help="round 0 only (the gate)")
    a = ap.parse_args()
    root, out, d, s = Path(a.root), Path(a.out), a.design, a.seed
    start = root / "vpr" / ("q5a-stock" if a.arm == "dup" else "q5a-s2") / d / f"vpr_sa.s{s}"
    blif0 = root / "netlists" / "base" / d / "netlist" / f"{d}.blif"
    arch = root / "arch" / f"{d}.xml"
    base = out / "work" / f"q6-{a.arm}" / d / f"s{s}"
    final = out / "vpr" / f"q6a-{a.arm}" / d / f"vpr_sa.s{s}"
    log = {"design": d, "seed": s, "arm": a.arm, "k": a.k, "R": a.rounds, "rounds": [], "copies": 0, "moves": 0, "refused": 0}
    # the spare arm's start run packed a different BLIF? no: same BLIF, different packing; the start flat placement carries it
    cur_blif, cur_flat = blif0, start / "final.flat_place"
    best = None
    for r in range(a.rounds + 1):
        rd = base / f"r{r}"
        if r > 0:
            prev = base / f"r{r-1}"
            pos, typ = read_flat(cur_flat)
            paths = parse_paths((prev / "report_timing.setup.rpt").read_text(errors="replace"))
            bl = Blif(cur_blif)
            if bl.cont:
                log["stop"] = "blif has continuation lines"
                break
            chosen, model = candidates(paths, pos, typ, bl, a.maxdist, a.k, occupancy(prev, d), clb_tiles(arch))
            if not chosen:
                log["stop"] = "no candidate with gain"
                break
            edits, newpos, extra = [], dict(pos), {}
            rinfo = {"round": r, "model": model, "cands": []}
            for i, (sn, q, t, g) in enumerate(chosen):
                if bl.fan.get(sn, 0) == 1:
                    newpos[sn] = t
                    rinfo["cands"].append([sn, q, list(t), round(g, 3), "move"])
                    log["moves"] += 1
                else:
                    sn2 = f"{sn}__dup{r}_{i}"
                    edits.append((sn, sn2, q))
                    extra[sn2] = t
                    rinfo["cands"].append([sn, q, list(t), round(g, 3), "copy"])
                    log["copies"] += 1
            rd.mkdir(parents=True, exist_ok=True)
            nb = rd / f"{d}.blif"
            if edits:
                edit_blif(cur_blif, edits, nb)
                eq, msg = cec(str(blif0), str(nb))
                rinfo["equiv"] = eq
                if not eq:
                    log["stop"] = "EQUIVALENCE FAILED: " + msg
                    log["rounds"].append(rinfo)
                    break
            else:
                shutil.copy(cur_blif, nb)
                rinfo["equiv"] = "no netlist change"
            nf = rd / "in.flat_place"
            write_flat(nf, newpos, extra)
            res = vpr(rd, arch, nb, nf, s)
            rinfo.update(res)
            log["rounds"].append(rinfo)
            if not res["ok"]:
                log["refused"] += 1
                log["stop"] = "VPR refused or unroutable"
                break
            if best is None or res["cpd"] < best[0]:
                best = (res["cpd"], r)
                cur_blif, cur_flat = nb, rd / "final.flat_place"
            else:
                log["stop"] = "guard: round not better than best, previous kept"
                break
        else:
            rd.mkdir(parents=True, exist_ok=True)
            res = vpr(rd, arch, blif0, cur_flat, s)
            log["rounds"].append({"round": 0, **res})
            if not res["ok"]:
                log["stop"] = "round 0 failed"
                break
            best = (res["cpd"], 0)
            cur_flat = rd / "final.flat_place"
            if a.zero:
                log["stop"] = "zero"
                break
    else:
        log["stop"] = "rounds done"
    if best:
        final.mkdir(parents=True, exist_ok=True)
        br = base / f"r{best[1]}"
        for f in ("vpr.out", "report_timing.setup.rpt", "mimir-run.json", "final.flat_place"):
            if (br / f).is_file():
                shutil.copy(br / f, final / f)
        log["best_round"] = best[1]
        log["best_blif"] = str(br / f"{d}.blif") if best[1] else str(blif0)
    (base / "dup.json").parent.mkdir(parents=True, exist_ok=True)
    (base / "dup.json").write_text(json.dumps(log, indent=1) + "\n")
    print(json.dumps({k: log[k] for k in ("design", "seed", "copies", "moves", "stop") if k in log}), [r.get("cpd") for r in log["rounds"]], flush=True)


if __name__ == "__main__":
    main()
