"""Environment diagnostics for the local workflow.

Only checks that OpenHarnX actually depends on belong here. Git is required
because baseline capture and candidate identity read repository state.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass

MIN_PYTHON = (3, 12)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str


def check_python() -> CheckResult:
    found = sys.version_info[:2]
    want = ".".join(map(str, MIN_PYTHON))
    return CheckResult(
        "python",
        found >= MIN_PYTHON,
        True,
        f"{platform.python_version()} (requires >= {want})",
    )


def check_git() -> CheckResult:
    path = shutil.which("git")
    if path is None:
        return CheckResult("git", False, True, "not found on PATH")
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10, check=True
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return CheckResult("git", False, True, f"found at {path} but failed to run: {exc}")
    return CheckResult("git", True, True, f"{out.stdout.strip()} ({path})")


def check_platform() -> CheckResult:
    # Informational: the supported-environment matrix is not declared yet.
    detail = f"{platform.system()} {platform.release()} {platform.machine()}"
    return CheckResult("platform", True, False, detail)


def run_checks() -> list[CheckResult]:
    return [check_python(), check_git(), check_platform()]
