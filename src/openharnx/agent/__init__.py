"""Launch a coding agent (Claude Code by default) for one phase of work.

The agent is the engine; OpenHarnX decides what it is asked, what it may
touch and how its result is judged. In the sandbox the agent gets an explicit
environment allowlist and cannot write the OpenHarnX store or its own
configuration (hooks, settings, skills), which would persist after the run.

Everything specific to one agent lives in its `AgentAdapter` (proposal 13):
command, model endpoints, credentials, configuration paths, how its events
read as progress and how it reports cost. Claude Code is the first adapter.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openharnx.sandbox import wrap, write_profile


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    command: tuple[str, ...]
    model_domains: tuple[str, ...]
    pass_through: tuple[str, ...]  # environment variables the agent needs (credentials)
    config_dir: str  # under the home directory; the agent may write it
    config_files: tuple[str, ...]  # other writable files under the home directory
    protected_config: tuple[str, ...]  # under config_dir; never writable (they persist)
    describe: Callable[[dict[str, Any], Path], list[str]]  # one event as progress lines
    cost: Callable[[bytes], float | None]
    temp_env: tuple[str, ...] = ()  # variables that move the agent's own temp directory


def _short(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _where(path: str, cwd: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.relative_to(cwd))
        except ValueError:
            return p.name  # outside the repository: the name is enough
    return path


_TOOL_VERBS = {
    "Read": ("read", "file_path"),
    "Write": ("write", "file_path"),
    "Edit": ("edit", "file_path"),
    "MultiEdit": ("edit", "file_path"),
    "NotebookEdit": ("edit", "notebook_path"),
    "Bash": ("run", "command"),
    "Grep": ("search", "pattern"),
    "Glob": ("find", "pattern"),
}


def _claude_describe(event: dict[str, Any], cwd: Path) -> list[str]:
    if event.get("type") != "assistant":
        return []
    lines = []
    for item in event.get("message", {}).get("content", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and str(item.get("text", "")).strip():
            lines.append("note " + _short(str(item["text"])))
        elif item.get("type") == "tool_use":
            name = str(item.get("name", "tool"))
            raw_args = item.get("input")
            args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
            verb, key = _TOOL_VERBS.get(name, (name.lower(), ""))
            target = str(args.get(key, "")) if key else ""
            if key.endswith("path") and target:
                target = _where(target, cwd)
            lines.append(_short(f"{verb} {target}".strip()))
    return lines


def _claude_cost(output: bytes) -> float | None:
    """The `total_cost_usd` of the final result event; None when not reported."""
    for line in reversed(output.decode("utf-8", "replace").strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "total_cost_usd" in data:
            value = data["total_cost_usd"]
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            return float(value) if ok else None
    return None


CLAUDE_CODE = AgentAdapter(
    name="claude-code",
    command=(
        "claude",
        "-p",
        "{prompt}",
        "--output-format",
        "stream-json",  # one event per line, so progress shows while it works
        "--verbose",
        "--max-turns",
        "40",
        "--max-budget-usd",
        "1.00",
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--permission-mode",
        "bypassPermissions",  # safe only because the OS sandbox is the boundary
    ),
    model_domains=("api.anthropic.com", "*.anthropic.com", "claude.ai", "*.claude.ai"),
    pass_through=("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"),
    config_dir=".claude",
    config_files=(".claude.json", ".claude.json.lock"),
    protected_config=(
        "settings.json",
        "settings.local.json",
        "hooks",
        "agents",
        "skills",
        "plugins",
        "CLAUDE.md",
    ),
    describe=_claude_describe,
    cost=_claude_cost,
    # Its shell state goes under /tmp/claude-<uid>, not TMPDIR; the sandbox denies that.
    temp_env=("CLAUDE_CODE_TMPDIR",),
)

DEFAULT_COMMAND = list(CLAUDE_CODE.command)
GENERIC_PASS_THROUGH = ("USER", "TERM")


@dataclass(frozen=True)
class AgentRun:
    exit_code: int | None
    output: bytes
    cost_usd: float | None
    duration_ms: int
    protection: str


def agent_profile(
    write: list[Path], home: Path, ohx_home: Path, adapter: AgentAdapter = CLAUDE_CODE
) -> dict[str, object]:
    config = home / adapter.config_dir
    return {
        "network": {"allowedDomains": list(adapter.model_domains), "deniedDomains": []},
        "filesystem": {
            "denyRead": ["~/.ssh", str(ohx_home / "keys")],
            "allowWrite": [
                *(str(p) for p in write),
                str(config),
                *(str(home / f) for f in adapter.config_files),
                str(home / ".cache"),
            ],
            "denyWrite": [str(ohx_home), *(str(config / p) for p in adapter.protected_config)],
        },
    }


def _agent_temp() -> Path:
    """Outside the OpenHarnX home, which the agent may not write. Short where /tmp
    is writable, because agents put socket paths under their temp directory."""
    try:
        return Path(tempfile.mkdtemp(prefix="ohx-", dir="/tmp")).resolve()
    except OSError:
        return Path(tempfile.mkdtemp(prefix="ohx-agent-")).resolve()


def elapsed(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


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
    adapter: AgentAdapter = CLAUDE_CODE,
    on_event: Callable[[str], None] | None = None,
) -> AgentRun:
    """Run the agent; each event it emits is shown through `on_event` as it happens."""
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = _agent_temp()
    argv = [a.replace("{prompt}", prompt) for a in command]
    env_vars = {"OHX_PHASE": phase, **extra_env}
    if srt is not None:
        allowed = (*adapter.pass_through, *GENERIC_PASS_THROUGH)
        child = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(Path.home()),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TMPDIR": str(tmp),
            "TMPPREFIX": str(tmp / "zsh"),  # zsh heredoc files; zsh ignores TMPDIR
            **{k: os.environ[k] for k in allowed if k in os.environ},
            **dict.fromkeys(adapter.temp_env, str(tmp)),
            **env_vars,
        }
        profile = write_profile(
            run_dir / f"agent-{phase}.json",
            agent_profile([*writable, tmp], Path.home(), ohx_home, adapter),
        )
        cmd, env = wrap(srt, profile, argv, child)
        protection = "enforced: agent ran in the srt sandbox"
    else:
        cmd, env = argv, {**os.environ, **env_vars}
        protection = "none: agent ran without isolation"

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        return AgentRun(None, str(exc).encode(), None, 0, protection)

    stderr: list[bytes] = []
    reader = threading.Thread(
        target=lambda: stderr.append(proc.stderr.read() if proc.stderr else b"")
    )
    reader.start()
    timed_out = threading.Event()

    def _expire() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout_s, _expire)
    timer.start()
    stdout: list[bytes] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            stdout.append(raw)
            if on_event is None:
                continue
            try:
                event = json.loads(raw)
            except ValueError:
                continue  # not an event: kept in the record, not shown
            if isinstance(event, dict):
                for line in adapter.describe(event, cwd):
                    on_event(f"  [{elapsed(time.monotonic() - start)}] {line}")
        proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:  # interrupted: never leave the agent running
            proc.kill()
            proc.wait()
        reader.join()
    out = b"".join(stdout)
    ms = int((time.monotonic() - start) * 1000)
    code = None if timed_out.is_set() else proc.returncode
    return AgentRun(code, out + b"".join(stderr), adapter.cost(out), ms, protection)
