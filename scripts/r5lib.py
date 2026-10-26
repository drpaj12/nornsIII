"""Round-5 helpers: synthesis, keep check, labels, cut, purity against the known blocks (docs/plan/round5.md)."""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

import nornlib as nl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
import r5gen  # noqa: E402

DATA5 = nl.DATA / "r5"
CONSTS = ("gnd", "vcc", "unconn")
BLOCK = re.compile(r"^b(\d+)$")
PO = re.compile(r"^po\[(\d+)\]$")
BETA_KNOWN = 100.0
N_NULL = 50
NULL_SEED = 20261026


def src_dir(design: str) -> Path:
    return nl.runs_dir(design, "src")


def verilog_path(design: str) -> Path:
    return src_dir(design) / f"{design}.v"


def use_generated_sources() -> None:
    """Point nornlib (odin_script, timing4.ensure_json, build_words) at the generated Verilog."""
    nl.design_verilog = verilog_path  # type: ignore[assignment]


def write_sources(design: str) -> dict:
    spec = r5gen.build_spec(design)
    text = r5gen.verilog(spec)
    nl.ensure_dir(src_dir(design))
    verilog_path(design).write_text(text, encoding="utf-8")
    nl.write_json(src_dir(design) / "spec.json", spec)
    return r5gen.summary(spec, text)


def read_spec(design: str) -> dict:
    return nl.read_json(src_dir(design) / "spec.json")


def synth(design: str) -> int:
    use_generated_sources()
    out = nl.runs_dir(design, "netlist", f"{design}.blif")
    nl.ensure_dir(out.parent)
    script = nl.odin_script(design, out)
    return nl.run([str(nl.ODIN3), "-p", script], cwd=out.parent, env=nl.odin_env(), stdout=out.parent / "pre.log")


# ---------------------------------------------------------------------------------------
# labels

def label_of(name: str, spec: dict | None) -> tuple[int | None, str]:
    """(block index, how): 'path' = the provenance path component b<k>; 'spec' = a flip-flop Odin names after a
    primary output (`po[p]`), labelled from the designed spec (docs/plan/round5.md amendment 1); (None, '') else."""
    m = BLOCK.match(nl.module_of(name))
    if m:
        return int(m.group(1)), "path"
    m = PO.match(name)
    if m and spec is not None:
        return spec["po"][int(m.group(1))][0], "spec"
    return None, ""


def parse(design: str) -> dict:
    return nl.parse_blif(nl.runs_dir(design, "netlist", f"{design}.blif"), None, nl.arch_output_ports(nl.ARCH))


def atoms_of(parsed: dict) -> list[dict]:
    return [b for b in parsed["blocks"] if b["kind"] in ("lut", "latch") and b["name"] not in CONSTS]


def cut_of(parsed: dict, cluster) -> int:
    """Non-clock nets whose pins lie in more than one cluster. `cluster(atom name)` -> id or None (atom ignored);
    every primary input and output is its own pad cluster."""
    pis = {n for n in parsed["inputs"]}
    pos = set(parsed["outputs"])
    drivers = {b["name"]: b for b in atoms_of(parsed)}
    pins: dict[str, set] = {}
    for b in atoms_of(parsed):
        c = cluster(b["name"])
        if c is None:
            continue
        pins.setdefault(b["name"], set()).add(c)
        for n in b["inputs"]:
            if n in CONSTS:
                continue
            pins.setdefault(n, set()).add(c)
    for n in pis:
        if n in pins:
            pins[n].add(("pad", n))
    for n in pos:
        if n in drivers:
            pins.setdefault(n, set()).add(("pad", n))
    return sum(1 for s in pins.values() if len(s) > 1)


