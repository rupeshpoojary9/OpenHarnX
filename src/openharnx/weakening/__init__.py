"""The built-in weakening check (T77 item 9; owner proposals 1 and 2).

An agent can make checks pass by lowering the bar instead of fixing the code:
loosening lint, type or pytest configuration, adding a `conftest.py` that
rewrites results, or adding suppressions, skip markers or removing tests.
At contract acceptance a baseline is recorded; at verification the candidate
is compared with it. Any finding blocks until a contract revision is accepted.

Adding tests needs no approval: a new test file is checked only for
suppressions, and more tests or assertions in an existing file are fine.
Python, TypeScript, JavaScript and Go (T82); counts are per file, so moving a
suppression within one file is not seen. Baselines made before TypeScript
support (version 1) are compared on Python only, and before Go support
(version 2) without Go, so their contracts judge as they did.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE_VERSION = 3

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

# TypeScript and JavaScript (T82). Checker configuration found by name pattern, since each
# tool accepts several file names and extensions.
JS_SOURCE = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_JS_CONFIG = re.compile(
    r"^(?:tsconfig(?:\.[\w-]+)*\.json|jsconfig\.json"
    r"|(?:vitest|vite|jest|babel|playwright)\.(?:config|workspace|setup)\.[cm]?[jt]s"
    r"|vitest\.workspace\.json|jest\.setup\.[cm]?[jt]s|setupTests\.[cm]?[jt]sx?"
    r"|\.eslintrc(?:\.(?:js|cjs|json|ya?ml))?|eslint\.config\.[cm]?[jt]s"
    r"|biome\.jsonc?|\.babelrc(?:\.json)?|\.mocharc(?:\.\w+)?|\.c8rc(?:\.json)?|\.nycrc(?:\.\w+)?)$"
)
# package.json keys that configure checkers; scripts only when they run checks.
_PACKAGE_KEYS = ("jest", "eslintConfig", "mocha", "c8", "nyc", "ava", "vitest")
_CHECK_SCRIPT = re.compile(r"^(?:test|lint|type|check|format|ci|verify)", re.IGNORECASE)

# Go (T82). A build constraint is counted in test files only: there it can switch a test
# file off, while in other files it is the ordinary way to write platform code.
GO_CONFIG = re.compile(r"^(?:\.golangci\.(?:ya?ml|toml|json)|staticcheck\.conf)$")
GO_SUPPRESSIONS = {
    "nolint": re.compile(r"//\s*nolint\b"),
    "lint:ignore": re.compile(r"//\s*lint:(?:file-)?ignore\b"),
    "#nosec": re.compile(r"#nosec\b"),
    "skipped test": re.compile(r"\b\w+\.(?:Skip|SkipNow|Skipf)\s*\("),
}
GO_TEST_ONLY = {"build constraint": re.compile(r"^//\s*(?:go:build|\+build)\b", re.MULTILINE)}
_GO_TESTS = re.compile(r"^func\s+(?:Test|Fuzz|Example)\w*\s*\(", re.MULTILINE)
_GO_CHECKS = re.compile(
    r"\b[tbf]\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\b(?:assert|require)\.\w+\s*\("
)

JS_SUPPRESSIONS = {
    "@ts-ignore": re.compile(r"@ts-ignore\b"),
    "@ts-expect-error": re.compile(r"@ts-expect-error\b"),
    "@ts-nocheck": re.compile(r"@ts-nocheck\b"),
    "eslint-disable": re.compile(r"\beslint-disable(?:-next-line|-line)?\b"),
    "biome-ignore": re.compile(r"\bbiome-ignore\b"),
    "coverage ignore": re.compile(r"\b(?:istanbul|c8|v8)\s+ignore\b"),
    "skipped or focused test": re.compile(
        r"(?<![\w$])(?:it|test|describe|suite|context|bench)\s*\.\s*"
        r"(?:skip|only|fails|skipIf|runIf|todo)\b"
        r"|(?<![\w$.])(?:xit|xtest|xdescribe|fit|fdescribe)\s*\("
        r"|\b(?:skip|only|todo)\s*:\s*(?:true|['\"`])"
        r"|(?<![\w$])t\s*\.\s*(?:skip|todo)\s*\("
    ),
}
_JS_TESTS = re.compile(r"(?<![\w$.])(?:it|test)\s*(?:\.\s*(?:concurrent|each\s*\([^)]*\)))?\s*\(")
_JS_CHECKS = re.compile(r"(?<![\w$.])(?:expect|assert)\s*(?:\.\s*\w+\s*)?\(")
_JS_TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$")

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
    p = PurePosixPath(path)
    name = p.name
    if name.endswith(".py"):
        return name.startswith("test_") or name.endswith("_test.py")
    if name.endswith(".go"):
        return name.endswith("_test.go")
    if name.endswith(JS_SOURCE):
        return bool(_JS_TEST_FILE.search(name)) or "__tests__" in p.parts[:-1]
    return False


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
    if PurePosixPath(path).name == "package.json":
        try:
            package = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _digest(data)
        if not isinstance(package, dict):
            return _digest(data)
        scripts = package.get("scripts")
        checks = {
            k: v
            for k, v in (scripts if isinstance(scripts, dict) else {}).items()
            if _CHECK_SCRIPT.match(k)
        }
        part = {k: package[k] for k in _PACKAGE_KEYS if k in package}
        if checks:
            part["scripts"] = checks
        return _digest(json.dumps(part, sort_keys=True).encode()) if part else None
    name = PurePosixPath(path).name
    if name in CONFIG_NAMES or _JS_CONFIG.match(name) or GO_CONFIG.match(name):
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
        if rel.endswith(".py"):
            patterns, test_re, check_re = SUPPRESSIONS, _TESTS, _CHECKS
        elif rel.endswith(JS_SOURCE):
            patterns, test_re, check_re = JS_SUPPRESSIONS, _JS_TESTS, _JS_CHECKS
        elif rel.endswith(".go"):
            patterns, test_re, check_re = GO_SUPPRESSIONS, _GO_TESTS, _GO_CHECKS
            if is_test_file(rel):
                patterns = {**GO_SUPPRESSIONS, **GO_TEST_ONLY}
        else:
            continue
        text = data.decode("utf-8", errors="replace")
        counts = {k: len(p.findall(text)) for k, p in patterns.items()}
        counts = {k: n for k, n in counts.items() if n}
        if counts:
            suppressions[rel] = counts
        if is_test_file(rel):
            tests[rel] = {
                "tests": len(test_re.findall(text)),
                "checks": len(check_re.findall(text)),
            }
    return {
        "version": BASELINE_VERSION,
        "config": config,
        "suppressions": suppressions,
        "tests": tests,
    }


def _as_version(snap: dict[str, Any], version: int) -> dict[str, Any]:
    """What a baseline of an earlier version would have recorded: version 1 Python only,
    version 2 without Go."""

    def known(path: str, config: bool = False) -> bool:
        name = PurePosixPath(path).name
        if version < 2:
            return (
                (name == "pyproject.toml" or name in CONFIG_NAMES)
                if config
                else (path.endswith(".py"))
            )
        return not (path.endswith(".go") or (config and GO_CONFIG.match(name)))

    return {
        **snap,
        "config": {k: v for k, v in snap["config"].items() if known(k, config=True)},
        "suppressions": {k: v for k, v in snap["suppressions"].items() if known(k)},
        "tests": {k: v for k, v in snap["tests"].items() if known(k)},
    }


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Findings that lower the bar since the baseline; empty means none found."""
    if baseline.get("version", 1) < BASELINE_VERSION:
        current = _as_version(current, baseline.get("version", 1))
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
