"""OpenCode verifies when the agent goes idle, as Claude Code does when it stops (T104,
contracts/0068).

Claude Code was the only agent with a built-in integration. OpenCode loads project
plugins from `.opencode/plugins/`, fires `session.idle` when the agent finishes, and
gives a plugin a shell, a toast in its screen (`client.tui.showToast`) and a way to put a
message into the session (`client.session.prompt`) (OpenCode's plugin docs and its SDK
types, read 2026-10-07).

`ohx hook install --agent opencode` writes a plugin that, on `session.idle`, runs
`ohx hook opencode-stop` and acts on its answer: it shows the verdict as a toast, and
when the change is blocked it sends the agent back with what failed, at most three times
in a row in one session; a passing verdict resets the count. The verdict logic is the
one the Claude Code hook uses. Not yet run with a live OpenCode session, so it is
experimental until one is recorded.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
FIXED = CALC.replace("    return a\n", "    return a / 2\n")
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
ACCEPTANCE = "from calc import half\n\n\ndef test_half():\n    assert half(10) == 5\n"
PLUGIN = Path(".opencode") / "plugins" / "openharnx.js"


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
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    (repo / ".gitignore").write_text(".opencode/\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _contract() -> None:
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK


def _stop(repo: Path, capsys: pytest.CaptureFixture[str], session: str = "ses_1") -> dict[str, Any]:
    capsys.readouterr()
    args = ["hook", "opencode-stop", "--session", session, "--cwd", str(repo)]
    assert main([*args, "--sandbox", "none"]) == EXIT_OK
    answer: dict[str, Any] = json.loads(capsys.readouterr().out)
    return answer


def test_install_writes_a_project_plugin_once(repo: Path) -> None:
    assert main(["hook", "install", "--agent", "opencode"]) == EXIT_OK
    assert main(["hook", "install", "--agent", "opencode"]) == EXIT_OK
    plugin = (repo / PLUGIN).read_text()
    assert list((repo / ".opencode" / "plugins").iterdir()) == [repo / PLUGIN]
    assert '"session.idle"' in plugin
    assert "hook opencode-stop" in plugin or '"opencode-stop"' in plugin
    assert "client.session.prompt" in plugin and "client.tui.showToast" in plugin
    assert not (repo / ".claude").exists()  # the Claude Code hook is a separate choice


def test_the_claude_code_hook_is_still_the_default(repo: Path) -> None:
    assert main(["hook", "install"]) == EXIT_OK
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / PLUGIN).exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_plugin_is_valid_javascript(repo: Path) -> None:
    assert main(["hook", "install", "--agent", "opencode"]) == EXIT_OK
    module = repo / "plugin.mjs"
    module.write_text((repo / PLUGIN).read_text())
    r = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_without_a_contract_it_says_how_to_start(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = _stop(repo, capsys)
    assert answer["send_back"] is None
    assert "ohx init --lock-tests" in answer["message"]


def test_a_passing_change_is_told_and_not_sent_back(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    answer = _stop(repo, capsys)
    assert answer["send_back"] is None
    assert answer["message"].startswith("OpenHarnX: READY")
    assert answer["verdict"] == "ready"


def test_a_blocked_change_goes_back_to_the_agent_with_what_failed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    answer = _stop(repo, capsys)
    assert answer["verdict"] == "blocked"
    assert "test_add" in answer["send_back"] and "locked" in answer["send_back"]
    assert "attempt 1 of 3" in answer["message"]


def test_after_three_blocks_in_a_row_the_agent_is_left_alone(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    sent = [_stop(repo, capsys)["send_back"] is not None for _ in range(4)]
    assert sent == [True, True, True, False]
    last = _stop(repo, capsys, session="ses_2")  # another session counts afresh
    assert last["send_back"] is not None


def test_a_pass_resets_the_count(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _contract()
    broken = FIXED.replace("a + b", "a - b")
    (repo / "calc.py").write_text(broken)
    for _ in range(2):
        _stop(repo, capsys)
    (repo / "calc.py").write_text(FIXED)
    assert _stop(repo, capsys)["send_back"] is None
    (repo / "calc.py").write_text(broken)
    assert "attempt 1 of 3" in _stop(repo, capsys)["message"]


def test_the_report_names_the_opencode_session(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    _stop(repo, capsys, session="ses_abc")
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report = json.loads(runs[-1].read_text())
    assert report["agent"] == {"tool": "opencode", "session": "ses_abc"}
    assert "OpenCode" in report["cost"]["agent_work"] and "unknown" in report["cost"]["agent_work"]


def test_a_failure_inside_the_hook_is_reported_not_raised(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _contract()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("openharnx.app.hook.verify", boom)
    answer = _stop(repo, capsys)
    assert answer["send_back"] is None and "could not verify" in answer["message"]
    assert "disk full" in answer["message"]


def test_the_claude_code_hooks_answers_are_unchanged(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    event = {"session_id": "s", "cwd": str(repo), "stop_hook_active": False}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    capsys.readouterr()
    assert main(["hook", "claude-stop", "--sandbox", "none"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"].startswith("OpenHarnX: READY")
    assert os.environ.get("OHX_HOME")
