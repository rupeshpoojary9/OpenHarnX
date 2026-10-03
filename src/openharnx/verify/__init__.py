"""Run one obligation's checker against the candidate and classify the result."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
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
    sandbox_started: bool | None = None  # None: no sandbox requested


def _expand(value: str, subs: dict[str, str]) -> str:
    for key, sub in subs.items():
        value = value.replace("{" + key + "}", sub)
    return value


# Exit code of the launcher when the checker module is not installed outside the candidate.
EXIT_CHECKER_IN_CANDIDATE = 120

# Runs `{python} -m <module>` without letting the candidate supply the checker (VERIFY-11).
# Started with -P, so the candidate is not first on sys.path. The module must resolve
# before the candidate is added; the candidate is then appended last, so project code
# stays importable but cannot replace the checker or anything it imports from the
# interpreter's own paths.
_LAUNCHER = (
    "import importlib.util, os, runpy, sys\n"
    "m = sys.argv[1]\n"
    "if importlib.util.find_spec(m.partition('.')[0]) is None:\n"
    "    sys.stderr.write(f'ohx: checker {m!r} is not installed outside the candidate\\n')\n"
    f"    raise SystemExit({EXIT_CHECKER_IN_CANDIDATE})\n"
    "sys.path.append(os.getcwd())\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_module(m, run_name='__main__', alter_sys=True)\n"
)


def guard_module_run(argv: list[str], python: str) -> list[str]:
    """Rewrite `<python> -m <module> args` to run through the launcher; leave others alone."""
    if len(argv) >= 3 and argv[0] == python and argv[1] == "-m":
        return [python, "-P", "-c", _LAUNCHER, *argv[2:]]
    return argv


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
    extra_env: dict[str, str] | None = None,
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
    argv = guard_module_run([_expand(a, subs) for a in obligation["command"]], python)
    child_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TMPDIR": str(tmp),
        "PYTHONDONTWRITEBYTECODE": "1",
        **{k: _expand(v, subs) for k, v in obligation.get("env", {}).items()},
        **(extra_env or {}),
    }
    if srt is not None:
        profile = write_profile(
            run_dir / f"verifier-{obligation['id']}.json", verifier_profile(tmp, deny_read)
        )
        started: Path | None = tmp / f"started-{uuid.uuid4().hex}"
        cmd, env = wrap(srt, profile, argv, child_env, started=started)
    else:
        started = None
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
    output = proc.stdout + proc.stderr
    if started is not None and not started.exists():
        # The sandbox never ran the checker, so its exit code is not a result (VERIFY-12).
        output += b"\nohx: the sandbox did not start the checker\n"
        return CheckerRun("unavailable", proc.returncode, output, elapsed, argv, False)
    outcome = "crash" if proc.returncode < 0 else classify(proc.returncode)
    return CheckerRun(outcome, proc.returncode, output, elapsed, argv, True if started else None)
