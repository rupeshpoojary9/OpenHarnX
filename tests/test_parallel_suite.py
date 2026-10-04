"""Acceptance tests for running a locked Python suite in parallel (T80 slice 3, contracts/0035).

Measured 2026-10-04: OpenHarnX's own overhead in a verification is under a second; the
time is the project's test suite, run on one core. `pytest_args` in `ohx.toml` adds the
project's own pytest options (for example pytest-xdist's `-n auto`) to the locked run and
to the default `tests` run. It is check configuration, so it comes from the locked
`ohx.toml` like `js_runner`, and per-test results still decide the verdict.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main

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


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "tests" / "test_more.py").write_text(
        "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 4) == 4\n"
    )
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n{extra}")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    return repo


def _report(tmp_path: Path) -> dict[str, Any]:
    reports = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    return json.loads(reports[-1].read_text())  # type: ignore[no-any-return]


def _python_runs(report: dict[str, Any]) -> dict[str, list[str]]:
    return {
        o["obligation_id"]: o["argv"]
        for o in report["observations"]
        if o["obligation_id"] in ("locked-tests", "tests")
    }


def test_the_locked_suite_runs_with_the_projects_pytest_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _project(tmp_path, monkeypatch, 'pytest_args = ["-n", "2"]\n')
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    runs = _python_runs(_report(tmp_path))
    assert set(runs) == {"locked-tests", "tests"}
    for argv in runs.values():
        assert argv[argv.index("-n") + 1] == "2"


def test_per_test_results_still_decide_when_the_suite_runs_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _project(tmp_path, monkeypatch, 'pytest_args = ["-n", "2"]\n')
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 7"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    notes = " ".join(o["note"] for o in _report(tmp_path)["observations"])
    assert "test_mul" in notes  # named per test, not as a whole failing suite
    assert "test_add_zero" not in notes


def test_pytest_options_must_be_a_list_of_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _project(tmp_path, monkeypatch, 'pytest_args = "-n 2"\n')
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_USAGE
    assert "pytest_args" in capsys.readouterr().err


def test_changing_the_pytest_options_after_locking_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _project(tmp_path, monkeypatch, 'pytest_args = ["-n", "2"]\n')
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "ohx.toml").write_text(
        f'python = {sys.executable!r}\npytest_args = ["-n", "2", "--deselect", '
        '"tests/test_calc.py::test_mul"]\n'
    )
    (repo / "calc.py").write_text(CALC.replace("a * b", "a + b"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
