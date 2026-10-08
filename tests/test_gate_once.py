"""The gate runs a suite once when the pull request changes no test file (T106,
contracts/0068).

Measured on OpenHarnX's own CI (2026-10-07, run 37633993808): the gate step took 1,675 s,
of which the base's locked tests took about 530 s three times over: at acceptance on the
base (the baseline), against the pull request, and the pull request's own tests. When a
pull request changes nothing under `tests/`, its own tests are the locked tests byte for
byte, so two of those runs gave one answer.

Now, when nothing under `tests/` changed:
- with a mandatory pytest suite in the base's `ohx.toml` that runs all of `tests/`, that
  suite (every test must pass) is the check, and the locked copy and its baseline are not
  run: one run instead of three;
- with the default suites, the pull request's own run of `tests/` is not added beside the
  locked copy: two runs instead of four.
Any change under `tests/`, a `conftest.py` included, or a suite that runs only part of
`tests/`, keeps everything as before. The report says when a run was saved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
SUITE = "from calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
SUITE += "\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"
MANDATORY_SUITE = f"""python = {sys.executable!r}

[[obligations]]
id = "tests"
kind = "regression"
mandatory = true
command = ["{{python}}", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml: str) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(toml)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _pr(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _gate(tmp_path: Path) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)])
    return code, json.loads((out / "report.json").read_text())


def _ids(report: dict[str, Any]) -> set[str]:
    return {o["obligation_id"] for o in report["observations"]}


def test_with_a_mandatory_suite_and_no_test_change_the_suite_runs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, MANDATORY_SUITE)
    _pr(repo, {"calc.py": CALC + "\n\ndef sub(a, b):\n    return a - b\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK
    assert "tests" in _ids(report)
    assert not {i for i in _ids(report) if "locked" in i}
    assert any("ran once" in x for x in report["limitations"])


def test_a_broken_change_is_still_blocked_by_that_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, MANDATORY_SUITE)
    _pr(repo, {"calc.py": CALC.replace("a * b", "a + b")})
    code, report = _gate(tmp_path)
    assert code != EXIT_OK
    failing = [o["obligation_id"] for o in report["gate"]["obligations"] if o["status"] != "pass"]
    assert "tests" in failing


def test_with_the_default_suites_the_duplicate_own_run_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, f"python = {sys.executable!r}\n")
    _pr(repo, {"calc.py": CALC + "\n\nX = 1\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK
    assert "locked-tests" in _ids(report) and "tests" not in _ids(report)
    assert any("ran once" in x for x in report["limitations"])


def test_a_default_suite_change_that_breaks_a_test_is_still_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, f"python = {sys.executable!r}\n")
    _pr(repo, {"calc.py": CALC.replace("a * b", "a + b")})
    code, report = _gate(tmp_path)
    assert code != EXIT_OK and report["readiness"] == "blocked"


@pytest.mark.parametrize(
    "files",
    [
        {"tests/test_calc.py": SUITE + "\n\ndef test_more():\n    assert True\n"},
        {"tests/conftest.py": "import pytest\n"},
        {"tests/data/sample.txt": "x\n"},
    ],
    ids=["a test edited", "a conftest added", "test data added"],
)
def test_any_change_under_tests_keeps_every_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]
) -> None:
    repo = _repo(tmp_path, monkeypatch, MANDATORY_SUITE)
    _pr(repo, files)
    _, report = _gate(tmp_path)
    assert "locked-tests" in _ids(report)
    assert not any("ran once" in x for x in report["limitations"])


def test_a_suite_that_runs_only_part_of_tests_keeps_the_locked_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = MANDATORY_SUITE.replace('"no:cacheprovider"]', '"no:cacheprovider", "tests/unit"]')
    repo = _repo(tmp_path, monkeypatch, toml)
    (repo / "tests" / "unit").mkdir()
    (repo / "tests" / "unit" / "test_u.py").write_text("def test_u():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unit tests")
    _git(repo, "branch", "-f", "main")
    _pr(repo, {"calc.py": CALC + "\n\nX = 1\n"})
    _, report = _gate(tmp_path)
    assert "locked-tests" in _ids(report)


def test_an_advisory_suite_does_not_replace_the_locked_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(
        tmp_path, monkeypatch, MANDATORY_SUITE.replace("mandatory = true", "mandatory = false")
    )
    _pr(repo, {"calc.py": CALC + "\n\nX = 1\n"})
    _, report = _gate(tmp_path)
    assert "locked-tests" in _ids(report)


def test_without_any_test_suite_the_locked_copy_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = f'python = {sys.executable!r}\n\n[[obligations]]\nid = "lint"\nkind = "check"\n'
    toml += f'mandatory = true\ncommand = [{sys.executable!r}, "-c", "pass"]\n'
    repo = _repo(tmp_path, monkeypatch, toml)
    _pr(repo, {"calc.py": CALC + "\n\nX = 1\n"})
    _, report = _gate(tmp_path)
    assert "locked-tests" in _ids(report)
