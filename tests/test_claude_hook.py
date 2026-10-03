"""Acceptance tests for the Claude Code Stop hook (T80 slice 2, contracts/0034).

`ohx hook install` adds a Stop hook to the project's `.claude/settings.local.json` (the
owner's own settings; other settings and hooks are kept, and installing twice adds it
once). When the agent says it is done, Claude Code runs `ohx hook claude-stop`: it
verifies the change, lets the agent stop on READY, and otherwise blocks the stop with a
reason the agent reads: what failed, and that the tests are locked, so the fix belongs
in the code. After three blocked attempts in a row it lets the agent stop and leaves
the owner a message, so an agent that cannot fix it is never trapped. Claude Code gives a
Stop hook 30 seconds unless the hook says otherwise, so the installed hook sets its own
time limit.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
SUITE = """\
from calc import add, mul


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(2, 3) == 6
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    return repo


def _stop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    active: bool = False,
    session: str = "s1",
    raw: str | None = None,
) -> tuple[int, dict[str, Any]]:
    event = {
        "session_id": session,
        "hook_event_name": "Stop",
        "cwd": str(repo),
        "stop_hook_active": active,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw if raw is not None else json.dumps(event)))
    capsys.readouterr()
    code = main(["hook", "claude-stop", "--sandbox", "none"])
    out = capsys.readouterr().out.strip()
    return code, (json.loads(out) if out else {})


def _settings(repo: Path) -> dict[str, Any]:
    return json.loads((repo / ".claude" / "settings.local.json").read_text())  # type: ignore[no-any-return]


def test_one_command_installs_the_stop_hook_with_its_own_time_limit(repo: Path) -> None:
    assert main(["hook", "install"]) == EXIT_OK
    stops = _settings(repo)["hooks"]["Stop"]
    commands = [h for group in stops for h in group["hooks"]]
    assert len(commands) == 1
    assert commands[0]["type"] == "command"
    assert commands[0]["command"].endswith("hook claude-stop")
    assert commands[0]["timeout"] >= 300  # Claude Code's default for Stop is 30 seconds


def test_installing_keeps_other_settings_and_adds_the_hook_once(repo: Path) -> None:
    (repo / ".claude").mkdir()
    existing: dict[str, Any] = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}],
        },
    }
    (repo / ".claude" / "settings.local.json").write_text(json.dumps(existing))
    assert main(["hook", "install"]) == EXIT_OK
    assert main(["hook", "install"]) == EXIT_OK
    settings = _settings(repo)
    assert settings["permissions"] == existing["permissions"]
    assert settings["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
    commands = [h["command"] for group in settings["hooks"]["Stop"] for h in group["hooks"]]
    assert "say done" in commands
    assert sum(c.endswith("hook claude-stop") for c in commands) == 1


def test_a_ready_change_lets_the_agent_stop(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    code, out = _stop(monkeypatch, capsys, repo)
    assert code == EXIT_OK
    assert out.get("decision") != "block"


def test_an_agent_that_edits_a_test_to_get_green_is_sent_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 7"))
    code, out = _stop(monkeypatch, capsys, repo)
    assert code == EXIT_OK
    assert out["decision"] == "block"
    reason = out["reason"]
    assert "BLOCKED" in reason
    assert "test_mul" in reason  # what failed
    assert "locked" in reason  # and why editing the test does not help


def test_after_three_blocked_attempts_the_agent_may_stop_and_the_owner_is_told(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a * b", "a + b"))
    decisions = []
    for attempt in range(4):
        _, out = _stop(monkeypatch, capsys, repo, active=attempt > 0)
        decisions.append(out.get("decision"))
    assert decisions[:3] == ["block", "block", "block"]
    assert decisions[3] != "block"
    assert "BLOCKED" in out["systemMessage"]
    # A new session starts counting again.
    _, out = _stop(monkeypatch, capsys, repo, session="s2")
    assert out.get("decision") == "block"


def test_without_a_contract_the_hook_does_not_block_and_says_how_to_start(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _stop(monkeypatch, capsys, repo)
    assert code == EXIT_OK
    assert out.get("decision") != "block"
    assert "ohx init --lock-tests" in out.get("systemMessage", "")


def test_unreadable_hook_input_does_not_crash(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    code, out = _stop(monkeypatch, capsys, repo, raw="not json")
    assert code == EXIT_OK
    assert out.get("decision") != "block"


def test_the_shared_claude_settings_are_checker_configuration(tmp_path: Path) -> None:
    from openharnx.weakening import compare, snapshot

    (tmp_path / ".claude").mkdir()
    settings = tmp_path / ".claude" / "settings.json"
    settings.write_text('{"hooks": {"Stop": []}}')
    baseline = snapshot(tmp_path, [".claude/settings.json"])
    settings.write_text("{}")  # the hook removed
    found = compare(baseline, snapshot(tmp_path, [".claude/settings.json"]))
    assert found == [".claude/settings.json: check configuration changed since acceptance"]
