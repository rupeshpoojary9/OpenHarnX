"""Acceptance tests for `ohx gate`, the CI mode (T79 slice 1, contracts/0021).

In CI the base branch is the contract (owner decision 2026-10-03): the pull
request is judged against the base commit's own tests, policy (`ohx.toml`) and
check configuration, never against anything the pull request brings. The base
tests run as locked copies against the pull request's code; a test that passed
on the base must still pass; the pull request's own tests must pass; weakening
is judged against the base. No model calls, a throwaway evidence store, and the
report written to files and to the CI job summary.

Also RC-30 of the release criteria: a candidate changed during verification
invalidates the run. Self-contained; runs without the sandbox for speed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
SUITE = """\
from calc import add, mul


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(2, 3) == 6
"""


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
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _pr(repo: Path, files: dict[str, str], commit: bool = True) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if commit:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "change")


def _gate(tmp_path: Path, *extra: str) -> tuple[int, dict[str, object]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out), *extra])
    return code, json.loads((out / "report.json").read_text())


def _failing(report: dict[str, object]) -> list[str]:
    gate = report["gate"]
    assert isinstance(gate, dict)
    return [o["obligation_id"] for o in gate["obligations"] if o["status"] != "pass"]


def test_genuine_change_with_a_new_test_passes(repo: Path, tmp_path: Path) -> None:
    calc = CALC + "\n\ndef sub(a, b):\n    return a - b\n"
    test = "from calc import sub\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"
    _pr(repo, {"calc.py": calc, "tests/test_sub.py": test})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK, _failing(report)
    assert report["readiness"] == "no-regressions"  # no acceptance tests in a plain gate (T91)


def test_editing_a_test_to_match_broken_code_is_blocked(repo: Path, tmp_path: Path) -> None:
    _pr(
        repo,
        {
            "calc.py": CALC.replace("a * b", "a * b + 1"),
            "tests/test_calc.py": SUITE.replace("mul(2, 3) == 6", "mul(2, 3) == 7"),
        },
    )
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert any("locked" in o for o in _failing(report)) or "no-new-failures" in " ".join(
        _failing(report)
    )


def test_a_new_skip_marker_is_blocked(repo: Path, tmp_path: Path) -> None:
    skipped = SUITE.replace("def test_mul", "import pytest\n\n\n@pytest.mark.skip\ndef test_mul")
    _pr(repo, {"calc.py": CALC.replace("a * b", "a + b"), "tests/test_calc.py": skipped})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "weakening" in _failing(report)


def test_loosened_check_configuration_is_blocked(repo: Path, tmp_path: Path) -> None:
    _pr(repo, {"pyproject.toml": '[tool.ruff.lint]\nignore = ["E", "F"]\n'})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "weakening" in _failing(report)


def test_deleting_a_test_is_blocked(repo: Path, tmp_path: Path) -> None:
    _pr(repo, {"tests/test_calc.py": SUITE.split("\n\n\ndef test_mul")[0] + "\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED


def test_policy_and_contract_changes_in_the_pull_request_have_no_effect(
    repo: Path, tmp_path: Path
) -> None:
    broken = CALC.replace("a * b", "a * b + 1")
    lax = (
        f'python = {sys.executable!r}\n\n[[obligations]]\nid = "tests"\nkind = "regression"\n'
        'mandatory = false\ncommand = ["true"]\n'
    )
    contract = (
        'title = "anything"\nmode = "task"\nchange_summary = "x"\n\n'
        '[[obligations]]\nid = "ok"\nkind = "check"\nmandatory = true\ncommand = ["true"]\n'
    )
    _pr(repo, {"calc.py": broken, "ohx.toml": lax, "contracts/0001-anything.toml": contract})
    code, _ = _gate(tmp_path)
    assert code == EXIT_BLOCKED


def test_a_failure_already_on_the_base_does_not_block(repo: Path, tmp_path: Path) -> None:
    _git(repo, "checkout", "-q", "main")
    _pr(repo, {"tests/test_known.py": "def test_known_broken():\n    assert 0.1 + 0.2 == 0.3\n"})
    _git(repo, "checkout", "-q", "pr")
    _git(repo, "merge", "-q", "main")
    _pr(repo, {"calc.py": CALC + "\n# a comment\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK, _failing(report)


def test_report_is_bound_to_base_and_head_and_goes_to_the_job_summary(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _pr(repo, {"calc.py": CALC + "\n# a comment\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK
    ci = report["ci"]
    assert isinstance(ci, dict)
    assert ci["base_commit"] == _git(repo, "rev-parse", "main")
    assert ci["head_commit"] == _git(repo, "rev-parse", "HEAD")
    assert (tmp_path / "gate-out" / "report.md").read_text().startswith("# OpenHarnX report")
    assert "OpenHarnX report: NO REGRESSIONS" in summary.read_text()


def test_the_gate_leaves_the_repository_untouched(repo: Path, tmp_path: Path) -> None:
    _pr(repo, {"calc.py": CALC + "\n# a comment\n"})
    before = (_git(repo, "status", "--porcelain"), _git(repo, "worktree", "list"))
    _gate(tmp_path)
    assert (_git(repo, "status", "--porcelain"), _git(repo, "worktree", "list")) == before


def test_the_gate_never_starts_an_agent(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "agent-ran"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(f"#!/bin/sh\ntouch {marker}\n")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin")
    _pr(repo, {"calc.py": CALC + "\n# a comment\n"})
    _gate(tmp_path)
    assert not marker.exists()


def test_a_candidate_changed_during_verification_is_invalid(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RC-30: a checker that writes into the candidate invalidates every result of the run."""
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(SUITE)
    (repo / "ohx.toml").write_text(
        f'python = {sys.executable!r}\n\n[[obligations]]\nid = "meddle"\nkind = "check"\n'
        'mandatory = true\ncommand = ["/bin/sh", "-c", "echo x > meddled.txt"]\n'
    )
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "t", "--summary", "s", "--sandbox", "none"]
    assert main([*new, "--acceptance", str(acceptance), "--accept"]) == EXIT_OK
    capsys.readouterr()
    assert main(["verify", "--sandbox", "none", "--json"]) == EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["candidate"]["changed_during_verification"] is True
    assert {o["outcome"] for o in report["observations"]} == {"invalid"}
