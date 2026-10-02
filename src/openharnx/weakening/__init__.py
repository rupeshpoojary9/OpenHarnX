"""The built-in weakening check (T77 item 9; owner proposals 1 and 2).

An agent can make checks pass by lowering the bar instead of fixing the code:
loosening lint, type or pytest configuration, adding a `conftest.py` that
rewrites results, or adding suppressions, skip markers or removing tests.
At contract acceptance a baseline is recorded; at verification the candidate
is compared with it. Any finding blocks until a contract revision is accepted.

Adding tests needs no approval: a new test file is checked only for
suppressions, and more tests or assertions in an existing file are fine.
Python only; counts are per file, so moving a suppression within one file
is not seen.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE_VERSION = 1

# Files that configure checkers, wherever they are (ruff and pytest read nested ones).
CONFIG_NAMES = frozenset(
    {
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        ".pytest.ini",
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".mypy.ini",
        ".flake8",
        ".coveragerc",
        ".importlinter",
        "pyrightconfig.json",
        # Code that runs inside the checker or at interpreter start-up.
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
    }
)

SUPPRESSIONS = {
    "noqa": re.compile(r"#\s*noqa\b", re.IGNORECASE),
    "file-level noqa": re.compile(r"#\s*(?:ruff|flake8)\s*:\s*noqa\b", re.IGNORECASE),
    "type: ignore": re.compile(r"#\s*type\s*:\s*ignore\b"),
    "pyright: ignore": re.compile(r"#\s*pyright\s*:\s*ignore\b"),
    "inline mypy setting": re.compile(r"#\s*mypy\s*:"),
    "pragma: no cover": re.compile(r"#\s*pragma\s*:\s*no\s*cover\b"),
    "skip or xfail": re.compile(
        r"\b(?:pytest\.(?:mark\.)?(?:skip|skipif|xfail|importorskip)"
        r"|unittest\.(?:skip\w*|expectedFailure))\b"
    ),
    "pytest_plugins": re.compile(r"\bpytest_plugins\b"),
}
_TESTS = re.compile(r"^\s*(?:async\s+)?def\s+test\w*\s*\(", re.MULTILINE)
_CHECKS = re.compile(
    r"^\s*assert\b|\bself\.assert\w*\s*\(|\bpytest\.(?:raises|warns)\s*\(", re.MULTILINE
)


def is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _config_digest(path: str, data: bytes) -> str | None:
    """Digest of the part of a file that configures checkers; None if it has none."""
    if PurePosixPath(path).name == "pyproject.toml":
        try:
            tool = tomllib.loads(data.decode("utf-8")).get("tool")
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            return _digest(data)  # unreadable: any change counts
        if tool is None:
            return None
        return _digest(json.dumps(tool, sort_keys=True).encode())
    if PurePosixPath(path).name in CONFIG_NAMES:
        return _digest(data)
    return None


def snapshot(root: Path, paths: list[str]) -> dict[str, Any]:
    """Configuration digests, suppression counts and test counts for the given files."""
    config: dict[str, str] = {}
    suppressions: dict[str, dict[str, int]] = {}
    tests: dict[str, dict[str, int]] = {}
    for rel in sorted(paths):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        cdig = _config_digest(rel, data)
        if cdig is not None:
            config[rel] = cdig
        if not rel.endswith(".py"):
            continue
        text = data.decode("utf-8", errors="replace")
        counts = {k: len(p.findall(text)) for k, p in SUPPRESSIONS.items()}
        counts = {k: n for k, n in counts.items() if n}
        if counts:
            suppressions[rel] = counts
        if is_test_file(rel):
            tests[rel] = {"tests": len(_TESTS.findall(text)), "checks": len(_CHECKS.findall(text))}
    return {
        "version": BASELINE_VERSION,
        "config": config,
        "suppressions": suppressions,
        "tests": tests,
    }


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Findings that lower the bar since the baseline; empty means none found."""
    findings: list[str] = []
    before_cfg, now_cfg = baseline["config"], current["config"]
    for path in sorted(set(before_cfg) | set(now_cfg)):
        if path not in now_cfg:
            findings.append(f"{path}: check configuration removed since acceptance")
        elif path not in before_cfg:
            findings.append(f"{path}: check configuration added since acceptance")
        elif before_cfg[path] != now_cfg[path]:
            findings.append(f"{path}: check configuration changed since acceptance")
    for path, counts in sorted(current["suppressions"].items()):
        before = baseline["suppressions"].get(path, {})
        for kind, n in sorted(counts.items()):
            if n > before.get(kind, 0):
                findings.append(f"{path}: {n - before.get(kind, 0)} new {kind}")
    for path, before in sorted(baseline["tests"].items()):
        now = current["tests"].get(path)
        if now is None:
            findings.append(f"{path}: test file removed")
            continue
        for key, label in (("tests", "tests"), ("checks", "assertions")):
            if now[key] < before[key]:
                findings.append(f"{path}: fewer {label} ({before[key]} to {now[key]})")
    return findings
