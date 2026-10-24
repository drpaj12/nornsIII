"""Round-2 seeds: bitwise (word) seeds, the random start and the coarse-random arms.

Word membership comes from scripts/build_words.py (Odin III provenance: HDL bus names and
source spans joined to the BLIF by net id). Seed families written here (each as
seeds/<name>-full.place, -inter.place, -hard.xml like build_seeds.py, and merged into
seeds/clusters.json):

  words          each word's CLBs form one cluster, quotient-graph layout; blocks outside any
                 word stay in their Urd module cluster
  slices         the same clusters, each word laid out as a vertical run in bit order
                 (the carry-chain direction, top = bit 0), runs of equal length aligned to the
                 same rows; carry chains stay what they are
  hier           Urd module clusters at the coarse level; inside each module the words are
                 bit-sliced runs
  words_partial  only the word CLBs are seeded; every other CLB keeps VPR's analytic position
  random         a random legal placement (the true random start, RQ-N4)
  urd_shuf, words_shuf, slices_shuf, hier_shuf, words_partial_shuf
                 the coarse-random arm: clusters kept, cluster positions permuted

Usage: python scripts/build_word_seeds.py [--only=a,b] [design ...]
"""

from __future__ import annotations

import collections
import os
import statistics
import sys

import build_seeds as bs
import nornlib as nl


def prepare(design: str):
    blif = nl.runs_dir(design, "netlist", f"{design}.blif")
    init_place, final_flat, _log = bs.baseline_paths(design)
    flat = nl.Flat(final_flat)
    parsed = nl.parse_blif(blif, set(flat.atoms), nl.arch_output_ports(nl.ARCH))
    blocks = parsed["blocks"]
    place = nl.Place(init_place)
    chains = bs.adder_chains(blocks, flat, {r["num"]: r["name"] for r in place.rows})
    clb_types = {clb: bs.classify(t) for clb, t in flat.clb_types().items()}
    clb_class = {r["name"]: clb_types.get(r["num"], "logic") for r in place.rows}
    clb_atoms: dict[str, list[str]] = collections.defaultdict(list)
    for atom, row in flat.atoms.items():
        clb_atoms[row[4]].append(atom)
    base_slots = collections.defaultdict(list)
    for r in place.rows:
        base_slots[clb_class.get(r["name"], "logic")].append(
            (int(r["x"]), int(r["y"]), int(r["sub"]), int(r["layer"])))
    return blif, flat, blocks, place, chains, clb_class, clb_atoms, base_slots


def majority(place, clb_atoms, mapping) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for clb in place.rows:
        counts = collections.Counter()
        for atom in clb_atoms.get(clb["num"], []):
            if atom in mapping:
                counts[mapping[atom]] += 1
        out[clb["name"]] = counts.most_common(1)[0][0] if counts else None
    return out


WORD_SHARE = 1 / 3  # a CLB joins a word cluster when >= this share of its atoms are word atoms


def majority_word(place, clb_atoms, word_map: dict[str, int]) -> dict[str, int | None]:
    """CLB -> its plurality word, or None when fewer than WORD_SHARE of its atoms are word atoms
    (the CLB then keeps its module cluster; ABC's cone provenance leaves most LUTs word-less)."""
    out: dict[str, int | None] = {}
    for clb in place.rows:
        atoms = clb_atoms.get(clb["num"], [])
        hits = collections.Counter(word_map[a] for a in atoms if a in word_map)
        if atoms and hits and sum(hits.values()) / len(atoms) >= WORD_SHARE - 1e-9:
            out[clb["name"]] = hits.most_common(1)[0][0]
        else:
            out[clb["name"]] = None
    return out


