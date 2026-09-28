"""Acceptance tests for `ohx bug` (contracts/0003): issue -> investigation ->
owner approval -> contract -> agent fix -> verification, with retries.

Written before the feature. A scripted fake agent stands in for Claude Code,
so these tests spend nothing. Self-contained: the protected copy runs from
the OpenHarnX store.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main

BUGGY = "def add(a, b):\n    return a - b\n"

FAKE_AGENT = r"""
import json, os, sys
from pathlib import Path

mode, prompt = sys.argv[1], sys.argv[2]
phase, out = os.environ["OHX_PHASE"], os.environ.get("OHX_OUT", "")
log = Path(os.environ["FAKE_LOG"])
with log.open("a") as fh:
    fh.write(json.dumps({"phase": phase, "prompt": prompt}) + "\n")

REPRO = "from calc import add\n\n\ndef test_add_adds():\n    assert add(2, 3) == 5\n"
PASSING = "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"

if phase == "investigate":
    if mode == "edits-during-investigation":
        Path("calc.py").write_text("def add(a, b):\n    return a + b\n")
    Path(out, "proposal.md").write_text(
        "Cause: add subtracts instead of adding.\nRule: add(a, b) returns a + b.\n"
    )
    Path(out, "test_proposed.py").write_text(PASSING if mode == "no-repro" else REPRO)
elif phase == "fix":
    if mode == "good":
        Path("calc.py").write_text("def add(a, b):\n    return a + b\n")
    elif mode == "tamper":
        for t in Path("tests").glob("test_bug_*.py"):
            t.write_text("def test_nothing():\n    assert True\n")
    elif mode == "second-try" and "still fails" in prompt:
        Path("calc.py").write_text("def add(a, b):\n    return a + b\n")
print(json.dumps({"type": "result", "total_cost_usd": 0.01, "result": "done"}))
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(BUGGY)
    agent = tmp_path / "fake_agent.py"
    agent.write_text(FAKE_AGENT)
    (repo / "ohx.toml").write_text(
        f'python = "{sys.executable}"\n\n[agent]\n'
        f'command = ["{sys.executable}", "{agent}", "{mode}", "{{prompt}}"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "agent.log"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


def _log(tmp_path: Path) -> list[dict[str, str]]:
    lines = (tmp_path / "agent.log").read_text().splitlines()
    return [json.loads(x) for x in lines]


NEW = ["bug", "new", "add returns the wrong result", "--sandbox", "none"]
FIX = ["bug", "fix", "BUG-001", "--sandbox", "none", "--attempts", "2"]


def test_full_flow_issue_to_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _setup(tmp_path, monkeypatch, "good")
    assert main(NEW) == EXIT_OK
    out = capsys.readouterr().out
    assert "BUG-001" in out and "Rule: add(a, b) returns a + b." in out
    assert "reproduces" in out
    assert (repo / "calc.py").read_text() == BUGGY  # investigation changed nothing

    assert main(["bug", "approve", "BUG-001"]) == EXIT_OK
    assert (repo / "tests" / "test_bug_001.py").exists()
    assert list((repo / "contracts").glob("0001-*.toml"))

    assert main(FIX) == EXIT_OK
    report = capsys.readouterr().out
    assert "READY" in report
    assert "$0.02" in report  # investigation + one fix run, as reported by the agent
    phases = [e["phase"] for e in _log(tmp_path)]
    assert phases == ["investigate", "fix"]


def test_investigation_that_does_not_reproduce_cannot_be_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path, monkeypatch, "no-repro")
    assert main(NEW) == EXIT_BLOCKED
    assert "does not reproduce" in capsys.readouterr().out
    assert main(["bug", "approve", "BUG-001"]) == EXIT_USAGE


def test_investigation_that_changes_code_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path, monkeypatch, "edits-during-investigation")
    assert main(NEW) == EXIT_BLOCKED
    assert "changed the code during investigation" in capsys.readouterr().out
    assert main(["bug", "approve", "BUG-001"]) == EXIT_USAGE


def test_agent_that_edits_the_test_stays_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch, "tamper")
    assert main(NEW) == EXIT_OK
    assert main(["bug", "approve", "BUG-001"]) == EXIT_OK
    assert main(FIX) == EXIT_BLOCKED  # the locked copy still fails


def test_failure_is_fed_back_and_second_attempt_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch, "second-try")
    assert main(NEW) == EXIT_OK
    assert main(["bug", "approve", "BUG-001"]) == EXIT_OK
    assert main(FIX) == EXIT_OK
    fixes = [e for e in _log(tmp_path) if e["phase"] == "fix"]
    assert len(fixes) == 2
    assert "still fails" not in fixes[0]["prompt"]
    assert "still fails" in fixes[1]["prompt"] and "acceptance" in fixes[1]["prompt"]


def test_attempts_are_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch, "lazy")
    assert main(NEW) == EXIT_OK
    assert main(["bug", "approve", "BUG-001"]) == EXIT_OK
    assert main(FIX) == EXIT_BLOCKED
    assert len([e for e in _log(tmp_path) if e["phase"] == "fix"]) == 2


def test_fix_before_approval_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch, "good")
    assert main(NEW) == EXIT_OK
    assert main(FIX) == EXIT_USAGE


def test_default_refuses_to_run_an_agent_without_the_sandbox_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch, "good")
    monkeypatch.setenv("OHX_SRT", str(tmp_path / "no-srt-here"))
    assert main(["bug", "new", "add returns the wrong result"]) == EXIT_USAGE
