"""Use cases for source tracing: init, check, approve."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openharnx.app import UsageError, _open, _toml_value, now_utc
from openharnx.kernel.trace import (
    DROPS,
    SourceUnit,
    TraceEntry,
    TraceReport,
    evaluate_trace,
    split_units,
)
from openharnx.workspace import NotARepository, repo_root

HEADER = """\
# Source trace: every unit of the sources below must be accounted for.
# status: unmarked | requirement (list the tests that prove it) | question
#         | context (not a requirement) | excluded (needs a note)
# Dropped units (context, excluded) count only after `ohx trace approve`.
"""


def _root(cwd: Path) -> Path:
    try:
        return repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc


def _prefix(source: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]", "", Path(source).stem).upper()
    return stem[:10] or "SRC"


def _read_units(root: Path, sources: Sequence[str]) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    for rel in sources:
        path = root / rel
        if not path.is_file():
            raise UsageError(f"source not found: {rel}")
        units += split_units(rel, path.read_text())
    return units


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise UsageError(f"no trace file at {path}; run `ohx trace init <sources>`")
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"{path.name} is not valid TOML: {exc}") from exc


def _entries(data: dict[str, Any]) -> list[TraceEntry]:
    out = []
    for u in data.get("unit", []):
        try:
            out.append(
                TraceEntry(
                    u["id"],
                    u["source"],
                    u["text"],
                    u["digest"],
                    u.get("status", "unmarked"),
                    tuple(u.get("tests", [])),
                    u.get("note", ""),
                )
            )
        except KeyError as exc:
            raise UsageError(f"trace unit missing field {exc}") from exc
    return out


def trace_init(cwd: Path, sources: Sequence[str], out: str = "trace.toml") -> tuple[Path, int, int]:
    """Write or merge the trace file. Returns (path, new units, removed units)."""
    root = _root(cwd)
    rels = [Path((cwd / s).resolve()).relative_to(root).as_posix() for s in sources]
    units = _read_units(root, rels)
    path = root / out
    old = _entries(_load(path)) if path.exists() else []

    pool: dict[tuple[str, str], list[TraceEntry]] = {}
    for e in old:
        pool.setdefault((e.source, e.digest), []).append(e)
    numbers: dict[str, int] = {}
    for e in old:
        prefix, _, num = e.id.rpartition("-")
        if num.isdigit():
            numbers[prefix] = max(numbers.get(prefix, 0), int(num))

    blocks: list[dict[str, Any]] = []
    added = 0
    for u in units:
        kept = pool.get((u.source, u.digest))
        if kept:
            e = kept.pop(0)
            entry = {"id": e.id, "status": e.status, "tests": list(e.tests), "note": e.note}
        else:
            added += 1
            prefix = _prefix(u.source)
            numbers[prefix] = numbers.get(prefix, 0) + 1
            entry = {
                "id": f"{prefix}-{numbers[prefix]:03d}",
                "status": "unmarked",
                "tests": [],
                "note": "",
            }
        blocks.append(
            {
                "id": entry["id"],
                "source": u.source,
                "section": u.section,
                "text": u.text,
                "digest": u.digest,
                "status": entry["status"],
                "tests": entry["tests"],
                "note": entry["note"],
            }
        )
    removed = sum(len(v) for v in pool.values())

    lines = [HEADER, f"sources = {_toml_value(rels)}"]
    for b in blocks:
        lines += ["", "[[unit]]", *(f"{k} = {_toml_value(v)}" for k, v in b.items())]
    path.write_text("\n".join(lines) + "\n")
    return path, added, removed


def _python(root: Path) -> str:
    cfg = root / "ohx.toml"
    if cfg.exists():
        python = tomllib.loads(cfg.read_text()).get("python")
        if isinstance(python, str) and python:
            return str(root / python) if not Path(python).is_absolute() else python
    return sys.executable


def _node_matches(nodeid: str, classname: str, name: str) -> bool:
    file, *rest = nodeid.split("::")
    if not rest:
        return False
    module = file.removesuffix(".py").replace("/", ".")
    *classes, func = rest
    expected = ".".join([module, *classes])
    return classname == expected and (name == func or name.startswith(func + "["))


def _run_tests(root: Path, nodeids: set[str]) -> dict[str, bool]:
    """Run the files that hold the linked tests; map each node ID to pass."""
    files = sorted({n.split("::")[0] for n in nodeids if (root / n.split("::")[0]).is_file()})
    if not files:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        subprocess.run(
            [
                _python(root),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={xml_path}",
                *files,
            ],
            cwd=root,
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": tmp},
        )
        if not xml_path.exists():
            return {}
        cases = ET.parse(xml_path).getroot().iter("testcase")
        outcomes = [
            (
                c.get("classname", ""),
                c.get("name", ""),
                not any(child.tag in ("failure", "error", "skipped") for child in c),
            )
            for c in cases
        ]
    results: dict[str, bool] = {}
    for nodeid in nodeids:
        matched = [ok for cls, name, ok in outcomes if _node_matches(nodeid, cls, name)]
        if matched:
            results[nodeid] = all(matched)
    return results


def _approved(cwd: Path, trace_rel: str) -> str | None:
    try:
        _, _, store = _open(cwd)
    except UsageError:
        return None
    try:
        for rec in reversed(store.all("trace_approval")):
            if rec.body["trace"] == trace_rel:
                return str(rec.body["drops_digest"])
        return None
    finally:
        store.close()


def trace_check(cwd: Path, trace: str = "trace.toml", run: bool = False) -> TraceReport:
    root = _root(cwd)
    data = _load(root / trace)
    entries = _entries(data)
    units = _read_units(root, data.get("sources", []))
    results = None
    if run:
        nodeids = {t for e in entries if e.status == "requirement" for t in e.tests}
        results = _run_tests(root, nodeids)
    return evaluate_trace(units, entries, _approved(cwd, trace), results)


def trace_approve(cwd: Path, trace: str = "trace.toml") -> tuple[list[TraceEntry], str]:
    """Record the owner's approval of exactly the current set of dropped units."""
    root = _root(cwd)
    entries = _entries(_load(root / trace))
    drops = [e for e in entries if e.status in DROPS]
    unreasoned = [e.id for e in drops if e.status == "excluded" and not e.note.strip()]
    if unreasoned:
        raise UsageError("excluded units need a note giving the reason: " + ", ".join(unreasoned))
    report = evaluate_trace([], entries, None, None)
    _, _, store = _open(cwd)
    try:
        who = (
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name"], capture_output=True, text=True
            ).stdout.strip()
            or "unknown"
        )
        store.append(
            "trace_approval",
            {
                "trace": trace,
                "drops_digest": report.drops_digest,
                "drops": [
                    {"id": e.id, "status": e.status, "note": e.note, "text": e.text} for e in drops
                ],
                "approved_by": who,
            },
            now=now_utc(),
        )
    finally:
        store.close()
    return drops, report.drops_digest
