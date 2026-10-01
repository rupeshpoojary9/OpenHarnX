"""Verifier isolation through Anthropic sandbox-runtime (`srt`, ADR-0007).

Operational rules from the threat model: an explicit environment allowlist
(the sandbox does not filter the environment), a short TMPDIR for `srt`
itself, and the child's own TMPDIR set inside the sandboxed command.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path

SRT_ENV = "OHX_SRT"


def find_srt() -> Path | None:
    configured = os.environ.get(SRT_ENV)
    if configured:
        return Path(configured)
    found = shutil.which("srt")
    return Path(found) if found else None


def verifier_profile(write_dir: Path, deny_read: list[str]) -> dict[str, object]:
    """Writes only to the run's own directory; no network; secrets unreadable."""
    return {
        "network": {"allowedDomains": [], "deniedDomains": []},
        "filesystem": {
            "denyRead": deny_read,
            "allowWrite": [str(write_dir)],
            "denyWrite": [],
        },
    }


def write_profile(path: Path, profile: dict[str, object]) -> Path:
    path.write_text(json.dumps(profile, indent=2))
    return path


def wrap(
    srt: Path,
    profile: Path,
    argv: list[str],
    child_env: dict[str, str],
    started: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return the outer command and outer environment for a sandboxed run.

    The allowlist is applied to srt's own environment, so nothing from the
    caller's environment reaches the child (threat T11). The child then sees
    exactly `child_env` plus the proxy settings srt adds for its network
    allowlist; wiping the environment inside the sandbox would remove those.

    With `started`, that file is created inside the sandbox just before the
    command runs; if it is missing afterwards, srt never ran the command and
    its exit code says nothing about the command (VERIFY-12).
    """
    inner = shlex.join(["env", f"TMPDIR={child_env['TMPDIR']}", *argv])
    if started is not None:
        inner = shlex.join(["touch", str(started)]) + " && exec " + inner
    outer_env = {**child_env, "TMPDIR": "/tmp"}  # srt's socket path must stay short
    return [str(srt), "-s", str(profile), "-c", inner], outer_env
