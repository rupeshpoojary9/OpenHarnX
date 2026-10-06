"""The advisory mutation check spends its time where it can find something (T97,
contracts/0055).

OpenHarnX's own T96 verification spent 497 of 637 seconds on the mutation check, and all
ten mutants were in a file no acceptance test imported, so none could have failed a test.
Every repair round paid that again.

Now mutants are made only in changed files the acceptance tests imported (when the run
recorded its imports), and no mutant starts once the time budget would run out: 120
seconds unless `mutation_budget_s` in ohx.toml says otherwise. The note says which files
were not mutated and how many mutants did not run. The check stays advisory; the verdict
does not change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def half(a):\n    return a\n\n\ndef third(a):\n    return a\n"
FIXED = "def half(a):\n    return a / 2\n\n\ndef third(a):\n    return a / 3\n"
OTHER = "def scale(a):\n    return a\n"
OTHER_CHANGED = "def scale(a):\n    return a * 2 + 1 - 3\n"
ACCEPTANCE = """\
import time

from calc import half, third


def test_half():
    time.sleep(SLEEP)
    assert half(10) == 5


def test_third():
    assert third(9) == 3
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleep: float, toml: str = "") -> Path:
    repo = tmp_path / "proj"
    (repo / "acceptance").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "other.py").write_text(OTHER)
    (repo / "acceptance" / "test_calc.py").write_text(ACCEPTANCE.replace("SLEEP", str(sleep)))
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\nobligations = []\n{toml}")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_calc.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    return repo


def _verify(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    mutation = next(o for o in report["observations"] if o["obligation_id"] == "mutation")
    return report, mutation


def test_files_no_acceptance_test_imported_are_not_mutated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=0)
    (repo / "calc.py").write_text(FIXED)
    (repo / "other.py").write_text(OTHER_CHANGED)
    report, mutation = _verify(tmp_path)
    assert report["readiness"] == "ready"
    assert mutation["outcome"] == "pass", mutation["note"]
    assert "not exercised" not in mutation["note"]
    assert "other.py" in mutation["note"] and "no acceptance test imported" in mutation["note"]
    output = (tmp_path / "home").glob("projects/*/runs/*/evidence/mutation.txt")
    text = max(output, key=lambda p: p.stat().st_mtime).read_text()
    assert "calc.py" in text and "other.py" not in text


def test_only_unimported_files_changed_runs_no_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=0)
    (repo / "calc.py").write_text(FIXED)
    _git(repo, "commit", "-qam", "the fix, already committed")
    (repo / "other.py").write_text(OTHER_CHANGED)
    _, mutation = _verify(tmp_path)
    assert mutation["outcome"] == "unavailable"
    assert "other.py" in mutation["note"] and "no acceptance test imported" in mutation["note"]
    assert mutation["duration_ms"] < 5000  # no acceptance run was spent on it


def test_no_mutant_starts_once_the_budget_would_run_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=1, toml="mutation_budget_s = 3\n")
    (repo / "calc.py").write_text(FIXED)
    report, mutation = _verify(tmp_path)
    assert report["readiness"] == "ready"  # advisory: the verdict does not change
    note = mutation["note"]
    assert "the time budget of 3 s" in note and "mutation_budget_s" in note
    # How many mutants fit in 3 s depends on the machine: on a slow CI runner one
    # acceptance run alone takes longer, and none starts (2026-10-06, run 37484375324).
    assert "not run" in note or "no mutant ran" in note
    assert mutation["duration_ms"] < 8000


def test_a_budget_smaller_than_one_acceptance_run_runs_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=2, toml="mutation_budget_s = 1\n")
    (repo / "calc.py").write_text(FIXED)
    report, mutation = _verify(tmp_path)
    assert report["readiness"] == "ready"
    assert mutation["outcome"] == "unavailable"
    assert "the time budget of 1 s" in mutation["note"]


def test_the_budget_is_part_of_the_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=0, toml="mutation_budget_s = 30\n")
    written = next((repo / "contracts").glob("*.toml")).read_text()
    assert "mutation_budget_s = 30" in written


def test_a_budget_that_is_not_a_positive_number_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(AssertionError):
        _repo(tmp_path, monkeypatch, sleep=0, toml='mutation_budget_s = "fast"\n')


def test_the_default_budget_keeps_small_projects_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, sleep=0)
    (repo / "calc.py").write_text(FIXED)
    _, mutation = _verify(tmp_path)
    assert mutation["outcome"] == "pass"
    assert "not run" not in mutation["note"]


def test_without_import_records_every_changed_file_is_still_mutated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code in a folder that is not a package is not tracked by the import record, so
    nothing is filtered: the check mutates and runs as it did before T97."""
    repo = tmp_path / "proj"
    (repo / "lib").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "lib" / "calc.py").write_text(CALC)
    (repo / "acceptance" / "test_calc.py").write_text(
        "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path.cwd() / 'lib'))\n\n"
        + ACCEPTANCE.replace("SLEEP", "0")
    )
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\nobligations = []\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_calc.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    (repo / "lib" / "calc.py").write_text(FIXED)
    report, mutation = _verify(tmp_path)
    assert not any(k.startswith("acceptance") for k in report["imported"])  # nothing recorded
    assert mutation["outcome"] == "pass", mutation["note"]
    assert "killed" in mutation["note"] and "not mutated" not in mutation["note"]
