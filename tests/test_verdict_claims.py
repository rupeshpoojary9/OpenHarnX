"""The verdict says what the evidence supports: READY or NO REGRESSIONS (T91,
contracts/0046).

External review (2026-10-04): in the impossible-tasks replay, 10 of 12 honest runs that
left the task unsolved were READY in zero setup, because nothing that passed before
broke. Readers take READY as "the work is done". Owner decision (2026-10-04): separate
them. READY now needs acceptance criteria: every mandatory check passed and the
contract has at least one mandatory acceptance check. With every mandatory check
passing and no acceptance check (zero setup, a gate without a contract) the verdict is
NO REGRESSIONS: nothing that passed before broke; whether the task is done is not
known. Both exit 0, so CI and the Stop hook still let the work through, and the
report states each claim: no regressions, acceptance (met, none defined, not met),
and the tests that still fail.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.app.hook import claude_stop
from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
SUITE = """\
from calc import add, half


def test_add():
    assert add(2, 3) == 5


def test_half():
    assert half(4) == 2
"""
FIXED = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a / 2\n"
ACCEPTANCE = "from calc import half\n\n\ndef test_half_of_ten():\n    assert half(10) == 5\n"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _report(tmp_path: Path) -> tuple[dict[str, Any], str]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    return json.loads(runs[-1].read_text()), (runs[-1].parent / "report.md").read_text()


def test_zero_setup_with_the_task_unsolved_is_no_regressions_not_ready(
    repo: Path, tmp_path: Path
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "notes.txt").write_text("looked at it\n")  # nothing fixed, nothing broken
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["readiness"] == "no-regressions"
    claims = report["claims"]
    assert claims["no_regressions"] is True
    assert claims["acceptance"] == "none defined"
    assert any("test_half" in t for t in claims["still_failing"])
    assert markdown.startswith("# OpenHarnX report: NO REGRESSIONS")
    assert "no acceptance" in markdown.lower() and "still fail" in markdown.lower()


def test_zero_setup_with_the_task_solved_is_still_no_regressions(
    repo: Path, tmp_path: Path
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _ = _report(tmp_path)
    assert report["readiness"] == "no-regressions"  # no acceptance criteria were agreed
    assert report["claims"]["still_failing"] == []


def _acceptance_contract(repo: Path) -> None:
    (repo / "acceptance").mkdir()
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK


def test_acceptance_criteria_met_is_ready(repo: Path, tmp_path: Path) -> None:
    _acceptance_contract(repo)
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["readiness"] == "ready"
    assert report["claims"]["acceptance"] == "met"
    assert report["claims"]["no_regressions"] is True
    assert markdown.startswith("# OpenHarnX report: READY")


def test_acceptance_criteria_not_met_is_blocked(repo: Path, tmp_path: Path) -> None:
    _acceptance_contract(repo)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report, _ = _report(tmp_path)
    assert report["readiness"] == "blocked"
    assert report["claims"]["acceptance"] == "not met"


def test_a_regression_is_blocked_and_says_so(repo: Path, tmp_path: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a + b", "a - b"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report, _ = _report(tmp_path)
    assert report["readiness"] == "blocked"
    assert report["claims"]["no_regressions"] is False


def test_a_gate_without_a_contract_is_no_regressions(repo: Path, tmp_path: Path) -> None:
    _git(repo, "checkout", "-qb", "pr")
    (repo / "calc.py").write_text(FIXED)
    _git(repo, "commit", "-qam", "fix half")
    out = tmp_path / "gate-out"
    assert main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)]) == EXIT_OK
    report = json.loads((out / "report.json").read_text())
    assert report["readiness"] == "no-regressions"


def test_the_stop_hook_lets_the_agent_stop_and_tells_the_user_what_it_means(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "notes.txt").write_text("looked at it\n")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    event = json.dumps({"session_id": "s1", "cwd": str(repo), "stop_hook_active": False})
    answer = claude_stop(event, repo, "none")
    assert "decision" not in answer and "hookSpecificOutput" not in answer  # may stop
    message = answer["systemMessage"]
    assert "NO REGRESSIONS" in message and "not shown to be done" in message


def test_the_action_documents_the_new_verdict() -> None:
    action = (Path.cwd() / "action.yml").read_text()  # the locked copy runs outside the repo
    assert "no-regressions" in action
