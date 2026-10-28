"""Run records for Mimir III: one `mimir-run.json` per Norns run (stdlib only; Norns does not import mimir).

The record carries the full how-obtained data of a run: tool commits (how found, clean or dirty), binary
sha256 and `--version` text, the exact command lines (paths replaced by placeholders), every parameter as
{value, conf, source}, seed, host alias, time and peak RSS, input and artifact sha256 with relative paths.
The format is specified in mimirIII, docs/specs/2026-10-28-mimir-run-record.md (record_version 1); the
importer is `mimir import-runrecords`. Nothing here deletes a file.

    rec = RunRecorder(source, design, arm, seed, family, arch, roots={"run": cwd, ...})   # HostMapError: no host map
    rec.add_step(name, argv, rc, time_s, rss_mib, locked=...)   # one per tool run (vpr, nextpnr, scripts)
    rec.add_tool("vpr", tool_entry(tree, binary, ...))          # commit, clean flag, binary sha256 and version text
    rec.add_vpr_params(argv, log, tree, commit) / rec.add_nextpnr_params(argv, tree, commit, label, placer, ...)
    rec.add_input(role, path) / rec.add_artifact(role, path)
    rec.write(cwd / "mimir-run.json", required_inputs=..., required_artifacts=...)   # RecordRefused: privacy rule hit

Conf values are those of the Mimir schema: given, default (cited file:line at a named commit), default-unrecorded,
unknown. A value only inferred (for example a commit of a source tree that was dirty when the binary was built)
is recorded `unknown` with the source starting `inferred at record time`.
"""
from __future__ import annotations

import difflib
import fcntl
import getpass
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

RECORD_VERSION = 1
SHA40 = re.compile(r"[0-9a-f]{40}")
OPT_LINE = re.compile(r"^([A-Za-z_]\w*\.[\w.]+)\s*[:=]\s*(.*)$")
VPR_OPTIONS_HEAD = "VPR was run with the following options:"
ALIAS_RE = re.compile(r"host-\d+")
# an absolute path in a value (spec section 6): a slash that starts the string or follows a blank, `=`, `,`, `;`,
# `:`, a quote or a bracket and is followed by a path character; /dev/null is allowed
ABS_PATH = re.compile(r"(?:^|[\s=,;:'\"(\[])/(?!dev/null(?![\w.-]))[\w.~-]")
MAX_LISTED_DIFFS = 50


# ---------------------------------------------------------------- host alias (docs/specs/2026-10-28-mimir-host-alias.md)

class HostMapError(Exception):
    """The host map is not set, missing or unusable: no record is written."""


class RecordRefused(Exception):
    """The record holds a private string or an absolute path; `hits` are 'rule at key.path' texts (never a value)."""

    def __init__(self, hits: list[str]):
        super().__init__("; ".join(hits))
        self.hits = hits


def map_path() -> Path:
    """$MIMIR_HOST_MAP, else work/mimir-data/remote-private/hosts.toml of the workspace (Mimir's rule)."""
    env = os.environ.get("MIMIR_HOST_MAP")
    return Path(env) if env else Path.home() / "odin3-ws" / "work" / "mimir-data" / "remote-private" / "hosts.toml"


def _read_hosts(path: Path) -> dict[str, str]:
    table = tomllib.loads(path.read_text(encoding="utf-8")).get("hosts", {})
    return {str(k).lower(): str(v) for k, v in table.items()}


def host_table(path: Path | None = None) -> dict[str, str]:
    """Lower-cased real name -> alias of the [hosts] table, read under a shared flock when the lock file exists.
    HostMapError (naming MIMIR_HOST_MAP) when the map does not exist: an absent map is never an empty one."""
    path = path or map_path()
    if not path.is_file():
        raise HostMapError(f"host map '{path.name}' does not exist: set MIMIR_HOST_MAP to the private map "
                           "(created only by `mimir host-alias --init`); no run record is written without it")
    lock = path.with_name(path.name + ".lock")
    if not lock.exists():
        return _read_hosts(path)
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        return _read_hosts(path)
    finally:
        os.close(fd)


def host_alias(real: str | None = None, path: Path | None = None) -> str:
    """The alias of a host (this one by default) from the map; an alias maps to itself. A name that is not in the
    map gets `host-<max+1>` and one line is appended, as Mimir's `hostalias.alias_of` does: exclusive flock on
    `<map>.lock` (mode 600), the map re-read inside the lock, `O_APPEND` and `fsync`. The real name is never returned."""
    real = (real or platform.node()).strip()
    if not real:
        raise HostMapError("empty host name")
    if ALIAS_RE.fullmatch(real):
        return real
    path = path or map_path()
    key = real.lower()
    table = host_table(path)
    if key in table:
        return table[key]
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        table = _read_hosts(path)
        if key in table:
            return table[key]
        used = [int(a.split("-")[1]) for a in table.values() if ALIAS_RE.fullmatch(a)]
        alias = f"host-{max(used, default=0) + 1}"
        line = f"{json.dumps(key)} = {json.dumps(alias)}\n"  # a JSON string is a TOML basic string
        if path.stat().st_size and path.read_bytes()[-1:] != b"\n":
            line = "\n" + line  # an append never joins the last line of a map that lacks its final newline
        afd = os.open(path, os.O_WRONLY | os.O_APPEND)
        try:
            os.fchmod(afd, 0o600)
            os.write(afd, line.encode("utf-8"))
            os.fsync(afd)
        finally:
            os.close(afd)
        return alias
    finally:
        os.close(fd)  # closing releases the lock


