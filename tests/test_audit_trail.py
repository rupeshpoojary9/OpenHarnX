"""Acceptance tests for the audit trail (T87 item 3, contracts/0018).

From the owner's question after a real `ohx bug` run (2026-10-03): "if
multiple agents are working, is it audited who did what and touched what?"
The store kept each agent run's cost and output, but not which agent, model
or session it was, not which files it changed, and not who approved or
accepted. One candidate snapshot at the end could not say which actor changed
which file.

Each agent run now records the agent's identity and the files it changed, as
observed by OpenHarnX from snapshots before and after the run (not as the
agent reports them). Acceptance and approval record who did them. `ohx audit`
prints the trail, and changes no recorded actor accounts for are shown as
made outside OpenHarnX. Self-contained.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main

# Emits a Claude Code style init event; the fix edits calc.py through a shell
# command and reports no edit event, so only observation can attribute it.
AGENT = r"""
import json, os, subprocess
from pathlib import Path

print(json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1234",
                  "model": "model-x", "claude_code_version": "9.9.9"}), flush=True)
out = os.environ.get("OHX_OUT", "")
if os.environ["OHX_PHASE"] == "investigate":
    Path(out, "proposal.md").write_text("Cause: calc.py subtracts.\nRule: add(a, b) is a + b.\n")
    Path(out, "test_proposed.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
else:
    subprocess.run(["/bin/sh", "-c", "printf 'def add(a, b):\\n    return a + b\\n' > calc.py"])
print(json.dumps({"type": "result", "total_cost_usd": 0.01}), flush=True)
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "notes.txt").write_text("notes\n")
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    (repo / "ohx.toml").write_text(
        f'python = "{sys.executable}"\n\n[agent]\ncommand = ["{sys.executable}", "{agent}"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Owner")
    _git(repo, "config", "user.email", "owner@example.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["bug", "new", "add is wrong", "--sandbox", "none"]) == EXIT_OK
    assert main(["bug", "approve", "BUG-001"]) == EXIT_OK
    assert main(["bug", "fix", "BUG-001", "--sandbox", "none"]) == EXIT_OK
    return repo


def _audit(capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert main(["audit"]) == EXIT_OK
    return capsys.readouterr().out.splitlines()


def _line(lines: list[str], *words: str) -> int:
    for i, line in enumerate(lines):
        if all(w in line for w in words):
            return i
    raise AssertionError(f"no line with {words!r} in:\n" + "\n".join(lines))


def test_each_agent_run_names_the_agent_model_version_and_session(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _audit(capsys)
    for phase in ("investigate", "fix"):
        line = lines[_line(lines, phase, "BUG-001", "sess-1234")]
        assert "model-x" in line and "9.9.9" in line


def test_files_an_agent_changed_are_observed_not_reported(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _audit(capsys)
    assert "changed nothing" in lines[_line(lines, "investigate", "BUG-001")]
    fix = lines[_line(lines, "fix", "BUG-001")]
    assert "calc.py" in fix
    assert "notes.txt" not in fix


def test_acceptance_and_approval_name_who_did_them(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _audit(capsys)
    approved = _line(lines, "approved", "BUG-001", "Test Owner", "owner@example.com")
    accepted = _line(lines, "accepted", "Test Owner", "owner@example.com")
    fix = _line(lines, "fix", "BUG-001")
    assert accepted < fix and approved < fix


def test_changes_no_recorded_actor_made_are_flagged(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "notes.txt").write_text("edited by someone else\n")
    main(["verify", "--sandbox", "none"])
    lines = _audit(capsys)
    outside = lines[_line(lines, "outside OpenHarnX")]
    assert "notes.txt" in outside
    assert "calc.py" not in outside


def test_the_trail_is_in_order_and_ends_with_the_verdict(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _audit(capsys)
    reported = _line(lines, "BUG-001", "reported")
    investigate = _line(lines, "investigate", "BUG-001")
    fix = _line(lines, "fix", "BUG-001")
    verdict = _line(lines, "READY")
    assert reported < investigate < fix < verdict
