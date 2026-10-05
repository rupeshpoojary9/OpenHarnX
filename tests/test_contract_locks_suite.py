"""An acceptance contract keeps the existing tests locked (T95, contracts/0053).

Found by a simulated skeptical user (2026-10-05, pypa/packaging): after
`ohx init --lock-tests`, `ohx contract new --acceptance ... --accept` made a contract
whose regression suite ran the working tree's own tests, not a locked copy. Breaking
the code and rewriting an existing test to expect the broken output gave READY. The
acceptance contract is what turns NO REGRESSIONS into READY, so it must hold at least as
much as the locked suite did.

Now `ohx contract new` (without obligations in ohx.toml) adds the locked copy of a
Python `tests/` folder, as `ohx init --lock-tests` and `ohx gate` do, next to the
working tree's own run. TypeScript, JavaScript and Go suites still run unlocked in such a
contract, and the report says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
SUITE = """\
from calc import add


def test_add():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-1, 1) == 0
"""
ACCEPTANCE = "from calc import half\n\n\ndef test_half():\n    assert half(10) == 5\n"
FIXED = CALC.replace("    return a\n", "    return a / 2\n")


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
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _contract() -> None:
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_half.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK


def _report(tmp_path: Path) -> dict[str, Any]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return report


@pytest.mark.parametrize("locked_first", [True, False], ids=["after the lock", "on its own"])
def test_rewriting_an_existing_test_to_expect_broken_code_is_blocked(
    repo: Path, tmp_path: Path, locked_first: bool
) -> None:
    if locked_first:
        assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    else:
        assert main(["init"]) == EXIT_OK
    _contract()
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a + b + 1"))
    (repo / "tests" / "test_calc.py").write_text(
        SUITE.replace("== 5", "== 6").replace("== 0", "== 1")
    )
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report = _report(tmp_path)
    failing = [o["obligation_id"] for o in report["gate"]["obligations"] if o["status"] != "pass"]
    assert "no-new-failures-locked-tests" in failing
    assert report["readiness"] == "blocked"


def test_the_genuine_fix_is_ready(repo: Path, tmp_path: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    _contract()
    (repo / "calc.py").write_text(FIXED)
    (repo / "tests" / "test_more.py").write_text(
        "from calc import half\n\n\ndef test_half_zero():\n    assert half(0) == 0\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report = _report(tmp_path)
    assert report["readiness"] == "ready" and report["claims"]["no_regressions"] is True
    assert "not locked" not in " ".join(report["limitations"])  # the Python suite is


def test_the_contract_file_locks_the_tests_folder(repo: Path) -> None:
    assert main(["init"]) == EXIT_OK
    _contract()
    written = next((repo / "contracts").glob("*.toml")).read_text()
    assert 'id = "locked-tests"' in written
    assert 'protected = "../tests"' in written and 'protected_at = "tests"' in written


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_an_unlocked_typescript_suite_is_named_in_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "js"
    (repo / "test").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "a.js").write_text("export const one = () => 1;\n")
    (repo / "test" / "a.test.js").write_text(
        'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
        'import { one } from "../src/a.js";\n\ntest("one", () => assert.equal(one(), 1));\n'
    )
    (repo / "package.json").write_text('{"name": "a", "type": "module"}\n')
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    assert main([*args, "--acceptance", "test/a.test.js", "--accept", "--sandbox", "none"]) == 0
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    limits = " ".join(_report(tmp_path)["limitations"])
    assert "not locked" in limits and "ohx init --lock-tests" in limits