# ---------------------------------------------------------------- git and binaries

def git(root: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def git_show(root: Path | None, commit: str, path: str) -> list[str] | None:
    """Lines of `path` as committed at `commit` (None when there is no tree, commit or file)."""
    if root is None or not commit:
        return None
    res = subprocess.run(["git", "-C", str(root), "show", f"{commit}:{path}"], capture_output=True, text=True, errors="replace", check=False)
    return res.stdout.split("\n") if res.returncode == 0 else None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_state(tree: Path, copy: Path, allowed_extra: tuple[str, ...] = (), exempt: dict[str, tuple[str, ...]] | None = None) -> dict[str, object]:
    """How a `git archive` copy used for a build differs from HEAD of `tree`:
    `differs` (tracked paths whose content differs or that are missing), `extra` (files in the copy that HEAD lacks),
    `sha256` (of each differing or extra file present), `unlisted` (the differences that are not listed exemptions)
    and `is_head` (no unlisted difference). An exemption `exempt[path]` holds the lines the build may add to that
    tracked file (checked by content: nothing removed, nothing else added); `allowed_extra` are extra files the
    build adds (an overlay). Both kinds stay recorded and hashed."""
    exempt = exempt or {}
    listing = git(tree, "ls-tree", "-r", "-z", "HEAD")
    entries = [e.split("\t", 1) for e in listing.split("\0") if e and not e.startswith("160000")]
    tracked = {p for _, p in entries}
    present = [p for _, p in entries if (copy / p).is_file()]
    res = subprocess.run(["git", "-C", str(copy), "hash-object", "--no-filters", "--stdin-paths"], input="\n".join(present) + "\n",
                         capture_output=True, text=True, check=False)
    got = dict(zip(present, res.stdout.split()))
    differs = sorted([p for meta, p in entries if (copy / p).is_file() and meta.split()[2] != got.get(p)] + [p for _, p in entries if not (copy / p).is_file()])
    extra = []
    for dirpath, dirnames, filenames in os.walk(copy):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), copy).replace(os.sep, "/")
            if rel not in tracked:
                extra.append(rel)
    extra.sort()
    unlisted = [p for p in extra if p not in allowed_extra]
    for p in differs:
        if p not in exempt or not (copy / p).is_file():
            unlisted.append(p)
            continue
        old = [ln.rstrip("\n") for ln in (git_show(tree, "HEAD", p) or [])]
        new = (copy / p).read_text(encoding="utf-8", errors="replace").split("\n")
        changes = [d for d in difflib.unified_diff(old, new, lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("+++", "---")]
        if any(d[0] == "-" or d[1:].strip() not in exempt[p] for d in changes):
            unlisted.append(p)
    sha = {p: file_sha256(copy / p) for p in differs + extra if (copy / p).is_file()}
    return {"differs": differs, "extra": extra, "sha256": sha, "unlisted": sorted(set(unlisted)), "is_head": not unlisted}


def copy_differs(tree: Path, copy: Path) -> list[str]:
    """Tracked paths of `tree` at HEAD whose content in the copy differs or is missing."""
    return list(copy_state(tree, copy)["differs"])  # type: ignore[arg-type]


def overlay_check(tree: Path, norns: Path, binary: Path, version: str, pin_rel: str = "packer/VTR_COMMIT", overlay_rel: str = "packer/vpr") -> dict[str, object]:
    """Is a dirty VTR build tree exactly "VTR base commit + the Norns packer overlay"? Four checks at record time:
    `vtr_head_is_pin` (tree HEAD equals the pin file at the nornsIII commit), `tree_matches_overlay` (every modified or
    untracked, non-ignored file of the tree has a byte-identical counterpart in the overlay as committed, and every overlay
    file is present and identical in the tree), `packer_clean` (the nornsIII tree's packer/ has no change), and
    `binary_newer_or_names_base` (binary mtime not older than any overlay file in the tree, or its --version text names the
    base commit). Result: `ok`, `failed` (check names, with `details`), `base_commit`, `overlay_commit`, `overlay_sha256`."""
    failed: dict[str, str] = {}
    commit = git(norns, "rev-parse", "HEAD")
    base = git(tree, "rev-parse", "HEAD")
    pin = "\n".join(git_show(norns, commit, pin_rel) or []).strip() if commit else ""
    if not (SHA40.fullmatch(commit) and SHA40.fullmatch(base)):
        failed["vtr_head_is_pin"] = "no git commit for the VTR tree or the nornsIII tree"
    elif base != pin:
        failed["vtr_head_is_pin"] = f"tree HEAD {base[:10]} differs from {pin_rel} {pin[:10] or '(unreadable)'}"
    files: dict[str, bytes] = {}  # path under vpr/ (as in the VTR tree) -> committed bytes
    if commit:
        for name in git(norns, "ls-tree", "-r", "--name-only", "-z", commit, "--", overlay_rel).split("\0"):
            if not name:
                continue
            res = subprocess.run(["git", "-C", str(norns), "show", f"{commit}:{name}"], capture_output=True, check=False)
            if res.returncode == 0:
                files["vpr/" + name[len(overlay_rel) + 1:]] = res.stdout
    problems = []
    if not files:
        problems.append("no overlay files at the nornsIII commit")
    for rel, data in sorted(files.items()):
        f = tree / rel
        if not f.is_file():
            problems.append(f"overlay file missing in the tree: {rel}")
        elif f.read_bytes() != data:
            problems.append(f"overlay file differs in the tree: {rel}")
    status = subprocess.run(["git", "-C", str(tree), "status", "--porcelain", "-z", "--untracked-files=all"], capture_output=True, text=True, check=False).stdout  # not git(): it strips the first entry's leading space
    for ent in status.split("\0"):
        if ent and ent[3:] not in files:
            problems.append(f"modified or untracked file without an overlay counterpart: {ent[3:]}")
    if problems:
        failed["tree_matches_overlay"] = "; ".join(problems[:MAX_LISTED_DIFFS])
    if git(norns, "status", "--porcelain", "--untracked-files=all", "--", "packer") != "":
        failed["packer_clean"] = "packer/ of the nornsIII tree has uncommitted changes"
    present = [tree / r for r in files if (tree / r).is_file()]
    if binary.is_file() and present:
        if not (binary.stat().st_mtime >= max(f.stat().st_mtime for f in present) or (base and base[:10] in version)):
            failed["binary_newer_or_names_base"] = "the binary is older than an overlay file and its --version text does not name the base commit"
    elif not binary.is_file():
        failed["binary_newer_or_names_base"] = "no binary"
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(f"{rel}\0{len(files[rel])}\0".encode() + files[rel] + b"\n")
    return {"ok": not failed, "failed": failed, "base_commit": base, "overlay_commit": commit, "overlay_sha256": h.hexdigest() if files else ""}


def tool_entry(tree: Path | None, binary: Path, env: dict[str, str] | None = None, version_args: tuple[str, ...] | None = ("--version",),
               copy: Path | None = None, copy_allowed_extra: tuple[str, ...] = (), copy_exempt: dict[str, tuple[str, ...]] | None = None, overlay_repo: Path | None = None) -> dict[str, object]:
    """Facts about one tool: HEAD of its source tree and how it was found, whether the tree is clean AT RECORD TIME
    (and the sha256 of its diff when it is not), the binary's sha256 and `--version` text, whether that text names
    the tree's HEAD, and whether the text says the binary was built from a dirty tree (`built_dirty`, from the
    `-dirty` suffix of the version; None when unknown). For a tool built from a `git archive` copy: `build_copy`
    (see copy_state). With `overlay_repo` (the norns repo whose packer/vpr overlays a VTR tree): `overlay` (see overlay_check)."""
    head = git(tree, "rev-parse", "HEAD") if tree else ""
    head = head if SHA40.fullmatch(head) else ""
    clean = None
    diff_sha = ""
    if head and tree:
        clean = git(tree, "status", "--porcelain", "--untracked-files=no") == ""
        if not clean:
            diff_sha = hashlib.sha256(git(tree, "diff", "HEAD").encode()).hexdigest()
    version = ""
    if binary.is_file() and version_args is not None:
        res = subprocess.run([str(binary), *version_args], capture_output=True, text=True, check=False, timeout=60, cwd=tempfile.gettempdir(),
                             env={**os.environ, **(env or {})})
        version = (res.stdout + res.stderr).strip()
    ov = overlay_check(tree, overlay_repo, binary, version) if (overlay_repo and tree and head) else None
    bc = copy_state(tree, copy, copy_allowed_extra, copy_exempt) if (copy and tree and head and copy.is_dir()) else None
    return {"commit": head, "commit_how": "git rev-parse HEAD of the source tree" if head else "no git source tree",
            "clean": clean, "dirty_diff_sha256": diff_sha,
            "binary_sha256": file_sha256(binary) if binary.is_file() else "",
            "binary_version": version,
            "built_dirty": (re.search(r"-dirty\b", version) is not None) if version else None,
            # a script run from its tree (version_args None) is that tree's HEAD when the tree is clean
            "version_names_commit": (clean is True) if version_args is None else (bool(head) and head[:10] in version),
            "is_script": version_args is None,
            "overlay": ov, "build_copy": bc, "build_copy_is_head": bool(bc and bc["is_head"])}


def parse_time_v(text: str) -> tuple[float | None, float | None]:
    """(elapsed wall seconds, peak RSS MiB) from `/usr/bin/time -v` output; None for a value that is absent."""
    el = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:.]+)", text)
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    secs = None
    if el:
        secs = 0.0
        for part in el.group(1).split(":"):
            secs = secs * 60 + float(part)
    return secs, (int(rss.group(1)) / 1024.0 if rss else None)