def keep_check(design: str) -> dict:
    spec = read_spec(design)
    b = spec["b"]
    parsed = parse(design)
    atoms = atoms_of(parsed)
    luts = [a for a in atoms if a["kind"] == "lut"]
    ffs = [a for a in atoms if a["kind"] == "latch"]
    lab: dict[str, int] = {}
    how = {"path": 0, "spec": 0}
    for a in atoms:
        k, h = label_of(a["name"], spec)
        if k is not None:
            lab[a["name"]] = k
            how[h] += 1
    per_l = [0] * b
    per_f = [0] * b
    for a in luts:
        if a["name"] in lab:
            per_l[lab[a["name"]]] += 1
    for a in ffs:
        if a["name"] in lab:
            per_f[lab[a["name"]]] += 1
    ext: list[set] = [set() for _ in range(b)]
    driver = {a["name"]: lab.get(a["name"]) for a in atoms}
    for a in atoms:
        k = lab.get(a["name"])
        if k is None:
            continue
        for n in a["inputs"]:
            if n in CONSTS:
                continue
            if n in driver and driver[n] == k:
                continue
            ext[k].add(n)
    measured = cut_of(parsed, lambda x: lab.get(x))
    designed = spec["designed_cut"]
    unl = len(atoms) - len(lab)
    k1 = len(luts) == 10 * b and len(ffs) == 10 * b
    k2 = max(per_l) <= 10 and max(per_f) <= 10 and max(len(s) for s in ext) <= 40
    k3_path = how["path"] >= 0.99 * len(atoms)
    k3 = unl <= 0.01 * len(atoms)
    k4 = abs(measured - designed) <= 0.10 * designed
    return {"design": design, "b": b, "luts": len(luts), "ffs": len(ffs), "labelled_path": how["path"],
            "labelled_spec": how["spec"], "unlabelled": unl, "max_luts_block": max(per_l), "max_ffs_block": max(per_f),
            "max_inputs_block": max(len(s) for s in ext), "designed_cut": designed, "measured_cut": measured,
            "k1": k1, "k2": k2, "k3": k3, "k3_path_only": k3_path, "k4": k4,
            "kept": bool(k1 and k2 and k3 and k4),
            "kept_original_rule": bool(k1 and k2 and k3_path and k4),
            "failing": [n for n, v in (("k1", k1), ("k2", k2), ("k3", k3), ("k4", k4)) if not v]}


# ---------------------------------------------------------------------------------------
# packings against the known blocks

def known_labels(design: str) -> dict[str, int]:
    """Block label of every atom VPR has (the vpr view of the round-4 affinity builder)."""
    import affinity as af
    spec = read_spec(design)
    out = {}
    for a in af.logic_atoms(design, True):
        k, _ = label_of(a, spec)
        if k is not None:
            out[a] = k
    return out


def write_known_affinity(design: str) -> int:
    import affinity as af
    lab = known_labels(design)
    path = af.affinity_path(design, "known", "r5")
    nl.ensure_dir(path.parent)
    path.write_text("".join(f"{a}\t{k}\n" for a, k in sorted(lab.items())), encoding="utf-8")
    return len(lab)


def packing_vs_blocks(design: str, flat_path: Path) -> dict:
    """Purity, exact blocks, null purity, logic CLB count and cut of a packing against the known blocks."""
    import r3lib
    lab = known_labels(design)
    groups = r3lib.logic_groups(flat_path)
    members = {c: [a for a in v if a in lab] for c, v in groups.items()}
    total = sum(len(v) for v in members.values())

    def pur(g: dict[str, list[int]]) -> float:
        best = 0
        for v in g.values():
            if v:
                counts: dict[int, int] = {}
                for k in v:
                    counts[k] = counts.get(k, 0) + 1
                best += max(counts.values())
        return best / total if total else float("nan")

    g_lab = {c: [lab[a] for a in v] for c, v in members.items()}
    purity = pur(g_lab)
    sizes = [len(v) for v in members.values()]
    pool = [k for v in g_lab.values() for k in v]
    rng = random.Random(f"{NULL_SEED}:{design}")
    nulls = []
    for _ in range(N_NULL):
        rng.shuffle(pool)
        i, g = 0, {}
        for c, s in enumerate(sizes):
            g[c] = pool[i:i + s]
            i += s
        nulls.append(pur(g))
    where: dict[int, set] = {}
    for c, v in g_lab.items():
        for k in set(v):
            where.setdefault(k, set()).add(c)
    atoms_per_block: dict[int, int] = {}
    for k in lab.values():
        atoms_per_block[k] = atoms_per_block.get(k, 0) + 1
    exact = 0
    for k, cs in where.items():
        if len(cs) == 1:
            c = next(iter(cs))
            if len(g_lab[c]) == atoms_per_block[k] == len(groups[c]):
                exact += 1
    n_blocks = len(atoms_per_block)
    flat = nl.Flat(flat_path)
    parsed = parse(design)
    cut = cut_of(parsed, lambda x: flat.clb_of(x))
    return {"logic_clbs": len(groups), "purity": purity, "null_purity": sum(nulls) / len(nulls),
            "null_purity_max": max(nulls), "exact_blocks": exact, "n_blocks": n_blocks,
            "reproduction": exact / n_blocks if n_blocks else float("nan"), "cut": cut,
            "labelled_in_logic": total}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.is_file() else []
