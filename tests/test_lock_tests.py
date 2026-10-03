"""Acceptance tests for `ohx init --lock-tests` (T80 slice 1, contracts/0033).

Zero setup: the project's existing test suite becomes the contract, with no contract file
to write. It is the CI gate's contract, taken from the working tree instead of a base
commit: the tests are locked (Python's `tests/`, and TypeScript, JavaScript and Go test
files wherever they are), every test that passes now must keep passing, and the
weakening check guards the configuration. `ohx verify` then judges any change, an
agent's or a person's, against it. Changing the tests on purpose means locking again.
"""

from __future__ import annotations

import json
import os
import shutil
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
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test Owner",
            "-c",
            "user.email=o@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Owner")  # who locks, as git says
    _git(repo, "config", "user.email", "o@example.com")
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


def test_one_command_locks_the_existing_suite(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "locked" in out and "tests" in out
    assert not (repo / "contracts").exists()  # nothing to write or commit
    assert sorted(p.name for p in tmp_path.iterdir()) == ["home", "proj"]  # nothing beside it
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_an_agent_that_edits_a_test_to_get_green_is_stopped(repo: Path, tmp_path: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 7"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    failing = [o for o in _report(tmp_path)["gate"]["obligations"] if o["status"] != "pass"]
    assert failing


def test_a_genuine_change_with_a_new_test_is_ready(repo: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "tests" / "test_sub.py").write_text(
        "from calc import sub\n\n\ndef test_sub():\n    assert sub(5, 3) == 2\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_changing_the_tests_on_purpose_means_locking_again(repo: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b * 1.0"))
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 6.0"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK  # same meaning, still passes
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("def test_mul", "def _off"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED  # a test went missing
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK  # the owner agrees
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_who_locked_the_suite_is_recorded(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    capsys.readouterr()
    assert main(["audit"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Test Owner" in out
    assert "Locked suite at" in out  # a locked suite, not a pull request gate


def test_a_repository_without_tests_is_told_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_USAGE
    assert "no tests" in capsys.readouterr().err


def _node_ok() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    major, minor = (int(x) for x in out.lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 18)


@pytest.mark.skipif(not _node_ok(), reason="needs Node 22.18 or later")
def test_typescript_tests_next_to_the_code_are_locked_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "ts"
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text('{"name": "calc", "type": "module"}')
    (repo / "src" / "calc.ts").write_text("export const mul = (a: number, b: number) => a * b;\n")
    (repo / "src" / "calc.test.ts").write_text(
        'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
        'import { mul } from "./calc.ts";\n\ntest("multiplies", () => {\n'
        "  assert.equal(mul(2, 3), 6);\n});\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert sorted(p.name for p in tmp_path.iterdir()) == ["home", "ts"]  # nothing beside it
    (repo / "src" / "calc.ts").write_text(
        "export const mul = (a: number, b: number) => a * b + 1;\n"
    )
    test = (repo / "src" / "calc.test.ts").read_text().replace("6);", "7);")
    (repo / "src" / "calc.test.ts").write_text(test)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_locking_and_verifying_under_srt(repo: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "srt"]) == EXIT_OK
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 7"))
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))
    assert main(["verify", "--sandbox", "srt"]) == EXIT_BLOCKED