# ---------------------------------------------------------------- defaults read from tool source at a commit

def option_default(src: Path, option: str, commit: str = "", rel: str = "") -> tuple[str, str] | None:
    """(value, 'first-last') of the `.default_value("x")` after the argparse entry of `option` in a VPR source file:
    the file as committed at `commit` of the tree `src` when `commit` and `rel` are given, else the file `src`."""
    if commit and rel:
        lines = git_show(src, commit, rel) or []
    else:
        lines = src.read_text(encoding="utf-8", errors="replace").split("\n") if src.is_file() else []
    for i, ln in enumerate(lines):
        if f'"{option}")' in ln:
            for j in range(i, min(i + 20, len(lines))):
                m = re.search(r'\.default_value\("([^"]*)"\)', lines[j])
                if m:
                    return m.group(1), f"{i + 1}-{j + 1}"
            return None
    return None


def line_of(src: Path, needle: str) -> int:
    """1-based line of the first line of `src` containing `needle`; 0 when absent."""
    lines = src.read_text(encoding="utf-8", errors="replace").split("\n") if src.is_file() else []
    return next((i + 1 for i, ln in enumerate(lines) if needle in ln), 0)


# nextpnr: the settings the generic arch's flow reads (placers, timing, packing). The files are listed here, the
# settings in them are enumerated from the source at the recorded commit (enumerate_settings).
NEXTPNR_COMMON_FILES = ("common/kernel/command.cc", "common/kernel/timing.cc", "common/kernel/timing_log.cc", "common/place/place_common.cc",
                        "common/place/detail_place_core.cc", "common/place/parallel_refine.cc", "generic/pack.cc", "generic/arch.cc", "generic/main.cc")
