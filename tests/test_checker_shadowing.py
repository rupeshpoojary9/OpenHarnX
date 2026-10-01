"""Acceptance tests for T77 item 1, VERIFY-11 (contracts/0007).

Found by the independent review on `fb39881`: a `pytest.py` in the candidate
replaced the checker and turned BLOCKED into READY, also under srt. Checks run
as `{python} -m <module>` from the candidate, and Python puts that directory
first on `sys.path`, so any file in the candidate could stand in for the
checker or for a module the checker imports.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
FAKE = "raise SystemExit(0)\n"

# Each entry: file written into the candidate that tries to replace the checker.
SHADOWS = {
    "module named like the checker": "pytest.py",
    "package named like the checker": "pytest/__init__.py",
    "module the checker imports": "pluggy.py",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _contract(acceptance: Path, extra: str = "") -> str:
    contracts = acceptance.parent.parent / "proj" / "contracts"
    return (
        'title = "Fix add"\nmode = "bugfix"\nchange_summary = "add adds"\n'
        f"python = {str(sys.executable)!r}\n\n"
        '[[obligations]]\nid = "acceptance"\nkind = "acceptance"\nmandatory = true\n'
        f"protected = {os.path.relpath(acceptance, contracts)!r}\n"
        'command = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "{protected}"]\n'
        + extra
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _make_repo(tmp_path, monkeypatch)


def _make_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str = "") -> Path:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    (repo / "contracts").mkdir(parents=True)
    (repo / "calc.py").write_text(BUGGY)
    (repo / "contracts" / "0001-fix-add.toml").write_text(_contract(acceptance, extra))
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
    return repo


def _shadow(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE)


def test_controls_buggy_blocks_and_fixed_is_ready(repo: Path) -> None:
    """Project code stays importable by the locked tests; the fix must not break that."""
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


@pytest.mark.parametrize("rel", list(SHADOWS.values()), ids=list(SHADOWS))
def test_candidate_file_cannot_replace_the_checker(repo: Path, rel: str) -> None:
    _shadow(repo, rel)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


@pytest.mark.parametrize("rel", list(SHADOWS.values()), ids=list(SHADOWS))
def test_shadow_file_does_not_break_a_real_fix(repo: Path, rel: str) -> None:
    (repo / "calc.py").write_text(FIXED)
    _shadow(repo, rel)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_checker_found_only_in_the_candidate_is_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra = (
        '\n[[obligations]]\nid = "lint"\nkind = "check"\nmandatory = true\n'
        'command = ["{python}", "-m", "ohx_absent_checker"]\n'
    )
    repo = _make_repo(tmp_path, monkeypatch, extra)
    (repo / "calc.py").write_text(FIXED)
    _shadow(repo, "ohx_absent_checker.py")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_candidate_file_cannot_replace_the_checker_under_srt(repo: Path) -> None:
    _shadow(repo, "pytest.py")
    assert main(["verify", "--sandbox", "srt"]) == EXIT_BLOCKED
