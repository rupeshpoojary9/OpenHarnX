"""The report says how many tests actually checked the change (T90d, contracts/0048).

Replaying spec-kit's pull requests (2026-10-04), tests that write under the home folder
failed inside the srt sandbox both before and after every change: no false alarm, but
they checked nothing, and the verdict did not say so. A test checks the change only
when it passes after it; one that failed or was skipped both before and after checked
nothing. The report's claims now count the tests that ran, the ones that checked the
change, and the ones that failed or were skipped both times, and say it in one line.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n"
SUITE = """\
import sys

import pytest

from calc import add


def test_add():
    assert add(2, 3) == 5


def test_add_zero():
    assert add(0, 3) == 3


def test_writes_home():
    assert add(0.1, 0.2) == 0.3  # fails before and after


@pytest.mark.skipif(sys.platform != "nonexistent-os", reason="other platforms only")
def test_platform_only():
    assert add(1, 1) == 2
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _report(tmp_path: Path) -> tuple[dict[str, Any], str]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    return json.loads(runs[-1].read_text()), (runs[-1].parent / "report.md").read_text()


def test_tests_that_failed_or_were_skipped_both_times_are_counted(
    repo: Path, tmp_path: Path
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    tests = report["claims"]["tests"]
    assert tests == {"ran": 4, "checked": 2, "failed_both_times": 1, "skipped_both_times": 1}
    assert "2 of 4 tests checked this change" in markdown
    assert "1 failed and 1 was skipped both before and after" in markdown


def test_a_suite_where_every_test_passes_says_so(repo: Path, tmp_path: Path) -> None:
    (repo / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    _git(repo, "commit", "-qam", "one test")
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["claims"]["tests"]["checked"] == 1
    assert "1 of 1 tests checked this change" in markdown


def test_without_per_test_results_nothing_is_counted(repo: Path, tmp_path: Path) -> None:
    (repo / "acceptance").mkdir()
    (repo / "acceptance" / "test_a.py").write_text(
        "from calc import add\n\n\ndef test_a():\n    assert add(1, 2) == 3\n"
    )
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\nobligations = []\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "acceptance only")
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_a.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["claims"]["tests"] is None
    assert "tests checked this change" not in markdown


def test_a_test_the_change_fixed_checked_it(repo: Path, tmp_path: Path) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    fixed = "def add(a, b):\n    return round(a + b, 10)\n"  # now 0.1 + 0.2 == 0.3
    (repo / "calc.py").write_text(fixed)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _ = _report(tmp_path)
    tests = report["claims"]["tests"]
    assert tests == {"ran": 4, "checked": 3, "failed_both_times": 0, "skipped_both_times": 1}
