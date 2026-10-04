"""The Claude Code Stop hook (T80): verify when the agent says it is done.

`install` adds the hook to the project's `.claude/settings.local.json`, the owner's own
settings, keeping everything else there. `claude_stop` reads the hook event, verifies,
and tells Claude Code whether the agent may stop. A BLOCKED reason goes back to the
agent, as hook feedback where Claude Code supports it (a plain block is shown to the
user as a hook error); after `MAX_BLOCKS` blocked attempts in a row in one session the
agent may stop and the owner gets the message instead, so an agent that cannot fix it
is not trapped.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from openharnx.app import UsageError, _open, verify
from openharnx.workspace import NotARepository, repo_root

SETTINGS = Path(".claude") / "settings.local.json"
HOOK_ARGS = ["hook", "claude-stop"]
# Above Claude Code's 600-second default for command hooks (hooks reference, 2026-10-04),
# so a long verification is not cut off.
TIMEOUT_S = 900
MAX_BLOCKS = 3
STATE = "claude-stop.json"
SHOWN = 8  # failing checks listed in the reason
# First Claude Code to accept `additionalContext` from a Stop hook (its changelog, 2.1.163).
FEEDBACK_SINCE = (2, 1, 163)


def _command() -> str:
    found = shutil.which("ohx")
    return f"{found or 'ohx'} {' '.join(HOOK_ARGS)}"


def _is_ours(hook: Any) -> bool:
    return isinstance(hook, dict) and str(hook.get("command", "")).endswith(" ".join(HOOK_ARGS))


def install(cwd: Path) -> Path:
    """Add the Stop hook once; other settings and hooks stay as they are."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    path = root / SETTINGS
    settings: dict[str, Any] = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsageError(f"{path} is not valid JSON; fix it first: {exc}") from exc
        if not isinstance(settings, dict):
            raise UsageError(f"{path} is not a JSON object")
    hooks = settings.setdefault("hooks", {})
    stops = hooks.setdefault("Stop", [])
    groups = [g for g in stops if isinstance(g, dict) and isinstance(g.get("hooks"), list)]
    for group in groups:
        group["hooks"] = [h for h in group["hooks"] if not _is_ours(h)]
    hooks["Stop"] = [g for g in stops if not isinstance(g, dict) or g.get("hooks") != []]
    hooks["Stop"].append(
        {"hooks": [{"type": "command", "command": _command(), "timeout": TIMEOUT_S}]}
    )
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path


def _reason(report: dict[str, Any]) -> str:
    notes = {o["obligation_id"]: o.get("note", "") for o in report.get("observations", [])}
    failing = [o for o in report["gate"]["obligations"] if o["status"] != "pass" and o["mandatory"]]
    lines = [f"OpenHarnX: {report['readiness'].upper()}. These checks did not pass:"]
    for o in failing[:SHOWN]:
        detail = notes.get(o["obligation_id"]) or ", ".join(o["reasons"])
        lines.append(f"- {o['obligation_id']}: {detail[:400]}")
    lines.append(
        "The tests and check configuration are locked: editing, skipping or deleting a"
        " test does not change this result. Fix the code so the locked tests pass, then"
        " finish again."
    )
    return "\n".join(lines)


def _claude_version() -> tuple[int, int, int] | None:
    """The version of the `claude` on PATH, or None when it cannot be told."""
    found = shutil.which("claude")
    if found is None:
        return None
    try:
        out = subprocess.run([found, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", out.stdout)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _send_back(reason: str) -> dict[str, Any]:
    """Keep the agent working: as feedback where supported, else as a block, never neither."""
    version = _claude_version()
    if version is not None and version >= FEEDBACK_SINCE:
        return {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}
    return {"decision": "block", "reason": reason}


def _attempts(pdir: Path, session: str, active: bool) -> int:
    """Blocked attempts so far in this session's current run of stops."""
    try:
        state = json.loads((pdir / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not active or not isinstance(state, dict) or state.get("session") != session:
        return 0
    count = state.get("blocked", 0)
    return count if isinstance(count, int) else 0


def _record(pdir: Path, session: str, blocked: int) -> None:
    (pdir / STATE).write_text(json.dumps({"session": session, "blocked": blocked}))


def claude_stop(stdin: str, cwd: Path, sandbox: str = "auto") -> dict[str, Any]:
    """The hook's answer to Claude Code: empty to let the agent stop, or a decision."""
    try:
        event = json.loads(stdin) if stdin.strip() else {}
    except ValueError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    where = Path(event.get("cwd") or cwd)
    session = str(event.get("session_id", ""))
    pdir = where
    try:
        _, pdir, store = _open(where)
        contract = store.latest("contract")
        store.close()
    except UsageError:
        contract = None
    if contract is None:
        return {
            "systemMessage": "OpenHarnX: nothing verified, this repository has no contract yet;"
            " run `ohx init --lock-tests` to lock its tests."
        }
    blocked = _attempts(pdir, session, bool(event.get("stop_hook_active")))
    record, run_dir = verify(where, sandbox=sandbox)
    report = record.body
    if report["readiness"] == "ready":
        _record(pdir, session, 0)
        return {}
    if blocked >= MAX_BLOCKS:
        _record(pdir, session, 0)
        return {
            "systemMessage": f"OpenHarnX: still {report['readiness'].upper()} after"
            f" {MAX_BLOCKS} attempts; the agent stopped. Report: {run_dir / 'report.md'}"
        }
    _record(pdir, session, blocked + 1)
    return _send_back(_reason(report))


def main_stop(sandbox: str) -> dict[str, Any]:
    return claude_stop(sys.stdin.read(), Path.cwd(), sandbox)
