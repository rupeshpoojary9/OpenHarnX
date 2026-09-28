"""Launch a coding agent (Claude Code by default) for one phase of work.

The agent is the engine; OpenHarnX decides what it is asked, what it may
touch and how its result is judged. In the sandbox the agent gets an explicit
environment allowlist and cannot write the OpenHarnX store or its own
configuration (hooks, settings, skills), which would persist after the run.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from openharnx.sandbox import wrap, write_profile

DEFAULT_COMMAND = [
    "claude",
    "-p",
    "{prompt}",
    "--output-format",
    "json",
    "--max-turns",
    "40",
    "--max-budget-usd",
    "1.00",
    "--setting-sources",
    "project",
    "--strict-mcp-config",
    "--permission-mode",
    "bypassPermissions",  # safe only because the OS sandbox is the boundary
]

MODEL_DOMAINS = ["api.anthropic.com", "*.anthropic.com", "claude.ai", "*.claude.ai"]
PASS_THROUGH = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "USER", "TERM")


@dataclass(frozen=True)
class AgentRun:
    exit_code: int | None
    output: bytes
    cost_usd: float | None
    duration_ms: int
    protection: str


def agent_profile(write: list[Path], home: Path, ohx_home: Path) -> dict[str, object]:
    claude = home / ".claude"
    return {
        "network": {"allowedDomains": MODEL_DOMAINS, "deniedDomains": []},
        "filesystem": {
            "denyRead": ["~/.ssh", str(ohx_home / "keys")],
            "allowWrite": [
                *(str(p) for p in write),
                str(claude),
                str(home / ".claude.json"),
                str(home / ".claude.json.lock"),
                str(home / ".cache"),
            ],
            "denyWrite": [
                str(ohx_home),
                *(
                    str(claude / p)
                    for p in (
                        "settings.json",
                        "settings.local.json",
                        "hooks",
                        "agents",
                        "skills",
                        "plugins",
                        "CLAUDE.md",
                    )
                ),
            ],
        },
    }


def _cost(output: bytes) -> float | None:
    try:
        data = json.loads(output.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    value = data.get("total_cost_usd") if isinstance(data, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def launch(
    command: list[str],
    prompt: str,
    *,
    cwd: Path,
    run_dir: Path,
    phase: str,
    writable: list[Path],
    srt: Path | None,
    ohx_home: Path,
    extra_env: dict[str, str],
    timeout_s: int = 900,
) -> AgentRun:
    run_dir.mkdir(parents=True, exist_ok=True)
    # Outside the OpenHarnX home, which the agent may not write.
    tmp = Path(tempfile.mkdtemp(prefix="ohx-agent-"))
    argv = [a.replace("{prompt}", prompt) for a in command]
    env_vars = {"OHX_PHASE": phase, **extra_env}
    if srt is not None:
        child = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(Path.home()),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TMPDIR": str(tmp),
            **{k: os.environ[k] for k in PASS_THROUGH if k in os.environ},
            **env_vars,
        }
        profile = write_profile(
            run_dir / f"agent-{phase}.json",
            agent_profile([*writable, tmp], Path.home(), ohx_home),
        )
        cmd, env = wrap(srt, profile, argv, child)
        protection = "enforced: agent ran in the srt sandbox"
    else:
        cmd, env = argv, {**os.environ, **env_vars}
        protection = "none: agent ran without isolation"

    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") + (exc.stderr or b"")
        return AgentRun(None, out, _cost(out), int((time.monotonic() - start) * 1000), protection)
    except OSError as exc:
        return AgentRun(None, str(exc).encode(), None, 0, protection)
    elapsed = int((time.monotonic() - start) * 1000)
    return AgentRun(
        proc.returncode, proc.stdout + proc.stderr, _cost(proc.stdout), elapsed, protection
    )
