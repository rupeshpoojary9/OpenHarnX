"""Acceptance tests for `ohx contract new` (contracts/0001-contract-new.toml).

Written before the feature. Self-contained, because the protected copy runs
from the OpenHarnX store, outside this repository.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main
from openharnx.kernel.contract import validate_contract

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
DEFAULTS = """python = "venv-python"

[[obligations]]
id = "lint"
kind = "check"
mandatory = true
command = ["{python}", "-c", "pass"]
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
    repo.mkdir()
    (repo / "calc.py").write_text(BUGGY)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


@pytest.fixture
def acceptance(tmp_path: Path) -> Path:
    path = tmp_path / "outside" / "test_calc.py"
    path.parent.mkdir()
    path.write_text(ACCEPTANCE)
    return path


def _new(*extra: str) -> int:
    return main(["contract", "new", "--title", "Fix add", "--summary", "add adds", *extra])


def test_writes_a_numbered_valid_contract_with_project_defaults(
    repo: Path, acceptance: Path
) -> None:
    (repo / "ohx.toml").write_text(DEFAULTS)
    assert _new("--mode", "task", "--acceptance", str(acceptance)) == EXIT_OK
    path = repo / "contracts" / "0001-fix-add.toml"
    raw = tomllib.loads(path.read_text())
    assert validate_contract(raw) == []
    assert raw["mode"] == "task"
    assert raw["python"] == "venv-python"
    by_id = {o["id"]: o for o in raw["obligations"]}
    assert by_id["lint"]["kind"] == "check"
    ob = by_id["acceptance-test_calc"]
    assert ob["kind"] == "acceptance" and ob["mandatory"] is True
    assert (path.parent / ob["protected"]).resolve() == acceptance.resolve()


def test_numbers_increase(repo: Path, acceptance: Path) -> None:
    assert _new("--acceptance", str(acceptance)) == EXIT_OK
    assert _new("--acceptance", str(acceptance)) == EXIT_OK
    assert (repo / "contracts" / "0002-fix-add.toml").exists()


def test_defaults_to_bugfix_and_advisory_tests_without_project_defaults(
    repo: Path, acceptance: Path
) -> None:
    (repo / "tests").mkdir()
    assert _new("--acceptance", str(acceptance)) == EXIT_OK
    raw = tomllib.loads((repo / "contracts" / "0001-fix-add.toml").read_text())
    assert raw["mode"] == "bugfix"
    regression = [o for o in raw["obligations"] if o["kind"] == "regression"]
    # the locked copy and the working tree's own run (T95), both advisory
    assert [o["id"] for o in regression] == ["locked-tests", "tests"]
    assert all(o["mandatory"] is False for o in regression)


def test_accept_flag_then_verify_blocks_then_passes(repo: Path, acceptance: Path) -> None:
    assert _new("--acceptance", str(acceptance), "--accept") == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_missing_acceptance_is_a_usage_error_and_writes_nothing(repo: Path) -> None:
    assert _new("--acceptance", str(repo / "nope.py")) == EXIT_USAGE
    assert not (repo / "contracts").exists()


def test_acceptance_is_required(repo: Path) -> None:
    with pytest.raises(SystemExit):
        _new()
