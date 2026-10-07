"""What `ohx doctor` checks beyond Python and git (T103): what stands between a new user
and a first verification, each with the command that fixes it.

The simulated user trial (2026-10-05) lost most of its setup time here: the sandbox not
installed, the checks running with an interpreter that has no pytest, and on Linux the
programs the sandbox needs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from openharnx.app import project_python
from openharnx.doctor import CheckResult, run_checks
from openharnx.sandbox import find_srt
from openharnx.workspace import NotARepository, repo_root

SRT_VERSION = "0.0.77"
SRT_INSTALL = f"npm install -g @anthropic-ai/sandbox-runtime@{SRT_VERSION}"
MIN_NODE = 20
# On Linux the sandbox runs through these (docs/ci/README.md).
LINUX_HELPERS = (("bwrap", "bubblewrap"), ("socat", "socat"), ("rg", "ripgrep"))


def _version(program: str, *args: str) -> str | None:
    try:
        out = subprocess.run(
            [program, *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else None


def check_srt() -> CheckResult:
    srt = find_srt()
    if srt is None:
        return CheckResult(
            "srt",
            False,
            False,
            f"the sandbox is not installed; checks would run without isolation."
            f" Install it: {SRT_INSTALL}",
        )
    version = _version(str(srt), "--version") or "version unknown"
    return CheckResult("srt", True, False, f"{version} ({srt})")


def check_node() -> CheckResult:
    node = shutil.which("node")
    if node is None:
        return CheckResult(
            "node", False, False, f"not found; the sandbox needs Node {MIN_NODE} or later"
        )
    version = _version(node, "--version") or ""
    m = re.match(r"v?(\d+)", version)
    if m is None or int(m[1]) < MIN_NODE:
        return CheckResult(
            "node", False, False, f"{version or 'unknown version'}; the sandbox needs {MIN_NODE}+"
        )
    return CheckResult("node", True, False, f"{version} ({node})")


def check_linux_helpers() -> list[CheckResult]:
    if not sys.platform.startswith("linux"):
        return []
    results = []
    for program, package in LINUX_HELPERS:
        found = shutil.which(program)
        results.append(
            CheckResult(
                package,
                found is not None,
                False,
                found or f"not found; the sandbox needs it on Linux (apt install {package})",
            )
        )
    return results


def _interpreter(python: str) -> CheckResult:
    name = "checks run with"
    probe = _version(python, "-c", "import pytest; print(pytest.__version__)")
    if probe is None or not re.fullmatch(r"\d+(\.\d+)*\S*", probe):
        return CheckResult(
            name,
            False,
            False,
            f"{python}, which has no pytest. Install it there ({python} -m pip install"
            ' pytest) or point the checks at another interpreter: python = "..." in ohx.toml',
        )
    return CheckResult(name, True, False, f"{python} (pytest {probe})")


def check_project(cwd: Path) -> list[CheckResult]:
    try:
        root = repo_root(cwd)
    except NotARepository:
        return [
            CheckResult(
                "project", True, False, "not inside a git repository; project checks skipped"
            )
        ]
    results: list[CheckResult] = []
    defaults: dict[str, object] = {}
    toml = root / "ohx.toml"
    if toml.is_file():
        try:
            defaults = tomllib.loads(toml.read_text(encoding="utf-8"))
            results.append(CheckResult("ohx.toml", True, True, str(toml)))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            results.append(CheckResult("ohx.toml", False, True, f"does not read: {exc}"))
            return results
    if defaults.get("environment") == "uv":
        results.append(
            CheckResult(
                "checks run with",
                True,
                False,
                'a protected environment built from uv.lock (environment = "uv")',
            )
        )
        return results
    configured = defaults.get("python")
    if isinstance(configured, str) and configured:
        python = configured if Path(configured).is_absolute() else str(root / configured)
    else:
        python = project_python(root) or sys.executable
    results.append(_interpreter(python))
    return results


def diagnose(cwd: Path) -> list[CheckResult]:
    return [
        *run_checks(),
        check_srt(),
        check_node(),
        *check_linux_helpers(),
        *check_project(cwd),
    ]
