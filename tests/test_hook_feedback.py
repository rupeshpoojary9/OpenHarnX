"""The Stop hook tells the person every verdict and gives the agent what it needs to fix
a block (T98, contracts/0056).

Found by two simulated users (2026-10-05, note 21): with `claude -p` the hook's verdict
was invisible, and the report said "Agent work: unknown: no agent run recorded" although
the hook had run in a Claude Code session. A probe on Claude Code 2.1.281 showed that
`--output-format json` carries no hook output at all, while `stream-json` carries a
hook's `systemMessage` as a system message ("Stop says: ..."). On READY the hook said
nothing, and a BLOCKED agent got a 400-character note per failing check.

Now every verdict reaches the person as a one-line `systemMessage` with the path to the
report (READY, NO REGRESSIONS, and each BLOCKED attempt). A BLOCKED agent is told which
agreed tests failed, the error lines from the failing checks' output and where the full
output is, within a bounded length. The report names the Claude Code session that
triggered the verification; its cost stays unknown, since hooks are not given it.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
FIXED = CALC.replace("    return a\n", "    return a / 2\n")
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
ACCEPTANCE = """\
from calc import half


def test_half_of_ten():
    assert half(10) == 5


def test_half_of_zero():
    assert half(0) == 0
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
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho '2.1.281 (Claude Code)'\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    return repo


def _stop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    active: bool = False,
    session: str = "session-1",
) -> dict[str, Any]:
    event = {
        "session_id": session,
        "hook_event_name": "Stop",
        "cwd": str(repo),
        "stop_hook_active": active,
        "transcript_path": "/somewhere/transcript.jsonl",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    capsys.readouterr()
    assert main(["hook", "claude-stop", "--sandbox", "none"]) == EXIT_OK
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else {}


def _sent_back(out: dict[str, Any]) -> str | None:
    if out.get("decision") == "block":
        return str(out["reason"])
    feedback = out.get("hookSpecificOutput", {})
    return str(feedback["additionalContext"]) if feedback.get("additionalContext") else None


def _latest(tmp_path: Path) -> dict[str, Any]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return report


def test_ready_is_told_to_the_person_with_the_report(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "calc.py").write_text(FIXED)
    out = _stop(monkeypatch, capsys, repo)
    assert _sent_back(out) is None  # the agent may stop
    message = out["systemMessage"]
    assert message.startswith("OpenHarnX: READY")
    path = re.search(r"(/\S+report\.md)", message)
    assert path and Path(path.group(1)).is_file()


def test_each_blocked_attempt_is_told_to_the_person_too(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _stop(monkeypatch, capsys, repo)
    assert _sent_back(out) is not None
    assert "BLOCKED" in out["systemMessage"] and "attempt 1 of 3" in out["systemMessage"]
    assert "sent back to the agent" in out["systemMessage"]
    out = _stop(monkeypatch, capsys, repo, active=True)
    assert "attempt 2 of 3" in out["systemMessage"]


def test_the_agent_is_told_which_agreed_tests_failed_and_why(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "calc.py").write_text(CALC.replace("    return a\n", "    return a // 2 + (a == 0)\n"))
    reason = _sent_back(_stop(monkeypatch, capsys, repo))
    assert reason is not None
    assert "test_half_of_zero" in reason  # the agreed test that failed
    assert "test_half_of_ten" not in reason  # not the one that passed
    assert "assert 1 == 0" in reason  # the error line from the output
    assert "locked" in reason


def test_the_agent_is_told_where_the_full_output_is(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reason = _sent_back(_stop(monkeypatch, capsys, repo))
    assert reason is not None
    paths = re.findall(r"(/\S+\.txt)", reason)
    assert paths and all(Path(p).is_file() for p in paths)
    assert any("test_half_of_ten" in Path(p).read_text() for p in paths)


def test_a_broken_existing_test_is_named_with_its_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    reason = _sent_back(_stop(monkeypatch, capsys, repo))
    assert reason is not None
    assert "test_add" in reason and "assert -1 == 5" in reason


def test_the_feedback_stays_bounded(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    noisy = "".join(
        f"\n\ndef test_noise_{i}():\n    assert 'x' * 300 == 'y' * 300\n" for i in range(60)
    )
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE + noisy)
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    reason = _sent_back(_stop(monkeypatch, capsys, repo))
    assert reason is not None
    assert len(reason) <= 6000
    assert "more" in reason  # says that it left some out


def test_the_report_names_the_agent_session_and_keeps_its_cost_unknown(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "calc.py").write_text(FIXED)
    _stop(monkeypatch, capsys, repo, session="abc-123")
    report = _latest(tmp_path)
    assert report["agent"] == {"tool": "claude-code", "session": "abc-123"}
    work = report["cost"]["agent_work"]
    assert work.startswith("unknown") and "abc-123" in work
    assert "total_cost_usd" in work  # where the cost can be read instead


def test_verify_without_the_hook_names_no_agent(repo: Path, tmp_path: Path) -> None:
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report = _latest(tmp_path)
    assert "agent" not in report
    assert report["cost"]["agent_work"] == "unknown: no agent run recorded"


def test_with_one_regression_suite_the_agent_still_gets_its_error_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Found in review (2026-10-06): with exactly one regression suite the comparison is
    named plain `no-new-failures`, and the hook read that check's own output (only its
    note) instead of the suite's, so the agent got no assertion lines. The suite is now
    found through the comparison's recorded `of`, not by parsing its id."""
    repo = tmp_path / "single"
    (repo / "tests").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    suite = '["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]'
    (repo / "ohx.toml").write_text(
        f'python = {sys.executable!r}\n\n[[obligations]]\nid = "suite"\n'
        f'kind = "regression"\nmandatory = false\ncommand = {suite}\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho '2.1.281 (Claude Code)'\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    reason = _sent_back(_stop(monkeypatch, capsys, repo))
    assert reason is not None
    report = _latest(tmp_path)
    assert report["compares"] == {"no-new-failures": "suite"}
    assert "- no-new-failures:" in reason
    assert "assert -1 == 5" in reason  # the suite's own error line, not the note again
    full = re.findall(r"Full output: (\S+)", reason)
    assert any(p.endswith("evidence/suite.txt") for p in full)
    markdown = next(Path(p).parent.parent / "report.md" for p in full)
    assert "every test in `suite` that passed before passes" not in markdown.read_text()
    assert "`no-new-failures` (built-in, mandatory)" not in _verified(markdown.read_text())


def _verified(markdown: str) -> str:
    start = markdown.index("## What was verified")
    return markdown[start : markdown.index("\n## ", start + 1)]


def test_the_brief_names_the_one_suite_a_passing_comparison_covered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from openharnx.report import render_markdown

    report = {
        "readiness": "ready",
        "claims": None,
        "contract": {"title": "t", "revision_id": "r"},
        "candidate": {"digest": "sha256:x", "base_commit": "b",
                      "changed_during_verification": False, "changed_paths": []},
        "gate": {
            "result": "pass",
            "coverage_percent": 100,
            "obligations": [
                {"obligation_id": "no-new-failures", "mandatory": True, "status": "pass",
                 "reasons": []},
            ],
        },
        "observations": [{"obligation_id": "no-new-failures", "note": "", "argv": None}],
        "compares": {"no-new-failures": "suite"},
        "protection": {"verifier": "enforced"},
        "cost": {"agent_work": "unknown", "overhead": {"model_calls": 0, "verifier_ms": 0}},
        "changelog_entry": "- s",
        "limitations": [],
        "authorizes": "nothing",
    }  # fmt: skip
    assert "every test in `suite` that passed before passes" in render_markdown(report)
