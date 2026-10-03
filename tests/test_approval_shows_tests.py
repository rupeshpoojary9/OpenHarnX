"""Acceptance tests for showing the proposed tests before approval (T87 item 2, contracts/0017).

From the owner's real `ohx bug` run (2026-10-03): approval locked the agent's
proposed tests as the oracle, but `ohx bug new` showed only the proposal and
its rule. The owner approved tests they never saw. A shallow test, one that
passes on the current code, or one that fails for an unrelated reason would
have been locked all the same.

`ohx bug new` now lists every proposed test with how it behaves on the current
code, flags tests that pass there or fail with something other than a failed
assertion, and `ohx bug show` prints the full test file. Self-contained.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main

PROPOSED = """\
import pytest

from calc import add


@pytest.mark.parametrize("a, b, total", [(2, 3, 5), (1, 1, 2)])
def test_add_cases(a, b, total):
    assert add(a, b) == total


def test_zero():
    assert add(0, 0) == 0


def test_typo():
    assert ad(1, 2) == 3
"""

AGENT = f"""
import os
from pathlib import Path

out = Path(os.environ["OHX_OUT"])
(out / "proposal.md").write_text("Cause: calc.py subtracts.\\nRule: add(a, b) is a + b.\\n")
(out / "test_proposed.py").write_text({PROPOSED!r})
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    (repo / "ohx.toml").write_text(
        f'python = "{sys.executable}"\n\n[agent]\ncommand = ["{sys.executable}", "{agent}"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    capsys.readouterr()
    assert main(["bug", "new", "add is wrong", "--sandbox", "none"]) == EXIT_OK
    return capsys.readouterr().out


def _line(out: str, *words: str) -> str:
    for line in out.splitlines():
        if all(w in line for w in words):
            return line
    raise AssertionError(f"no line with {words!r} in:\n{out}")


def test_every_proposed_test_is_listed_before_the_approve_step(output: str) -> None:
    lines = output.splitlines()
    approve = next(i for i, x in enumerate(lines) if "ohx bug approve BUG-001" in x)
    for name in ("test_add_cases", "test_zero", "test_typo"):
        assert any(name in x for x in lines[:approve]), name
    assert "2 cases" in _line(output, "test_add_cases")


def test_a_test_that_shows_the_bug_says_so(output: str) -> None:
    assert "fails on the current code" in _line(output, "test_add_cases")


def test_a_test_that_passes_on_the_current_code_is_flagged(output: str) -> None:
    assert "passes on the current code" in _line(output, "test_zero")


def test_a_test_failing_for_another_reason_is_flagged(output: str) -> None:
    assert "NameError" in _line(output, "test_typo")


def test_the_full_test_file_can_be_read_before_approving(
    output: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "ohx bug show BUG-001" in output
    assert main(["bug", "show", "BUG-001"]) == EXIT_OK
    shown = capsys.readouterr().out
    assert PROPOSED.strip() in shown
    assert "Rule: add(a, b) is a + b." in shown
