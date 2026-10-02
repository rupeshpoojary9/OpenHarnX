"""Acceptance tests for T77 item 9, weakened checks (contracts/0012).

Owner decisions 2026-10-01: proposal 1 (adding tests needs no approval; a
new or changed `conftest.py` does) and proposal 2 (`conftest.py`, pytest
`addopts` and fixtures are protected material, locked at acceptance).

Reproduced on `fb39881` by the independent verification: lint and type
settings live in the candidate, and new `# noqa` or `# type: ignore` were
not detected, so an agent could lower the bar and keep checks passing.

Every attack below makes the real checker pass, so the verdict was READY.
A mandatory built-in `weakening` obligation now blocks it; a contract
revision is the approval path.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = (
    "def add(a, b):\n    return a - b\n\n\n"
    "def sub(a, b):\n    return a - b\n\n\n"
    "def scale(a: int) -> int:\n    return a * 2\n"
)
FIXED = CALC.replace("return a - b\n\n\ndef sub", "return a + b\n\n\ndef sub")
BROKEN_SUB = FIXED.replace("def sub(a, b):\n    return a - b", "def sub(a, b):\n    return 0")
TESTS = (
    "from calc import sub\n\n\n"
    "def test_sub():\n    assert sub(5, 3) == 2\n    assert sub(3, 3) == 0\n\n\n"
    "def test_sub_negative():\n    assert sub(1, 3) == -2\n"
)
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
PYPROJECT = '[project]\nname = "calc"\nversion = "0"\n\n[tool.ruff.lint]\nselect = ["F"]\n'
FORCE_PASS = (
    "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\n"
    "def pytest_runtest_makereport(item, call):\n"
    "    outcome = yield\n    report = outcome.get_result()\n"
    "    if report.failed:\n        report.outcome = 'passed'\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _contract(acceptance: Path, contracts: Path, types: bool) -> str:
    text = (
        'title = "Fix add"\nmode = "bugfix"\nchange_summary = "add adds"\n'
        f"python = {sys.executable!r}\n\n"
        '[[obligations]]\nid = "acceptance"\nkind = "acceptance"\nmandatory = true\n'
        f"protected = {os.path.relpath(acceptance, contracts)!r}\n"
        'command = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "{protected}"]\n'
        '\n[[obligations]]\nid = "lint"\nkind = "check"\nmandatory = true\n'
        'command = ["{python}", "-m", "ruff", "check", "--no-cache", "."]\n'
        '\n[[obligations]]\nid = "tests"\nkind = "regression"\nmandatory = true\n'
        'command = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]\n'
    )
    if types:
        text += (
            '\n[[obligations]]\nid = "types"\nkind = "check"\nmandatory = true\n'
            'command = ["{python}", "-m", "mypy", "--cache-dir", "{tmp}/mypy", "calc.py"]\n'
        )
    return text


@pytest.fixture
def make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    def _make(types: bool = False) -> Path:
        acceptance = tmp_path / "outside" / "test_add.py"
        acceptance.parent.mkdir()
        acceptance.write_text(ACCEPTANCE)
        repo = tmp_path / "proj"
        (repo / "tests").mkdir(parents=True)
        (repo / "contracts").mkdir()
        (repo / "calc.py").write_text(CALC)
        (repo / "tests" / "test_calc.py").write_text(TESTS)
        (repo / "pyproject.toml").write_text(PYPROJECT)
        contract = _contract(acceptance, repo / "contracts", types)
        (repo / "contracts" / "0001-fix-add.toml").write_text(contract)
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
        monkeypatch.chdir(repo)
        assert main(["init"]) == EXIT_OK
        assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
        return repo

    return _make


def _report(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    main(["report", "--json"])
    report: dict[str, object] = json.loads(capsys.readouterr().out)
    return report


def _weakening_note(capsys: pytest.CaptureFixture[str]) -> str:
    observations = _report(capsys)["observations"]
    assert isinstance(observations, list)
    (ob,) = [o for o in observations if o["obligation_id"] == "weakening"]
    assert ob["outcome"] == "fail"
    note: str = ob["note"]
    return note


# Controls: honest work stays READY.


def test_control_a_real_fix_is_ready_and_runs_the_weakening_check(
    make: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    observations = _report(capsys)["observations"]
    assert isinstance(observations, list)
    assert [o["outcome"] for o in observations if o["obligation_id"] == "weakening"] == ["pass"]


def test_control_a_new_test_file_needs_no_approval(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text(FIXED)
    (repo / "tests" / "test_more.py").write_text(
        "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_control_more_tests_in_an_existing_file_need_no_approval(
    make: Callable[..., Path],
) -> None:
    repo = make()
    (repo / "calc.py").write_text(FIXED)
    with open(repo / "tests" / "test_calc.py", "a") as fh:
        fh.write("\n\ndef test_sub_zero():\n    assert sub(0, 0) == 0\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_control_an_accepted_revision_approves_a_config_change(
    make: Callable[..., Path],
) -> None:
    repo = make()
    (repo / "calc.py").write_text(FIXED)
    (repo / "pyproject.toml").write_text(PYPROJECT.replace('["F"]', '["F", "E"]'))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


# Attacks: each makes the real checker pass.


def test_new_noqa_is_blocked(make: Callable[..., Path], capsys: pytest.CaptureFixture[str]) -> None:
    repo = make()
    (repo / "calc.py").write_text("import os  # noqa: F401\n" + FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    assert "calc.py" in _weakening_note(capsys)


def test_file_level_ruff_noqa_is_blocked(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text("# ruff: noqa\nimport os\n" + FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_loosened_lint_config_is_blocked(
    make: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make()
    (repo / "calc.py").write_text("import os\n" + FIXED)
    (repo / "pyproject.toml").write_text(PYPROJECT + 'ignore = ["F401"]\n')
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    assert "pyproject.toml" in _weakening_note(capsys)


def test_new_type_ignore_is_blocked(make: Callable[..., Path]) -> None:
    repo = make(types=True)
    bad = FIXED.replace("return a * 2", 'return "x"  # type: ignore[return-value]')
    (repo / "calc.py").write_text(bad)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_new_skip_marker_is_blocked(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text(BROKEN_SUB)
    skipped = "import pytest\n" + TESTS.replace(
        "def test_sub():", '@pytest.mark.skip(reason="flaky")\ndef test_sub():'
    ).replace(
        "def test_sub_negative():", '@pytest.mark.skip(reason="flaky")\ndef test_sub_negative():'
    )
    (repo / "tests" / "test_calc.py").write_text(skipped)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_removed_assertions_are_blocked(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text(BROKEN_SUB)
    weakened = TESTS.replace(
        "    assert sub(5, 3) == 2\n    assert sub(3, 3) == 0\n", "    sub(5, 3)\n"
    )
    weakened = weakened.replace("    assert sub(1, 3) == -2\n", "    sub(1, 3)\n")
    (repo / "tests" / "test_calc.py").write_text(weakened)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_deleted_test_file_is_blocked(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text(BROKEN_SUB)
    (repo / "tests" / "test_calc.py").unlink()
    (repo / "tests" / "test_placeholder.py").write_text("def test_ok():\n    assert True\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_new_conftest_that_forces_passes_is_blocked(
    make: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make()
    (repo / "calc.py").write_text(BROKEN_SUB)
    (repo / "conftest.py").write_text(FORCE_PASS)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    assert "conftest.py" in _weakening_note(capsys)


def test_pytest_addopts_that_deselects_tests_is_blocked(make: Callable[..., Path]) -> None:
    repo = make()
    (repo / "calc.py").write_text(BROKEN_SUB)
    addopts = (
        '\n[tool.pytest.ini_options]\naddopts = "--deselect tests/test_calc.py::test_sub'
        ' --deselect tests/test_calc.py::test_sub_negative"\n'
    )
    (repo / "pyproject.toml").write_text(PYPROJECT + addopts)
    (repo / "tests" / "test_keep.py").write_text("def test_ok():\n    assert True\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_new_sitecustomize_is_blocked(make: Callable[..., Path]) -> None:
    """Runs at interpreter start-up wherever the candidate is on sys.path."""
    repo = make()
    (repo / "calc.py").write_text(FIXED)
    (repo / "sitecustomize.py").write_text("import os\nos.environ['X'] = '1'\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
