"""Acceptance tests for running locked tests inside the tree (T79, RC-31, contracts/0022).

From the first GitHub Actions run of the gate (2026-10-03): the locked copy of
the base tests ran from outside the repository, so tests that find files
relative to their own location (here `examples/` next to `tests/`) failed on
the base and on the pull request alike. They did not block, but the locked copy
did not protect them: a pull request could edit such a test to match broken
code and only its own, edited copy would run it.

The locked suite now runs in a read-only copy of the tree with `tests/`
replaced by the locked copy, for the base baseline and for the pull request.
Self-contained; runs without the sandbox for speed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n"
SUITE = """\
from pathlib import Path

from calc import add

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_add_matches_the_example():
    a, b, total = (int(x) for x in (EXAMPLES / "add.txt").read_text().split())
    assert add(a, b) == total
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
    (repo / "examples").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "examples" / "add.txt").write_text("2 3 5\n")
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.chdir(repo)
    return repo


def _gate(tmp_path: Path) -> tuple[int, dict[str, dict[str, Any]]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    return code, {o["obligation_id"]: o for o in report["gate"]["obligations"]}


def _commit(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "commit", "-qam", "change")


def test_a_location_relative_test_passes_in_the_locked_run(repo: Path, tmp_path: Path) -> None:
    _commit(repo, {"calc.py": CALC + "\n# a comment\n"})
    code, obligations = _gate(tmp_path)
    assert code == EXIT_OK
    assert obligations["locked-tests"]["status"] == "pass"


def test_editing_a_location_relative_test_to_match_broken_code_is_blocked(
    repo: Path, tmp_path: Path
) -> None:
    _commit(
        repo,
        {
            "calc.py": CALC.replace("a + b", "a + b + 1"),
            "tests/test_calc.py": SUITE.replace("== total", "== total + 1"),
        },
    )
    code, obligations = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    check = obligations["no-new-failures-locked-tests"]
    assert check["status"] == "fail"
    assert "test_add_matches_the_example" in " ".join(map(str, check["reasons"]))


def test_the_locked_run_does_not_include_tests_the_pull_request_adds(
    repo: Path, tmp_path: Path
) -> None:
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert False\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "new failing test")
    code, obligations = _gate(tmp_path)
    assert code == EXIT_BLOCKED  # the pull request's own suite catches it
    assert obligations["locked-tests"]["status"] == "pass"


def test_a_copy_that_differs_from_the_judged_candidate_is_refused(
    repo: Path, tmp_path: Path
) -> None:
    from openharnx.app import _tree_view, _TreeChanged  # the copy step itself
    from openharnx.workspace import build_manifest

    manifest = build_manifest(repo)
    (repo / "calc.py").write_text(CALC + "\n# edited after the snapshot\n")
    with pytest.raises(_TreeChanged, match="calc.py"):
        _tree_view(manifest, repo, repo / "tests", "tests", tmp_path / "view")
    # Unchanged files copy cleanly and the locked copy takes the place of tests/.
    clean = build_manifest(repo)
    view = _tree_view(clean, repo, repo / "tests", "tests", tmp_path / "view2")
    assert (view / "examples" / "add.txt").read_text() == "2 3 5\n"
    assert (view / "tests" / "test_calc.py").is_file()
