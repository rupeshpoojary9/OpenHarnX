"""A suite that cannot run at acceptance can still reach READY once fixed (contracts/0040).

Found by replaying the public impossible-tasks dataset (2026-10-04): the tests import a
function that does not exist yet, so at acceptance the suite crashes during collection
and no per-test baseline exists. The no-new-failures check then stayed unavailable for
ever, and a correct fix could never be READY. Nothing passed at acceptance, so nothing can
regress: a run that passes, ran at least one test and in which every test passed is
enough. Anything less (a failure, a skip, a crash, no tests) stays not ready.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.regression import compare

STRINGS = 'def slugify(text):\n    return text.strip().lower().replace(" ", "-")\n'
SUITE = """\
from strings import slugify, titlecase


def test_slugify():
    assert slugify(" Hello World ") == "hello-world"


def test_titlecase():
    assert titlecase("hello world") == "Hello World"
"""
TITLECASE = (
    '\n\ndef titlecase(text):\n    return " ".join(w.capitalize() for w in text.split(" "))\n'
)


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
    (repo / "strings.py").write_text(STRINGS)
    (repo / "tests" / "test_strings.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    return repo


def _contract(mode: str) -> None:
    if mode == "locked suite":
        assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    else:
        assert main(["init"]) == EXIT_OK
        args = ["contract", "new", "--mode", "task", "--title", "Add titlecase"]
        args += ["--summary", "s", "--acceptance", "tests", "--accept", "--sandbox", "none"]
        assert main(args) == EXIT_OK


@pytest.mark.parametrize("mode", ["locked suite", "acceptance contract"])
def test_implementing_the_missing_function_is_ready(repo: Path, mode: str) -> None:
    _contract(mode)
    (repo / "strings.py").write_text(STRINGS + TITLECASE)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


@pytest.mark.parametrize("mode", ["locked suite", "acceptance contract"])
def test_a_wrong_implementation_is_not_ready(repo: Path, mode: str) -> None:
    _contract(mode)
    (repo / "strings.py").write_text(STRINGS + TITLECASE.replace("capitalize()", "upper()"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK


@pytest.mark.parametrize("mode", ["locked suite", "acceptance contract"])
def test_a_suite_that_still_crashes_is_not_ready(repo: Path, mode: str) -> None:
    _contract(mode)
    (repo / "strings.py").write_text(STRINGS + "\n\ndef title_case(text):\n    return text\n")
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK


def test_without_a_baseline_only_a_full_pass_counts() -> None:
    crashed = {"outcome": "crash", "tests": None}
    assert compare(crashed, "pass", {"a": "pass", "b": "pass"})[0] == "pass"
    assert compare(crashed, "pass", {"a": "pass", "b": "skip"})[0] == "unavailable"
    assert compare(crashed, "fail", {"a": "pass", "b": "fail"})[0] == "unavailable"
    assert compare(crashed, "pass", {})[0] == "unavailable"
    assert compare(crashed, "pass", None)[0] == "unavailable"
    assert compare(crashed, "crash", None)[0] == "unavailable"
    nothing_ran = {"outcome": "pass", "tests": {}}
    assert compare(nothing_ran, "pass", {"a": "pass"})[0] == "pass"
    assert compare(nothing_ran, "pass", {})[0] == "unavailable"
