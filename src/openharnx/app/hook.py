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
from openharnx.report import NO_REGRESSIONS, PASSING, verdict
from openharnx.workspace import NotARepository, repo_root

SETTINGS = Path(".claude") / "settings.local.json"
HOOK_ARGS = ["hook", "claude-stop"]
# Above Claude Code's 600-second default for command hooks (hooks reference, 2026-10-04),
# so a long verification is not cut off.
TIMEOUT_S = 900
MAX_BLOCKS = 3
STATE = "claude-stop.json"
SHOWN = 8  # failing checks listed in the reason
NAMED_TESTS = 10  # failing agreed tests named per check
ERROR_LINES = 12  # error lines quoted per check
LINE_CHARS = 200
REASON_CHARS = 5500  # the whole reason, so a noisy failure cannot flood the agent's context
NO_NEW_FAILURES = "no-new-failures-"
# Lines in a checker's output that say what went wrong (pytest, node --test, Vitest, Go).
ERROR_LINE = re.compile(
    r"^\s*(E\s|FAILED |ERROR |--- FAIL|not ok |FAIL |✗|×)|AssertionError|Error:|panic:"
)
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


# Where a locked copy ran: the run's tree view or the protected store copy. Error lines
# name files there; the agent knows them by their place in the project.
LOCKED_PREFIX = re.compile(r"(?:\.\./)*[^\s:]*?/(?:tree-[^/\s]+|protected/[0-9a-f]{16})/")


def _errors(path: Path | None) -> list[str]:
    """The lines of a check's output that say what failed; the last lines if none do."""
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    for raw in text.splitlines():
        line = LOCKED_PREFIX.sub("", raw).strip()
        if ERROR_LINE.search(line) and line not in found:
            found.append(line)
    if not found:
        found = [line.strip() for line in text.splitlines() if line.strip()][-5:]
    return [line if len(line) <= LINE_CHARS else line[: LINE_CHARS - 3] + "..." for line in found]


def _reason(report: dict[str, Any], run_dir: Path) -> str:
    """What the agent needs to fix a block (T98): each failing check, the agreed tests that
    failed, the error lines and where the full output is; bounded in length."""
    notes = {o["obligation_id"]: o.get("note", "") for o in report.get("observations", [])}
    evidence = report.get("evidence") or {}
    per_test = report.get("acceptance_tests") or {}

    def output(oid: str) -> Path | None:
        ev = evidence.get(oid)
        return run_dir / ev["file"] if ev else None

    failing = [o for o in report["gate"]["obligations"] if o["status"] != "pass" and o["mandatory"]]
    lines = [f"OpenHarnX: {verdict(report['readiness'])}. These checks did not pass:"]
    shown: list[str] = []
    for o in failing[:SHOWN]:
        oid = o["obligation_id"]
        detail = notes.get(oid) or ", ".join(o["reasons"])
        lines.append(f"- {oid}: {detail[:400]}")
        failed = [t.rsplit("::", 1)[-1] for t, s in sorted((per_test.get(oid) or {}).items())
                  if s == "fail"]  # fmt: skip
        if failed:
            more = f" and {len(failed) - NAMED_TESTS} more" if len(failed) > NAMED_TESTS else ""
            lines.append(f"  Agreed tests that failed: {', '.join(failed[:NAMED_TESTS])}{more}")
        source = oid.removeprefix(NO_NEW_FAILURES) if oid.startswith(NO_NEW_FAILURES) else oid
        errors = _errors(output(source))
        if errors and errors == shown:
            lines.append("  Errors: the same as above")
        elif errors:
            lines.append("  Errors:")
            lines += [f"    {e}" for e in errors[:ERROR_LINES]]
            if len(errors) > ERROR_LINES:
                lines.append(f"    and {len(errors) - ERROR_LINES} more error lines")
            shown = errors
        path = output(source)
        if path is not None and path.is_file():
            lines.append(f"  Full output: {path}")
    if len(failing) > SHOWN:
        lines.append(f"- and {len(failing) - SHOWN} more checks; see the report")
    closing = (
        "The tests and check configuration are locked: editing, skipping or deleting a"
        " test does not change this result. Fix the code so the locked tests pass, then"
        " finish again."
    )
    body = "\n".join(lines)
    room = REASON_CHARS - len(closing) - 80
    if len(body) > room:
        body = body[:room].rsplit("\n", 1)[0] + "\n... and more; read the full output files"
    return f"{body}\n{closing}"


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
    agent = {"tool": "claude-code", "session": session} if session else None
    record, run_dir = verify(where, sandbox=sandbox, agent=agent)
    report = record.body
    where_report = f"Report: {run_dir / 'report.md'}"
    if report["readiness"] in PASSING:
        _record(pdir, session, 0)
        if report["readiness"] != NO_REGRESSIONS:
            return {
                "systemMessage": "OpenHarnX: READY. Every check passed, the agreed acceptance"
                f" tests included. {where_report}"
            }
        still = len(report["claims"]["still_failing"])
        return {
            "systemMessage": "OpenHarnX: NO REGRESSIONS. Nothing that passed before broke,"
            " but no acceptance tests define the task, so it is not shown to be done"
            + (f"; {still} locked test(s) still fail as before." if still else ".")
            + f" {where_report}"
        }
    if blocked >= MAX_BLOCKS:
        _record(pdir, session, 0)
        return {
            "systemMessage": f"OpenHarnX: still {verdict(report['readiness'])} after"
            f" {MAX_BLOCKS} attempts; the agent stopped. {where_report}"
        }
    _record(pdir, session, blocked + 1)
    return {
        **_send_back(_reason(report, run_dir)),
        "systemMessage": f"OpenHarnX: {verdict(report['readiness'])} (attempt {blocked + 1}"
        f" of {MAX_BLOCKS}); sent back to the agent with what failed. {where_report}",
    }


def main_stop(sandbox: str) -> dict[str, Any]:
    return claude_stop(sys.stdin.read(), Path.cwd(), sandbox)