def build(design: str, only: set[str] | None = None) -> int:
    words_path = nl.runs_dir(design, "words", "members.json")
    if not words_path.is_file():
        print(f"{design}: no word membership (run build_words.py)")
        return 2
    blif, flat, blocks, place, chains, clb_class, clb_atoms, base_slots = prepare(design)
    width, height = nl.grid_size(place)
    members = nl.read_json(words_path)
    urd = bs.block_clusters(design, blocks)["urd"]
    word_ids = sorted({m["word"] for m in members.values() if m["word"]})
    widx = {w: i for i, w in enumerate(word_ids)}
    offset = len(word_ids)
    words_map: dict[str, int] = {}
    for b in blocks:
        name = str(b["name"])
        m = members.get(name)
        words_map[name] = widx[m["word"]] if m and m["word"] else offset + urd[name]
    only_words = {n: widx[m["word"]] for n, m in members.items() if m["word"]}
    word_of_clb = majority_word(place, clb_atoms, only_words)
    mod_of_clb = majority(place, clb_atoms, urd)
    cluster_of = {  # words family: word if the CLB is word-dominated, else its module cluster
        "words": {c: (word_of_clb[c] if word_of_clb[c] is not None
                      else (offset + mod_of_clb[c] if mod_of_clb[c] is not None else None))
                  for c in word_of_clb},
        "urd": mod_of_clb,
    }
    chain_clbs = {c for ch in chains for c in ch["clbs"]}
    # bit order of a CLB inside its word: median bit index of its word atoms (unknown: last)
    bit_of_clb: dict[str, float] = {}
    for clb in place.rows:
        bits = [members[a]["bit"] for a in clb_atoms.get(clb["num"], [])
                if a in members and members[a]["word"] and members[a]["bit"] >= 0]
        bit_of_clb[clb["name"]] = statistics.median(bits) if bits else 1e9
    runs: list[dict[str, object]] = []
    word_clbs: dict[int, list[str]] = collections.defaultdict(list)
    for clb, cl in cluster_of["words"].items():
        if cl is not None and cl < offset and clb_class.get(clb) == "logic":
            word_clbs[cl].append(clb)
    for cl, names in sorted(word_clbs.items()):
        names = [n for n in names if n not in chain_clbs]
        if len(names) >= 2:
            ordered = sorted(names, key=lambda n: (bit_of_clb[n], n))
            runs.append({"blocks": ordered, "clbs": ordered, "word": cl})
    inner = {}
    for clb, cl in word_of_clb.items():
        if cl is not None and clb_class.get(clb) == "logic" and clb not in chain_clbs:
            inner[clb] = (str(cl), bit_of_clb[clb])
    # partial: only CLBs whose majority is a word cluster are seeded; the rest stay put,
    # and so does every carry chain that has a fixed CLB
    base_xy = {r["name"]: (int(r["x"]), int(r["y"]), int(r["sub"]), int(r["layer"]))
               for r in place.rows}
    seeded = {c for c, cl in cluster_of["words"].items()
              if cl is not None and cl < offset and clb_class.get(c) in ("logic", "memory")}
    fixed_names = {c for c in base_xy if c not in seeded}
    for ch in chains:
        if any(c in fixed_names for c in ch["clbs"]):
            fixed_names |= set(ch["clbs"])
    seeded -= fixed_names
    fixed = {c: base_xy[c] for c in fixed_names if clb_class.get(c) in ("logic", "memory")}

    def to_clusters(per: dict[str, int | None], keep=None) -> dict[int, list[str]]:
        out: dict[int, list[str]] = collections.defaultdict(list)
        for clb, cl in per.items():
            if cl is not None and clb_class.get(clb) not in ("pad", "mult") and \
                    (keep is None or clb in keep):
                out[cl].append(clb)
        return out

    def run(seed: str, per, mapping, **kw) -> None:
        if only and seed not in only:
            return
        clusters = to_clusters(per, kw.pop("keep", None))
        if not clusters:
            return
        res = bs.build_seed(design, seed, clusters, clb_class, base_slots, place, width,
                            height, blocks, mapping, flat, chains, **kw)
        result["seeds"][seed] = res
        print(f"{design}/{seed}: {len(clusters)} clusters, "
              f"{sum(len(v) for v in clusters.values())} CLBs")

    path = nl.runs_dir(design, "seeds", "clusters.json")
    result = nl.read_json(path) if path.is_file() else {"design": design, "seeds": {}}
    run("words", cluster_of["words"], words_map)
    wcl = {cl for cl in word_clbs}
    if os.environ.get("NORNS_NO_BIT_FALLBACK"):  # audit only (scripts/audit_seeds.py)
        wcl = set()
    run("slices", cluster_of["words"], words_map, extra_runs=runs, bit_order=bit_of_clb,
        bit_clusters=wcl)
    run("hier", cluster_of["urd"], urd, inner=inner)
    run("words_partial", cluster_of["words"], only_words, fixed=fixed, keep=seeded)
    per_clb = {r["name"]: i for i, r in enumerate(place.rows)}
    run("random", per_clb, {}, layout="random")
    run("words_partial_shuf", cluster_of["words"], only_words, layout="shuffle", fixed=fixed,
        keep=seeded)
    run("urd_shuf", cluster_of["urd"], urd, layout="shuffle")
    run("words_shuf", cluster_of["words"], words_map, layout="shuffle")
    run("slices_shuf", cluster_of["words"], words_map, layout="shuffle", extra_runs=runs,
        bit_order=bit_of_clb, bit_clusters=wcl)
    run("hier_shuf", cluster_of["urd"], urd, layout="shuffle", inner=inner)
    nl.write_json(path, result)
    return 0


def main(argv: list[str]) -> int:
    only = None
    if argv and argv[0].startswith("--only="):
        only = set(argv[0].split("=", 1)[1].split(","))
        argv = argv[1:]
    rc = 0
    for design in argv or list(nl.DESIGN_ORDER):
        rc |= build(design, only)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
