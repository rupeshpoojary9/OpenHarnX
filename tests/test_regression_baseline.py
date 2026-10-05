"""Acceptance tests for the regression baseline (T87 item 1, contracts/0015).

From the owner's real `ohx bug` run (2026-10-03): the project's own test suite
was advisory (`tests | Mandatory: no`), so an agent that fixed the bug and
broke other tests still got READY. It was advisory because a suite with
failures that were already there would otherwise block every change.

At acceptance OpenHarnX records which tests pass. At verification a mandatory
built-in check, `no-new-failures`, blocks when a test that passed at
acceptance fails, is skipped or no longer runs. Failures that were already
there are reported, not blocking. Without per-test results it compares the
whole suite, and when that was already failing the result is unknown, never a
pass. Self-contained.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = """\
def add(a, b):
    return a + b


def mul(a, b):
    return a * b


def sub(a, b):
    return a + b  # the bug
"""

SUITE = """\
from calc import add, mul


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(2, 3) == 6


def test_known_broken():
    assert add(0.1, 0.2) == 0.3  # failing before this change, and not its concern
"""

ACCEPTANCE = "from calc import sub\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ohx_toml: str = "") -> Path:
    acceptance = tmp_path / "outside" / "test_sub.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n{ohx_toml}")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix sub", "--summary", "sub subtracts"]
    assert main([*new, "--acceptance", str(acceptance), "--accept", "--sandbox", "none"]) == 0
    return repo


def _fix_sub(repo: Path, calc: str = CALC) -> None:
    (repo / "calc.py").write_text(calc.replace("return a + b  # the bug", "return a - b"))


def _verify(capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, dict[str, Any]]]:
    code = main(["verify", "--sandbox", "none"])
    capsys.readouterr()
    main(["report", "--json"])
    report = json.loads(capsys.readouterr().out)
    gate = {o["obligation_id"]: o for o in report["gate"]["obligations"]}
    notes = {o["obligation_id"]: o for o in report["observations"]}
    return code, {k: {**gate[k], "note": notes[k]["note"]} for k in gate}


def test_regression_check_is_mandatory_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    _fix_sub(repo)
    _, obligations = _verify(capsys)
    assert obligations["no-new-failures-tests"]["mandatory"] is True


def test_fix_with_a_failure_that_was_already_there_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    _fix_sub(repo)
    code, obligations = _verify(capsys)
    assert code == EXIT_OK
    check = obligations["no-new-failures-tests"]
    assert check["status"] == "pass"
    assert "test_known_broken" in str(check["note"])  # reported, not blocking


def test_fix_that_breaks_another_test_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    _fix_sub(repo, CALC.replace("return a * b", "return a * b + 1"))
    code, obligations = _verify(capsys)
    assert code == EXIT_BLOCKED
    check = obligations["no-new-failures-tests"]
    assert check["status"] == "fail"
    assert "test_mul" in " ".join(map(str, check["reasons"]))
    assert "test_add" not in " ".join(map(str, check["reasons"]))


def test_test_that_no_longer_runs_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    _fix_sub(repo)
    suite = repo / "tests" / "test_calc.py"
    suite.write_text(suite.read_text().replace("def test_mul", "def helper_mul"))
    code, obligations = _verify(capsys)
    assert code == EXIT_BLOCKED
    assert obligations["no-new-failures-tests"]["status"] == "fail"
    assert "test_mul" in " ".join(map(str, obligations["no-new-failures-tests"]["reasons"]))


def test_without_per_test_results_a_suite_failing_before_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    suite = (
        '\n[[obligations]]\nid = "suite"\nkind = "regression"\nmandatory = false\n'
        'command = ["/bin/sh", "-c", "exit 1"]\n'
    )
    repo = _make(tmp_path, monkeypatch, suite)
    _fix_sub(repo)
    code, obligations = _verify(capsys)
    assert code == EXIT_BLOCKED  # unknown is never a pass
    assert obligations["no-new-failures"]["status"] == "unknown"


def test_mandatory_suite_needs_no_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    suite = (
        '\n[[obligations]]\nid = "suite"\nkind = "regression"\nmandatory = true\n'
        f'command = ["{sys.executable}", "-m", "pytest", "-q", "-p", "no:cacheprovider",'
        ' "tests/test_calc.py::test_add"]\n'
    )
    repo = _make(tmp_path, monkeypatch, suite)
    _fix_sub(repo)
    code, obligations = _verify(capsys)
    assert code == EXIT_OK
    assert "no-new-failures" not in obligations  # every failure already blocks
