"""RQ-N15: RTL-level depth estimate per HDL statement (a text heuristic, docs/plan/round4.md) against the
Odin III attribution of the routed stock/analytic run (seed 1).

  python scripts/r4depth.py [design ...]       writes data/<d>/r4depth.json; needs runs/<d>/r4/stock.analytic.s1/attr.json

d_own = weighted operator count of a statement's right-hand side (+, -: 2; *: 4; << >> & | ^ ~ ! && || comparisons and ?:
: 1; concatenation and selects: 0). d_chain = d_own + the largest d_chain among the combinational (assign or blocking)
statements that define an identifier on the right-hand side (a statement already on the stack adds 0; non-blocking
assignments end a chain). Statements are found by a line scanner (a statement runs to its `;`), so this is an
estimate from text, not from the Odin III netlist.
"""

from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

import nornlib as nl

KEYWORDS = {"if", "else", "begin", "end", "case", "endcase", "always", "assign", "posedge", "negedge", "or", "and",
            "wire", "reg", "input", "output", "inout", "module", "endmodule", "default", "parameter", "integer",
            "for", "while", "generate", "endgenerate", "function", "endfunction", "initial", "signed"}
WEIGHTS = (("<<", 1), (">>", 1), ("&&", 1), ("||", 1), ("==", 1), ("!=", 1), ("<=", 1), (">=", 1), ("^~", 1),
           ("~^", 1), ("+", 2), ("-", 2), ("*", 4), ("&", 1), ("|", 1), ("^", 1), ("~", 1), ("!", 1), ("<", 1),
           (">", 1), ("?", 1))
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
HEADER = re.compile(r"\balways\s*@\s*\([^)]*\)|\balways\s*@\s*\*|\b(begin|end|else)\b")
NUM = re.compile(r"\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ]+|\b\d+\b")


def statements(path: Path) -> dict[int, dict]:
    """start line -> {kind, lhs, rhs, d_own} for the statements of one Verilog file."""
    text = path.read_text(errors="replace")
    text = COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    out: dict[int, dict] = {}
    buf, start = "", 0
    for no, line in enumerate(text.splitlines(), 1):
        for piece in re.split(r"(;)", line):
            if piece == ";":
                stmt = buf.strip()
                if stmt and start:
                    parsed = parse_statement(stmt)
                    if parsed:
                        out[start] = parsed
                buf, start = "", 0
            elif piece.strip():
                if not buf.strip():
                    start = no
                buf += " " + piece
    return out


def strip_if(stmt: str) -> str:
    """Drop leading `if (cond)` conditions (they select; the heuristic counts the data expression)."""
    while True:
        m = re.match(r"^\s*if\s*\(", stmt)
        if not m:
            return stmt
        depth, i = 1, m.end()
        while i < len(stmt) and depth:
            depth += {"(": 1, ")": -1}.get(stmt[i], 0)
            i += 1
        stmt = stmt[i:]


def parse_statement(stmt: str) -> dict | None:
    stmt = HEADER.sub(" ", stmt)
    stmt = re.sub(r"^\s*(input|output|inout|wire|reg|parameter|integer)\b.*$", "", stmt)
    stmt = strip_if(stmt)
    while re.match(r"^\s*(?:default|[\w']+(?:\s*,\s*[\w']+)*)\s*:(?!=)", stmt):  # case labels
        stmt = re.sub(r"^\s*(?:default|[\w']+(?:\s*,\s*[\w']+)*)\s*:", "", stmt, count=1)
        stmt = strip_if(stmt)
    m = re.match(r"^\s*(?:assign\s+)?(?:\w+\s+)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*(<=|=)(?!=)\s*(.*)$", stmt, re.S)
    if not m:
        return None
    lhs, op, rhs = m.group(1), m.group(2), m.group(3)
    if lhs in KEYWORDS:
        return None
    ops_text = NUM.sub(" ", rhs)
    d = 0
    rest = ops_text
    for sym, w in WEIGHTS:
        n = rest.count(sym)
        d += n * w
        rest = rest.replace(sym, " ")
    ids = {t for t in re.findall(r"[A-Za-z_]\w*", NUM.sub(" ", rhs)) if t not in KEYWORDS}
    return {"kind": "nb" if op == "<=" else "comb", "lhs": lhs, "rhs_ids": sorted(ids), "d_own": d}


def chain_depths(stmts: dict[int, dict]) -> dict[int, int]:
    defs: dict[str, list[int]] = collections.defaultdict(list)
    for line, s in stmts.items():
        if s["kind"] == "comb":
            defs[s["lhs"]].append(line)
    memo: dict[int, int] = {}

    def depth(line: int, stack: set[int]) -> int:
        if line in memo:
            return memo[line]
        if line in stack:
            return 0
        stack = stack | {line}
        s = stmts[line]
        best = 0
        for ident in s["rhs_ids"]:
            for dl in defs.get(ident, []):
                if dl != line:
                    best = max(best, depth(dl, stack))
        memo[line] = s["d_own"] + best
        return memo[line]

    sys.setrecursionlimit(20000)
    return {line: depth(line, set()) for line in stmts}


def spearman(x: list[float], y: list[float]) -> float | None:
    from scipy import stats
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return float(stats.spearmanr(x, y).statistic)


def analyse(design: str) -> dict:
    attr = nl.read_json(nl.runs_dir(design, "r4", "stock.analytic.s1", "attr.json"))
    cache: dict[str, tuple[dict, dict]] = {}
    xs: list[float] = []
    ys: list[float] = []
    rows = []
    miss = 0
    for sp in attr["spans"]:
        f = sp["file"]
        if f not in cache:
            p = Path(f)
            if not p.is_file():
                cache[f] = ({}, {})
            else:
                st = statements(p)
                cache[f] = (st, chain_depths(st))
        st, cd = cache[f]
        # the statement that starts on the span's line, else the nearest start line above it within 12 lines
        line = sp["line"]
        cand = [k for k in st if line - 12 <= k <= line]
        if not cand:
            miss += 1
            continue
        k = max(cand)
        xs.append(float(cd[k]))
        ys.append(float(sp["critical_delay_ns"]))
        rows.append({"span": sp["id"], "d_chain": cd[k], "d_own": st[k]["d_own"], "critical_delay_ns": sp["critical_delay_ns"]})
    top = 5
    by_d = {r["span"] for r in sorted(rows, key=lambda r: (-r["d_chain"], r["span"]))[:top]}
    by_t = {r["span"] for r in sorted(rows, key=lambda r: (-r["critical_delay_ns"], r["span"]))[:top]}
    n = len(rows)
    res = {"design": design, "spans_total": len(attr["spans"]), "spans_used": n, "spans_unmatched_to_statement": miss,
           "rho": spearman(xs, ys) if n >= 8 else None, "top5_overlap": len(by_d & by_t),
           "top5_expected": (top * top / n) if n else None, "enough": n >= 8}
    return res


def run(designs: list[str]) -> int:
    for design in designs:
        if not nl.runs_dir(design, "r4", "stock.analytic.s1", "attr.json").is_file():
            continue
        res = analyse(design)
        nl.write_json(nl.DATA / design / "r4depth.json", res)
        print(design, res, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:] or list(nl.DESIGN_ORDER)))
