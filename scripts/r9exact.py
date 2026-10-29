"""Round 9 stage 3a: the `exact` arm. VPR places and routes EXACTLY the clustering C (docs/plan/round9-tpeko-real.md, entry 2026-10-29 (b)).

  python scripts/r9exact.py build DESIGN [--cons own,foreign] [--shuffles 1,2,3]   # writes exact.net per shuffle
  python scripts/r9exact.py run DESIGN [--cons ...] [--shuffles ...] [--seeds 1,2,3]  # vpr --net_file exact.net, place + route

Method: every cluster of C is packed ALONE by stock VPR (its external nets become pads), which gives VPR's own legal intra-cluster
routing for that cluster. The CLB blocks of these single-cluster packings are copied into one `.net` file, whose pads, memories and
header come from the stock packing of the full shuffled netlist. VPR then runs place and route on that file (`--net_file`, no
packing), so the clusters are C exactly: purity 1, CLBs = K. A cluster that the default AAPack options cannot pack into one CLB
alone is retried with other packer options (`VARIANTS`); a cluster none of them packs is reported and the design has no exact arm.
Run outputs are under $R9_OUT, never deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import r9build as rb
import r9run as rr

VARIANTS = (
    (),
    ("--alpha_clustering", "0.5"),
    ("--connection_driven_clustering", "off"),
    ("--timing_driven_clustering", "off"),
    ("--allow_unrelated_clustering", "on"),
    ("--cluster_seed_type", "blend"),
    ("--cluster_seed_type", "max_inputs", "--connection_driven_clustering", "off"),
    ("--timing_driven_clustering", "off", "--connection_driven_clustering", "off", "--allow_unrelated_clustering", "on"),
    ("--target_ext_pin_util", "1.0,1.0"),
    ("--target_ext_pin_util", "1.0,1.0", "--timing_driven_clustering", "off"),
)


def statements(text: str) -> tuple:
    """(header dict, list of (kind, driven nets, read nets, text)) of a plain BLIF as written by r9build."""
    lines = rb.logical_lines(text)
    stm, cur = [], None
    for ln in lines:
        if ln.startswith("."):
            if cur:
                stm.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur:
        stm.append(cur)
    out = []
    for s in stm:
        t = s[0].split()
        if t[0] == ".names":
            out.append(("names", [t[-1]], t[1:-1], s))
        elif t[0] == ".latch":
            out.append(("latch", [t[2]], [t[1]], s))
        elif t[0] == ".subckt":
            kv = [x.split("=", 1) for x in t[2:]]
            if t[1] == "adder":
                out.append(("adder", [n for p, n in kv if p in ("sumout", "cout")], [n for p, n in kv if p not in ("sumout", "cout")], s))
            else:
                out.append(("hard", [], [], s))
        elif t[0] in (".inputs", ".outputs", ".model", ".end"):
            out.append((t[0][1:], t[1:], [], s))
    return out


def cluster_blifs(blif: Path, aff: Path, real_const: set) -> dict:
    """cluster -> BLIF text, from the shuffled design file and its affinity labels (atom -> cluster)."""
    lab = {}
    for ln in aff.read_text().splitlines():
        a, c = ln.split("\t")
        lab[a] = int(c)
    stm = statements(blif.read_text().split(".end")[0] + ".end\n")
    pos = set()
    clk = "clk"
    logic = []
    for kind, a, b, s in stm:
        if kind == "outputs":
            pos.update(a)
        elif kind == "inputs":
            clk = a[0]
        elif kind in ("names", "latch", "adder"):
            logic.append((kind, a, b, s))
    atom_of = []
    for kind, a, b, s in logic:
        if kind == "names":
            atom_of.append(lab.get(a[0]))
        elif kind == "latch":
            atom_of.append(lab.get(a[0]))
        else:
            atom_of.append(lab.get(next(n for n in a if n in lab), None) if any(n in lab for n in a) else None)
    # a LUT whose output only feeds a latch of the same cluster is internal; label of a .names also set via lut net
    drv = {}
    for i, (kind, a, b, s) in enumerate(logic):
        for n in a:
            drv[n] = i
    readers: dict = {}
    for i, (kind, a, b, s) in enumerate(logic):
        for n in b:
            readers.setdefault(n, []).append(i)
    # hard-block readers: any net named in a hard subckt counts as an outside reader
    hard_nets = set()
    for kind, a, b, s in stm:
        if kind == "hard":
            hard_nets.update(x.split("=", 1)[1] for x in s[0].split()[2:])
    out: dict = {}
    members: dict = {}
    for i, c in enumerate(atom_of):
        if c is None:
            kind, a, b, s = logic[i]
            if kind == "names" and ((a[0] in pos and all(x in rb.CONST for x in b)) or not b):
                continue  # constant-driven primary output (a buffer VPR absorbs) or an unlabelled constant generator
            raise ValueError(f"unlabelled statement {logic[i][3][0]}")
        members.setdefault(c, []).append(i)
    for c, ms in members.items():
        mset = set(ms)
        pis, pouts, body = set(), set(), []
        for i in ms:
            kind, a, b, s = logic[i]
            if kind == "names" and not b and a[0] in rb.CONST:
                continue  # constant generator: VPR keeps no atom for it in the full packing, so it is in no packed cluster
            body += s
            for n in b:
                if (drv.get(n) not in mset or n in rb.CONST) and n != clk and (n not in rb.CONST or n in real_const):
                    pis.add(n)
            for n in a:
                rd = readers.get(n, [])
                if kind == "adder" and any(
                        p.startswith("cout=") and p.split("=", 1)[1] == n for p in s[0].split()[2:]):
                    # carry out: a pad only if somebody outside reads it
                    if any(r not in mset for r in rd) or n in pos or n in hard_nets:
                        pouts.add(n)
                    continue
                if any(r not in mset for r in rd) or n in pos or n in hard_nets or not rd:
                    pouts.add(n)
        out[c] = "\n".join([f".model c{c}", ".inputs " + clk + " " + " ".join(sorted(pis)), ".outputs " + " ".join(sorted(pouts))] + body + [".end"]) + "\n"
    return out


def inputs_ok(net: Path, text: str) -> bool:
    """Every net the cluster reads from outside (a pad of the single-cluster netlist) must reach a pin of the CLB."""
    toks = next(ln for ln in text.splitlines() if ln.startswith(".inputs")).split()[1:]
    pis = set(toks[1:])  # the first input is the clock (r9build writes it first), which is a clock pin, not an input pin
    clb = next(b for b in ET.parse(net).getroot().findall("block") if b.get("instance", "").startswith("clb["))
    have = set()
    for p in clb.find("inputs").findall("port"):
        have |= set(p.text.split())
    return pis <= have


def pack_alone(text: str, d: Path, tag: str) -> tuple:
    """Pack one cluster alone. Returns (net path, variant index) for the first variant that gives exactly one logic CLB."""
    d.mkdir(parents=True, exist_ok=True)
    tag = f"{tag}.{hashlib.sha256(text.encode()).hexdigest()[:8]}"  # keyed by content: a changed cluster never reuses an old packing
    p = d / f"{tag}.blif"
    p.write_text(text)
    for k, v in enumerate(VARIANTS):
        od = d / f"{tag}.v{k}"
        od.mkdir(exist_ok=True)
        net = od / (p.stem + ".net")
        if not net.is_file():
            cmd = ["flock", "-x", rb.LOCK, str(rb.STOCK_VPR), str(rb.ARCH), str(p), "--pack", "--seed", "1", *v]
            with (od / "pack.out").open("w") as fh:
                rcode = subprocess.run(cmd, cwd=od, stdout=fh, stderr=subprocess.STDOUT, check=False).returncode
            if rcode != 0:
                continue
        if net.is_file() and rb.count_clbs(net) == 1 and inputs_ok(net, text):
            return net, k
    return None, -1


def build_exact(design: str, cons: str, sh: int) -> dict:
    shd = rb.OUT_ROOT / design / cons / f"sh{sh}"
    blif, aff = shd / "design.blif", shd / "affinity.tsv"
    rec_p = shd / "exact10.json"
    if rec_p.is_file() and (shd / "exact10" / "design.net").is_file():
        return json.loads(rec_p.read_text())
    full = rb.run_vpr_pack(blif, shd / "pack")
    ftree = ET.parse(full)
    real_const = set()  # constant nets that the stock packing routes into a CLB input pin (the others are folded into the logic by VPR)
    for t in ftree.getroot().findall("block"):
        if t.get("instance", "").startswith("clb["):
            for p in t.find("inputs").findall("port"):
                real_const |= set(p.text.split()) & set(rb.CONST)
    cb = cluster_blifs(blif, aff, real_const)
    k = len(cb)
    clbs, variants, bad = [], {}, []
    for c in sorted(cb):
        net, v = pack_alone(cb[c], shd / "exact_parts", f"c{c}")
        if net is None:
            bad.append(c)
            continue
        variants[c] = v
        clbs.append((c, net))
    rec = {"K": k, "packed_alone": len(clbs), "unpackable": bad, "variants_used": variants}
    if bad:
        rec["ok"] = False
        rec_p.write_text(json.dumps(rec, indent=1, sort_keys=True))
        return rec
    tree = ftree
    root = tree.getroot()
    tops = root.findall("block")
    nonclb = [b for b in tops if not b.get("instance", "").startswith("clb[")]
    # constant generators (gnd, vcc) are implicit atoms. A CLB that holds only them is copied from the stock packing; one that was packed
    # with other logic there gets its generator as a CLB of its own (packed alone), which needs the net to be a real one
    constclb, covered, all_const = [], set(), set()
    for t in tops:
        leaves = [x.get("name") for x in t.iter("block") if not x.findall("block") and x.get("name") != "open"]
        in_const = {n for n in leaves if n in rb.CONST}
        all_const |= in_const
        if t.get("instance", "").startswith("clb[") and in_const and in_const == set(leaves):
            constclb.append(t)
            covered |= in_const
    for cn in sorted(all_const - covered):
        txt = f".model k{cn}\n.inputs clk\n.outputs {cn}\n.names {cn}\n" + ("1\n" if rb.CONST_VAL[cn] else "") + ".end\n"
        net, _v = pack_alone(txt, shd / "exact_parts", f"const_{cn}")
        if net is None or cn not in real_const:
            rec = {"K": k, "packed_alone": len(clbs), "unpackable": [f"const_{cn}"], "variants_used": variants, "ok": False}
            rec_p.write_text(json.dumps(rec, indent=1, sort_keys=True))
            return rec
        constclb.append(next(x for x in ET.parse(net).getroot().findall("block") if x.get("instance", "").startswith("clb[")))
    nonclb = [x for x in nonclb if x not in constclb]
    for b in tops:
        root.remove(b)
    final = []
    for _c, net in clbs:
        final.append(next(x for x in ET.parse(net).getroot().findall("block") if x.get("instance", "").startswith("clb[")))
    final += constclb + nonclb
    for i, blk in enumerate(final):  # VPR requires instance index == position in the file
        blk.set("instance", blk.get("instance").split("[")[0] + f"[{i}]")
        root.append(blk)
    rec["const_clbs"] = len(constclb)
    od = shd / "exact10"
    od.mkdir(exist_ok=True)
    tree.write(od / "design.net")
    rec["ok"] = True
    rec["io_hard_blocks"] = len(nonclb)
    rec["net_sha256"] = hashlib.sha256((od / "design.net").read_bytes()).hexdigest()
    rec_p.write_text(json.dumps(rec, indent=1, sort_keys=True))
    return rec


def run_exact(design: str, cons: str, sh: int, seed: int) -> dict:
    shd = rb.OUT_ROOT / design / cons / f"sh{sh}"
    cwd = shd / "exact10_run" / f"s{seed}"
    mp = cwd / "metrics.json"
    if mp.is_file():
        return json.loads(mp.read_text())
    cwd.mkdir(parents=True, exist_ok=True)
    blif = shd / "design.blif"
    flags = ["--net_file", str(shd / "exact10" / "design.net"), "--seed", str(seed), "--timing_report_npaths", str(rr.NPATHS)]
    cmd = ["prlimit", f"--as={rr.MEM_BYTES}", "flock", "-x", rb.LOCK, str(rb.STOCK_VPR), str(rb.ARCH), str(blif), "--place", "--route", "--analysis"] + flags
    log = cwd / "vpr.out"
    with log.open("w") as fh:
        try:
            rc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=rr.TIMEOUT, check=False).returncode
        except subprocess.TimeoutExpired:
            rc = -9
    rec = {"design": design, "cons": cons, "shuffle": sh, "arm": "exact", "vseed": seed, "rc": rc, "sha": rr.blif_sha(design, cons, sh)}
    if rc == 0:
        rec.update(rr.nl.Metrics(log).values)
        rec.pop("init_t", None)
        aff = {}
        for line in (shd / "affinity.tsv").read_text().splitlines():
            a, lab = line.split("\t")
            if a not in rb.CONST:
                aff[a] = int(lab)
        base = rb.OUT_ROOT / design / cons
        struct = json.loads((base / "struct.json").read_text())
        struct["cut_star_C"] = json.loads((base / "build.json").read_text())["cut_star_C"]
        vatoms = json.loads((shd / "vatoms.json").read_text())
        rec.update(rr.pack_metrics(shd / "exact10" / "design.net", aff, struct, vatoms))
    else:
        rec["error"] = "timeout" if rc == -9 else "see vpr.out"
    mp.write_text(json.dumps(rec, sort_keys=True))
    with (rb.OUT_ROOT / "runs.jsonl").open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"{design}/{cons}/sh{sh}/exact.s{seed}: rc={rc} clbs={rec.get('logic_clbs')} purity={rec.get('purity')} "
          f"wl={rec.get('wirelength')} cpd={rec.get('cpd_ns')} W={rec.get('chan_width')}", flush=True)
    return rec


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--cons", default="own,foreign")
    ap.add_argument("--shuffles", default="1,2,3")
    ap.add_argument("--seeds", default="1,2,3")
    a = ap.parse_args(argv)
    for d in a.designs:
        for c in a.cons.split(","):
            for sh in [int(x) for x in a.shuffles.split(",")]:
                rec = build_exact(d, c, sh)
                print(d, c, f"sh{sh}", "K", rec["K"], "packed_alone", rec["packed_alone"], "unpackable", rec["unpackable"],
                      "variants", sorted(set(rec["variants_used"].values())), flush=True)
                if a.mode == "run" and rec["ok"]:
                    for s in [int(x) for x in a.seeds.split(",")]:
                        run_exact(d, c, sh, s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
