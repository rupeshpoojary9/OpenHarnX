"""A test that was failing when locked cannot be edited or removed to get READY (contracts/0041).

Found by replaying the public impossible-tasks dataset (2026-10-04): with
`ohx init --lock-tests`, a test that already failed at locking only had to keep failing.
The locked copy still failed "as before", so an agent that rewrote the test to pass
(changed the expected value, compared the result with itself) or deleted it was READY:
43 of 49 fakes. Now the no-new-failures check on a locked suite compares each test that
was failing at locking with the working tree: changed or removed is a finding. Editing a
test that passed at locking stays harmless (the locked copy still has to pass) and adding
tests needs no approval. If the test itself was wrong, the owner locks again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.regression import edited_tests

MATHS = 'def add(a, b):\n    """Ordinary integer addition."""\n    return a + b\n'
SUITE = """\
from maths import add


def test_add_small():
    assert add(1, 1) == 2


def test_add_pair():
    assert add(2, 2) == 5


class TestMore:
    def test_add_zero(self):
        assert add(0, 3) == 3

    def test_add_negative(self):
        assert add(-1, 1) == 1
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
    (repo / "maths.py").write_text(MATHS)
    (repo / "tests" / "test_maths.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _failing(tmp_path: Path) -> list[str]:
    reports = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(reports[-1].read_text())
    return [o["obligation_id"] for o in report["gate"]["obligations"] if o["status"] != "pass"]


def _notes(tmp_path: Path) -> str:
    reports = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(reports[-1].read_text())
    return " ".join(o["note"] for o in report["observations"])


def _locked(repo: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK


def test_rewriting_a_failing_test_to_pass_is_blocked(repo: Path, tmp_path: Path) -> None:
    _locked(repo)
    (repo / "tests" / "test_maths.py").write_text(SUITE.replace("== 5", "== 4"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    notes = _notes(tmp_path)
    assert "test_add_pair" in notes and "changed" in notes
    assert "no-new-failures-locked-tests" in _failing(tmp_path)  # reported by the locked suite
    assert "lock" in notes  # how to accept it if the test was wrong


def test_comparing_the_result_with_itself_is_blocked(repo: Path) -> None:
    _locked(repo)
    tautology = SUITE.replace("assert add(2, 2) == 5", "assert add(2, 2) == add(2, 2)")
    (repo / "tests" / "test_maths.py").write_text(tautology)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK


def test_a_failing_test_in_a_class_is_covered(repo: Path) -> None:
    _locked(repo)
    (repo / "tests" / "test_maths.py").write_text(SUITE.replace("== 1\n", "== 0\n"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK


def test_deleting_a_failing_test_is_blocked(repo: Path, tmp_path: Path) -> None:
    _locked(repo)
    without = SUITE.replace("def test_add_pair():\n    assert add(2, 2) == 5\n", "")
    (repo / "tests" / "test_maths.py").write_text(without)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    assert "removed" in _notes(tmp_path)


def test_deleting_the_test_file_is_blocked(repo: Path) -> None:
    _locked(repo)
    (repo / "tests" / "test_maths.py").unlink()
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK


def test_adding_a_test_and_leaving_the_failing_one_alone_is_ready(repo: Path) -> None:
    _locked(repo)
    (repo / "maths.py").write_text(MATHS + "\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "tests" / "test_sub.py").write_text(
        "from maths import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_reformatting_or_editing_a_passing_test_is_ready(repo: Path) -> None:
    _locked(repo)
    edited = SUITE.replace("assert add(1, 1) == 2", "result = add(1, 1)\n    assert result == 2")
    edited = edited.replace("assert add(2, 2) == 5", "assert add( 2,2 )==5  # still wrong")
    (repo / "tests" / "test_maths.py").write_text(edited)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_locking_again_accepts_a_deliberate_fix_to_a_wrong_test(repo: Path) -> None:
    _locked(repo)
    (repo / "tests" / "test_maths.py").write_text(SUITE.replace("== 5", "== 4"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    _locked(repo)  # the owner agrees the test was wrong
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_in_ci_a_pull_request_that_rewrites_a_test_failing_on_the_base_is_blocked(
    repo: Path, tmp_path: Path
) -> None:
    _git(repo, "checkout", "-qb", "pr")
    (repo / "tests" / "test_maths.py").write_text(SUITE.replace("== 5", "== 4"))
    _git(repo, "commit", "-qam", "fix the suite")
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert code != EXIT_OK and report["readiness"] != "ready"
    assert "test_add_pair" in " ".join(o["note"] for o in report["observations"])


def test_tests_are_found_by_every_id_shape_pytest_writes(tmp_path: Path) -> None:
    locked, working = tmp_path / "locked", tmp_path / "working"
    for root in (locked, working):
        root.mkdir()
        (root / "test_maths.py").write_text(SUITE)
    (working / "test_maths.py").write_text(
        SUITE.replace("== 5", "== 4").replace("== 1\n", "== 0\n")
    )
    ids = [
        "test_maths::test_add_pair",  # the locked folder run on its own
        "tests.test_maths::test_add_pair",  # run from the repository root
        "tests.test_maths.TestMore::test_add_negative",  # in a class
        "test_maths::test_add_small",  # unchanged
    ]
    found = edited_tests(locked, working, ids)
    assert found == [
        "test_maths::test_add_pair was failing when locked and has been changed",
        "tests.test_maths.TestMore::test_add_negative was failing when locked and has been changed",
        "tests.test_maths::test_add_pair was failing when locked and has been changed",
    ]