NEXTPNR_PLACER_FILE = {"heap": "common/place/placer_heap.cc", "sa": "common/place/placer1.cc"}
NEXTPNR_HELPERS = "common/kernel/util.h"  # `bool_or_default(..., bool def = false)` and the like
COMMAND_CC = "common/kernel/command.cc"
# the flag that sets a setting (verified against command.cc by cli_settings)
SEED_SETTING = "seed"  # `--seed` is read by `ctx->rngseed` (command.cc), not stored as a setting by the flag itself
LITERAL = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?[fFuUlL]*|true|false|\"[^\"]*\"")


def _balanced(text: str, start: int) -> str:
    """Text between the parenthesis at text[start - 1] and its match."""
    depth, i = 1, start
    while i < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
    return text[start:i - 1]


def _split_args(args: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for i, ch in enumerate(args):
        if ch in "(<[{":
            depth += 1
        elif ch in ")>]}" and not (ch == ">" and args[i - 1:i] == "-"):  # `->` is not a closing bracket
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def literal_value(expr: str) -> str | None:
    """The value of a literal expression (a number, true/false, a string, or std::to_string / int of one); else None."""
    e = expr.strip()
    m = re.fullmatch(r"(?:std::to_string|int|float|double|bool)\(\s*(.*?)\s*\)", e)
    if m:
        e = m.group(1)
    if not LITERAL.fullmatch(e):
        return None
    e = e.strip('"') if e.startswith('"') else re.sub(r"[fFuUlL]+$", "", e)
    return e


def enumerate_settings(sources: dict[str, list[str]]) -> tuple[list[tuple[str, str, int, str | None]], dict[str, tuple[str, int, str]]]:
    """From source files {path: lines}: (reads, command defaults).
    reads: (setting name, path, line, literal default or None) of every `ctx->setting<T>("name"[, default])` and
    `*_or_default(ctx->settings, ctx->id("name")[, default])`. command defaults: name -> (path, line, value text)
    of the `if (settings.find(id("name")) == settings.end()) settings[id("name")] = value;` lines of command.cc,
    and the helper defaults (`bool_or_default` -> false) of util.h under the key `<fn>()`."""
    reads: list[tuple[str, str, int, str | None]] = []
    defaults: dict[str, tuple[str, int, str]] = {}
    for path, lines in sources.items():
        text = "\n".join(lines)
        line_at = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
        for m in re.finditer(r"\bsetting\s*<[^>]*>\s*\(", text):
            args = _split_args(_balanced(text, m.end()))
            name = re.fullmatch(r'"([^"]+)"', args[0]) if args else None
            if name:
                reads.append((name.group(1), path, line_at(m.start()), literal_value(args[1]) if len(args) > 1 else None))
        for m in re.finditer(r"\b(\w+)_or_default\s*\(", text):
            args = _split_args(_balanced(text, m.end()))
            name = re.search(r'id\("([^"]+)"\)', args[1]) if len(args) > 1 and "settings" in args[0] else None
            if name:
                reads.append((name.group(1), path, line_at(m.start()), literal_value(args[2]) if len(args) > 2 else f"{m.group(1)}()"))
        for m in re.finditer(r'settings\.find\(\s*ctx->id\("([^"]+)"\)\s*\)\s*==\s*ctx->settings\.end\(\)\s*\)\s*ctx->settings\[\s*ctx->id\("\1"\)\s*\]\s*=\s*([^;]*);', text):
            defaults.setdefault(m.group(1), (path, line_at(m.start(2)), m.group(2).strip()))
        if path == NEXTPNR_HELPERS:
            for m in re.finditer(r"(\w+)_or_default\s*\([^)]*?\b(?:bool|int|std::string)\s+def\s*=\s*([^,)]+)\)", text):
                defaults.setdefault(f"{m.group(1)}()", (path, line_at(m.start()), m.group(2).strip()))
    return reads, defaults


def cli_settings(command_lines: list[str]) -> dict[str, str]:
    """flag -> setting name of the command.cc lines `ctx->settings[ctx->id("name")] = ... vm["flag"] ...`."""
    out = {}
    for ln in command_lines:
        m = re.search(r'settings\[\s*ctx->id\("([^"]+)"\)\s*\]\s*=.*vm\["([\w-]+)"\]', ln)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def cmd_options(flags: list[str]) -> list[tuple[str, list[str]]]:
    """[(option name without --, [values])] of a command line's `--name v1 v2` groups."""
    out: list[tuple[str, list[str]]] = []
    for a in flags:
        if a.startswith("--"):
            out.append((a[2:], []))
        elif out:
            out[-1][1].append(a)
    return out


# ---------------------------------------------------------------- the recorder

class RunRecorder:
    """Builds one run record. `roots` maps a placeholder name to a directory: a path under it is written as
    `<name>/relative`; any other absolute path as `<abs>/basename`; a file in `roles` as `<role>`."""

    def __init__(self, source: str, design: str, arm: str, seed: int, family: str, arch: str,
                 roots: dict[str, Path], roles: dict[Path, str] | None = None):
        self.run_id = f"{source}/{design}/{arm}/s{int(seed)}"
        self.rec: dict[str, object] = {
            "record_version": RECORD_VERSION, "kind": "norns-run", "source": source, "design": design,
            "arm": arm, "seed": int(seed), "family": family, "arch": arch, "host": host_alias(),
            "kernel": platform.release(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": [], "tools": {}, "params": {}, "inputs": {}, "artifacts": {}}
        self.roots = {k: v.resolve() for k, v in roots.items()}
        self.roles = {k.resolve(): v for k, v in (roles or {}).items()}
        self.missing: list[tuple[str, str, str]] = []  # (table, role, placeholder path) of files absent at record time

    # paths
    def ph(self, text: str) -> str:
        """A path (or a value that is one) as a placeholder."""
        if "=" in text and text.split("=", 1)[1].startswith("/") and not text.startswith("/"):
            k, v = text.split("=", 1)
            return f"{k}={self.ph(v)}"
        if not text.startswith("/"):
            return text
        p = Path(text)
        if p == Path("/dev/null"):
            return text
        rp = p.resolve()
        if rp in self.roles:
            return self.roles[rp]
        for name, root in sorted(self.roots.items(), key=lambda kv: -len(str(kv[1]))):
            if rp == root or root in rp.parents:
                return f"<{name}>/{rp.relative_to(root).as_posix()}".rstrip("/")
        return f"<abs>/{p.name}"

    def argv(self, argv: list[str], roles: dict[Path, str] | None = None) -> list[str]:
        """The argv with placeholders; `roles` names files of this step only (for example a per-seed input), so that
        the command text of one setup does not change from seed to seed."""
        saved = self.roles
        self.roles = {**saved, **{k.resolve(): v for k, v in (roles or {}).items()}}
        try:
            return [self.ph(a) for a in argv]
        finally:
            self.roles = saved

    # contents
    def add_step(self, name: str, argv: list[str], rc: int, time_s: float | None, rss_mib: float | None, locked: bool,
                 script: Path | None = None, shared: bool = False, roles: dict[Path, str] | None = None) -> None:
        """One tool run. A time or RSS that `/usr/bin/time` did not report is null with conf `unknown`, never 0.
        `shared` marks a step run once for several records (it is left out of the record's time). `script`: the
        sha256 of a Python script this step ran."""
        steps = self.rec["steps"]
        assert isinstance(steps, list)
        st: dict[str, object] = {"name": name, "argv": self.argv(argv, roles), "exit_code": int(rc),
                                 "time_s": None if time_s is None else round(time_s, 3), "time_conf": "unknown" if time_s is None else "given",
                                 "peak_rss_mib": None if rss_mib is None else round(rss_mib, 1), "locked": bool(locked), "shared": bool(shared)}
        if script is not None:
            st["script_sha256"] = file_sha256(script) if script.is_file() else ""
        steps.append(st)

    def add_tool(self, name: str, entry: dict[str, object]) -> None:
        tools = self.rec["tools"]
        assert isinstance(tools, dict)
        tools[name] = entry
        c = str(entry["commit"])
        bc = entry.get("build_copy")
        built_dirty = entry.get("built_dirty")
        ov = entry.get("overlay")
        ov_ok = isinstance(ov, dict) and bool(ov["ok"])
        if ov_ok:
            ok, why = True, f"VTR {ov['base_commit']} + Norns packer overlay at nornsIII {ov['overlay_commit']} (tree and overlay checked identical at record time)"
        elif entry.get("is_script"):
            ok, why = entry["clean"] is True, "a script run from its tree: the clean tree's HEAD"
        elif bc is not None:
            ok, why = bool(entry["build_copy_is_head"]), "HEAD of the source tree equals the build's source copy but for listed, hashed exemptions"
        else:
            ok, why = bool(entry["version_names_commit"]) and built_dirty is False, "the binary's --version text names HEAD and not '-dirty' (built from a clean tree)"
        ok = ok and bool(c)
        if ok:
            self.param(f"tool.{name}_commit", c, "given", f"{name}: {why}")
        else:
            reason = ("there is no source tree" if not c else "the binary was built from a dirty tree (its --version says -dirty)" if built_dirty
                      else "the source copy differs from HEAD in an unlisted way" if bc is not None else "the --version text does not name HEAD or the clean build is not shown")
            self.param(f"tool.{name}_commit", c, "unknown", f"inferred at record time: HEAD of the source tree; not given because {reason}")
        if isinstance(ov, dict):
            if ov_ok:
                self.param(f"tool.{name}_base_commit", str(ov["base_commit"]), "given", "VTR tree HEAD equals packer/VTR_COMMIT at the nornsIII commit (checked at record time)")
                self.param(f"tool.{name}_overlay_commit", str(ov["overlay_commit"]), "given", "HEAD of the nornsIII tree; packer/ clean and byte-identical to the VTR tree's overlay files (checked at record time)")
                self.param(f"tool.{name}_overlay_sha256", str(ov["overlay_sha256"]), "given", "sha256 over the sorted overlay file list and contents, as committed at the nornsIII commit")
            else:
                for chk, why_failed in dict(ov["failed"]).items():  # type: ignore[call-overload]
                    self.param(f"tool.{name}_overlay_check_failed[{chk}]", why_failed, "unknown", "at record time: this check of 'VTR base + Norns packer overlay' failed")
        if built_dirty is not None:
            self.param(f"tool.{name}_built_dirty", str(bool(built_dirty)).lower(), "given", f"{name} --version text ('-dirty' suffix)")
        self.param(f"tool.{name}_source_clean", "unknown" if entry["clean"] is None else str(entry["clean"]).lower(),
                   "given" if entry["clean"] is not None else "unknown", "at record time: git status --porcelain of the source tree (tracked files)")
        if entry["dirty_diff_sha256"]:
            self.param(f"tool.{name}_dirty_diff_sha256", str(entry["dirty_diff_sha256"]), "given", "at record time: sha256 of git diff HEAD of the source tree")
        self.param(f"tool.{name}_binary_sha256", str(entry["binary_sha256"]), "given" if entry["binary_sha256"] else "unknown", "sha256 of the binary file")
        if isinstance(bc, dict):
            for kind in ("differs", "extra"):
                label = "modified" if kind == "differs" else "extra"
                for p in list(bc[kind])[:MAX_LISTED_DIFFS]:
                    sha = bc["sha256"].get(p, "")
                    listed = p not in bc["unlisted"]
                    self.param(f"tool.{name}_build_copy_{label}[{p}]", sha, "given" if sha else "unknown",
                               f"sha256 of the file in the build copy ({label} against HEAD; {'a listed exemption' if listed else 'NOT a listed exemption'})")
                if len(bc[kind]) > MAX_LISTED_DIFFS:
                    self.param(f"tool.{name}_build_copy_{label}_count", str(len(bc[kind])), "given", f"number of {label} files in the build copy (only {MAX_LISTED_DIFFS} listed)")

    def param(self, key: str, value: str, conf: str, source: str) -> None:
        params = self.rec["params"]
        assert isinstance(params, dict)
        params[key] = {"value": self.ph(value), "conf": conf, "source": source}

    def add_input(self, role: str, path: Path) -> None:
        self._file("inputs", role, path)

    def add_artifact(self, role: str, path: Path) -> None:
        self._file("artifacts", role, path)

    def _file(self, table: str, role: str, path: Path) -> None:
        if path.is_file():
            tab = self.rec[table]
            assert isinstance(tab, dict)
            tab[role] = {"path": self.ph(str(path.resolve())), "sha256": file_sha256(path)}
        else:
            self.missing.append((table, role, self.ph(str(path))))

    # parameters of the tools
    def add_vpr_params(self, argv: list[str], log: Path, tree: Path | None, commit: str) -> None:
        """VPR: every option VPR echoed in its log (its own statement of the effective value, cited vpr.out:line),
        the options on the command line, the seed, and the seed's default read from `read_options.cpp` as committed
        at `commit` of `tree`. A log without the echo header is an `unknown` row (the options are not recorded)."""
        lines = log.read_text(encoding="utf-8", errors="replace").split("\n") if log.is_file() else []
        if VPR_OPTIONS_HEAD in lines:
            for n in range(lines.index(VPR_OPTIONS_HEAD) + 1, len(lines)):
                m = OPT_LINE.match(lines[n])
                if m:
                    self.param(f"vpr.{m.group(1)}", m.group(2).strip() or "(empty)", "given", f"vpr.out:{n + 1} (VPR's echo of the effective option)")
                elif lines[n].strip() and not lines[n].startswith(" ") and not lines[n].startswith("Using up to"):
                    break
        else:
            self.param("vpr.options_echo", "", "unknown", f"vpr.out lacks the line '{VPR_OPTIONS_HEAD}': the effective options are not recorded")
        for key, vals in cmd_options(argv[3:]):  # argv is vpr, arch, blif, then the options
            if key == "seed":
                self.param("run.seed", vals[0], "given", "command line --seed")
            else:
                self.param(f"vpr.cmd.{key}", " ".join(self.ph(v) for v in vals) or "(flag)", "given", "command line")
        self.param("vpr.cmd.arch_file", self.ph(argv[1]), "given", "command line")
        rel = "vpr/src/base/read_options.cpp"
        found = option_default(tree, "--seed", commit, rel) if tree and commit else None
        if found:
            self.param("run.seed_default", found[0], "default", f"vtr-tree {commit[:8]} {rel}:{found[1]}")
        else:
            self.param("run.seed_default", "", "default-unrecorded", "VPR source tree or commit not available")

    def add_nextpnr_params(self, argv: list[str], tree: Path | None, commit: str, label: str, placer: str,
                           extra_sources: dict[str, Path] | None = None) -> None:
        """nextpnr: the command-line options as given, and every setting the generic flow reads (enumerate_settings, from
        the sources at `commit`: command.cc, timing, the chosen placer, packing, plus `extra_sources` = overlay files of
        the build copy). A setting not given on the command line gets its default cited `path:line` at the commit; one
        with no default found in the source is `default-unrecorded`, which makes the configuration partial."""
        cmd = cmd_options(argv[1:])
        for key, vals in cmd:
            val = " ".join(vals) or "(flag)"
            if key == "seed":
                self.param("run.seed", val, "given", "command line --seed")
            elif key == "vopt":
                k, _, v = val.partition("=")
                self.param(f"nextpnr.vopt.{k}", v, "given", "command line --vopt")
            else:
                self.param(f"nextpnr.cmd.{key}", val, "given", "command line")
        paths = list(NEXTPNR_COMMON_FILES) + [NEXTPNR_PLACER_FILE[placer], NEXTPNR_HELPERS]
        sources: dict[str, list[str]] = {}
        for p in paths:
            lines = git_show(tree, commit, p)
            if lines is None:
                self.param(f"nextpnr.settings_source[{p}]", "", "unknown", f"{p} not readable at the recorded commit: its settings are not enumerated")
            else:
                sources[p] = lines
        for rel, f in (extra_sources or {}).items():
            if f.is_file():
                sources[rel] = f.read_text(encoding="utf-8", errors="replace").split("\n")
        reads, defaults = enumerate_settings(sources)
        flag_setting = cli_settings(sources.get(COMMAND_CC, []))
        flags = {k for k, _ in cmd}
        given_settings = {flag_setting[k] for k in flags if k in flag_setting} | ({SEED_SETTING} if "seed" in flags else set()) | {k for k in flags if k in ("placer",)}
        if "no-route" in flags:  # the router does not run, so no router setting is read
            self.param("nextpnr.router", "none", "given", "command line --no-route (the router does not run; its settings are not read)")
            given_settings |= {n for n, *_ in reads if n == "router" or n.startswith("router")}
        seen: dict[str, tuple[str, int, str | None]] = {}
        conflict: set[str] = set()
        for name, path, line, lit in reads:
            if name in seen and lit is not None and seen[name][2] is not None and seen[name][2] != lit:
                conflict.add(name)
            if name not in seen or (seen[name][2] is None and lit is not None):
                seen[name] = (path, line, lit)
        cite = lambda path, line: f"{label} {commit[:8]} {path}:{line}"  # noqa: E731
        for name in sorted(seen):
            if name in given_settings:
                continue  # given on the command line (the parameter above)
            path, line, lit = seen[name]
            if name in conflict:
                self.param(f"nextpnr.{name}", "", "default-unrecorded", f"{path}:{line}: reads of this setting give different defaults")
                continue
            if lit is not None and lit.endswith("()") and lit in defaults:  # helper default, for example bool_or_default() is false
                hp, hl, hv = defaults[lit]
                lit, path, line = literal_value(hv), hp, hl
            elif lit is None and name in defaults:
                path, line, expr = defaults[name]
                lit = literal_value(expr)
            if lit is not None and not lit.endswith("()"):
                self.param(f"nextpnr.{name}", lit, "default", cite(path, line))
            else:
                self.param(f"nextpnr.{name}", "", "default-unrecorded", f"{path}:{line}: read here; no literal default found in the source at the recorded commit")

    # output
    def write(self, path: Path, required_inputs: tuple[str, ...] = (), required_artifacts: tuple[str, ...] = ()) -> None:
        """Write the record. A required role that was not added is recorded as an `unknown` parameter (never dropped), as is
        every file that was absent at record time. RecordRefused (nothing written) when a privacy rule hits."""
        steps: list[dict[str, object]] = self.rec["steps"]  # type: ignore[assignment]
        for table, req in (("inputs", required_inputs), ("artifacts", required_artifacts)):
            tab = self.rec[table]
            assert isinstance(tab, dict)
            for role in req:
                if role not in tab and not any(t == table and r == role for t, r, _ in self.missing):
                    self.missing.append((table, role, ""))
        for table, role, where in self.missing:
            self.param(f"{table}.{role}_sha256", "", "unknown", f"file absent at record time ({where or 'not offered by the runner'})")
        own = [s for s in steps if not s["shared"]]
        times = [s["time_s"] for s in own]
        rss = [s["peak_rss_mib"] for s in own if "script_sha256" not in s]  # a helper script's RSS is not measured
        self.rec["time_s"] = None if (not own or None in times) else round(sum(times), 3)  # type: ignore[arg-type]
        self.rec["time_conf"] = "unknown" if self.rec["time_s"] is None else "given"
        self.rec["peak_rss_mib"] = None if (not rss or None in rss) else max(rss)  # type: ignore[type-var]
        nsteps = [s for s in steps if s["name"] == "nextpnr"]
        if nsteps:  # the placer step only (the last attempt, the one whose result was used)
            self.rec["placer_time_s"] = nsteps[-1]["time_s"]
        self.rec["ok"] = bool(steps) and steps[-1]["exit_code"] == 0  # the last step decides (earlier attempts may have failed)
        text = json.dumps(self.rec, indent=1, sort_keys=True) + "\n"
        hits = privacy_hits(self.rec)
        if hits:
            raise RecordRefused(hits)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _strings(obj: object, where: str = "record") -> list[tuple[str, str]]:
    if isinstance(obj, str):
        return [(where, obj)]
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in _strings(v, f"{where}.{k}")]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in _strings(v, f"{where}[{i}]")]
    return []


def private_strings() -> list[tuple[str, str]]:
    """(rule, string) no record may hold: the home directory, user name and host name of this machine, and every real
    host name of the host map. The rule names are what a log may show; the strings are never shown."""
    out = [("home-directory", str(Path.home())), ("user-name", getpass.getuser()), ("host-name", platform.node())]
    try:
        out += [("host-map-name", n) for n in host_table()]
    except (HostMapError, OSError, ValueError):
        pass
    return [(r, s) for r, s in out if len(s) >= 3]


def privacy_hits(rec: object) -> list[str]:
    """Rule and key path of every string of `rec` that holds a private string, a home path or an absolute path (spec section 6)."""
    privates = [(r, s.lower()) for r, s in private_strings()]
    hits = []
    for where, text in _strings(rec):
        low = text.lower()
        for rule, s in privates:
            if s in low:
                hits.append(f"{rule} at {where}")
        if "/home/" in text or "/Users/" in text:
            hits.append(f"home-path at {where}")
        elif ABS_PATH.search(text):
            hits.append(f"absolute-path at {where}")
    return hits
