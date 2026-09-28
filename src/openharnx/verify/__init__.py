"""Run one obligation's checker against the candidate and classify the result."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openharnx.sandbox import verifier_profile, wrap, write_profile


@dataclass(frozen=True)
class CheckerRun:
    outcome: str
    exit_code: int | None
    output: bytes
    duration_ms: int
    argv: list[str]


def _expand(value: str, subs: dict[str, str]) -> str:
    for key, sub in subs.items():
        value = value.replace("{" + key + "}", sub)
    return value


def classify(exit_code: int) -> str:
    # pytest conventions: 0 passed, 1 tests failed, 5 nothing collected.
    if exit_code == 0:
        return "pass"
    if exit_code == 1:
        return "fail"
    if exit_code == 5:
        return "invalid"
    return "crash"


def run_obligation(
    obligation: dict[str, Any],
    *,
    candidate: Path,
    protected: Path | None,
    run_dir: Path,
    srt: Path | None,
    deny_read: list[str],
    python: str | None = None,
) -> CheckerRun:
    tmp = run_dir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    python = python or sys.executable
    subs = {
        "candidate": str(candidate),
        "protected": str(protected) if protected else "",
        "python": python,
        "bindir": str(Path(python).parent),
        "tmp": str(tmp),
    }
    argv = [_expand(a, subs) for a in obligation["command"]]
    child_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TMPDIR": str(tmp),
        "PYTHONDONTWRITEBYTECODE": "1",
        **{k: _expand(v, subs) for k, v in obligation.get("env", {}).items()},
    }
    if srt is not None:
        profile = write_profile(
            run_dir / f"verifier-{obligation['id']}.json", verifier_profile(tmp, deny_read)
        )
        cmd, env = wrap(srt, profile, argv, child_env)
    else:
        cmd, env = argv, child_env

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=candidate,
            env=env,
            capture_output=True,
            timeout=obligation.get("timeout_s", 300),
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") + (exc.stderr or b"")
        return CheckerRun("timeout", None, out, int((time.monotonic() - start) * 1000), argv)
    except OSError as exc:
        return CheckerRun("unavailable", None, str(exc).encode(), 0, argv)
    elapsed = int((time.monotonic() - start) * 1000)
    outcome = "crash" if proc.returncode < 0 else classify(proc.returncode)
    return CheckerRun(outcome, proc.returncode, proc.stdout + proc.stderr, elapsed, argv)
