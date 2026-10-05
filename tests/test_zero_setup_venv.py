"""Zero setup finds the project's environment and says why a suite cannot run (T94,
contracts/0052).

Found by two simulated users (2026-10-05, python-humanize and jaraco/inflect): in a
project with its own virtual environment and no ohx.toml, checks ran with the
interpreter OpenHarnX itself is installed with, which has no pytest. `ohx init
--lock-tests` said "locked the existing tests" and exited 0 while its baseline had
crashed, and `ohx verify` gave UNKNOWN with "crash" as the only reason. The `python`
key that fixes it was documented nowhere.

Now, with no `python` in ohx.toml, the checkers use the project's `.venv` (or `venv`),
else the active virtual environment, else OpenHarnX's own interpreter. A suite that
cannot run when it is locked because the interpreter lacks the checker or a dependency
makes `ohx init --lock-tests` exit 10 with the checker's own error and what to set; one
whose own tests cannot be collected yet (they import code the task will add, T89) is
locked with a warning. A check that crashes says why in its note.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _interpreter(path: Path, *flags: str) -> Path:
    """A stand-in for a virtual environment's python: runs this test's interpreter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec {sys.executable} {" ".join(flags)} "$@"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / ".gitignore").write_text(".venv/\nvenv/\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _contract_python(tmp_path: Path) -> str:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return " ".join(report["limitations"])


@pytest.mark.parametrize("folder", [".venv", "venv"])
def test_the_projects_own_virtual_environment_is_used(
    repo: Path, tmp_path: Path, folder: str
) -> None:
    _interpreter(repo / folder / "bin" / "python")
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert f"{folder}/bin/python" in _contract_python(tmp_path)


def test_the_active_virtual_environment_is_used(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = _interpreter(tmp_path / "elsewhere-env" / "bin" / "python")
    monkeypatch.setenv("VIRTUAL_ENV", str(active.parent.parent))
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    runs = sorted((tmp_path / "home").glob("projects/*/runs/*/report.json"))
    report = json.loads(runs[-1].read_text())
    assert any(str(active) in o["argv"][0] for o in report["observations"] if o["argv"])


def test_an_explicit_python_in_ohx_toml_still_wins(repo: Path, tmp_path: Path) -> None:
    _interpreter(repo / ".venv" / "bin" / "python", "-S")  # this one cannot import pytest
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "add", "ohx.toml")
    _git(repo, "commit", "-qm", "ohx.toml")
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_a_suite_that_cannot_run_when_locked_fails_loudly_with_the_cause(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _interpreter(repo / ".venv" / "bin" / "python", "-S")  # no site-packages: no pytest
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_BLOCKED
    out = capsys.readouterr()
    text = out.out + out.err
    assert "could not run" in text and "pytest" in text and "is not installed" in text
    assert "python =" in text  # what to set in ohx.toml


def test_a_crashed_check_says_why(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _interpreter(repo / ".venv" / "bin" / "python", "-S")
    main(["init", "--lock-tests", "--sandbox", "none"])
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    runs = sorted((tmp_path / "home").glob("projects/*/runs/*/report.json"))
    report = json.loads(runs[-1].read_text())
    crashed = [o for o in report["observations"] if o["outcome"] == "crash"]
    assert crashed and all("is not installed" in o["note"] for o in crashed)
    assert "is not installed" in (runs[-1].parent / "report.md").read_text()


def test_without_any_environment_the_tool_interpreter_is_used_as_before(
    repo: Path, tmp_path: Path
) -> None:
    assert os.environ.get("VIRTUAL_ENV") is None
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_tests_that_import_code_not_written_yet_are_locked_with_a_warning(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = "from calc import sub\n\n\ndef test_sub():\n    pass\n"
    (repo / "tests" / "test_new.py").write_text(new)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a test for code the task will add")
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    err = capsys.readouterr().err
    assert "could not run" in err and "locked anyway" in err


def test_a_contract_made_with_contract_new_uses_the_projects_environment(
    repo: Path, tmp_path: Path
) -> None:
    venv = _interpreter(repo / ".venv" / "bin" / "python")
    (repo / "acceptance").mkdir()
    (repo / "acceptance" / "test_a.py").write_text(SUITE)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    assert (
        main([*args, "--acceptance", "acceptance/test_a.py", "--accept", "--sandbox", "none"]) == 0
    )
    written = next((repo / "contracts").glob("*.toml")).read_text()
    assert f"python = {str(venv)!r}".replace("'", '"') in written


def test_a_passing_check_gets_no_cause(repo: Path, tmp_path: Path) -> None:
    _interpreter(repo / ".venv" / "bin" / "python")
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    runs = sorted((tmp_path / "home").glob("projects/*/runs/*/report.json"))
    report = json.loads(runs[-1].read_text())
    locked = next(o for o in report["observations"] if o["obligation_id"] == "locked-tests")
    assert locked["outcome"] == "pass" and locked["note"] == ""


def test_the_cause_is_the_line_that_names_the_error() -> None:
    from openharnx.app import _cause

    output = b"collecting ...\nE   ImportError: cannot import name 'sub'\n1 error in 0.02s\n"
    assert _cause(output) == "E   ImportError: cannot import name 'sub'"
    assert _cause(b"just one line\n") == "just one line"
    assert _cause(b"") == ""
