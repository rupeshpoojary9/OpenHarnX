"""A check that ran other code than the candidate's is invalid, never a pass (T90c,
contracts/0047).

Found replaying spec-kit's pull requests (2026-10-04): the checker environment held the
project installed in editable mode from another checkout, so every run tested that
checkout's code, and the gate said READY. An external review (2026-10-04) asked for this
to block, not warn. Each pytest run now records which of the project's modules it
loaded and from where (in every pytest-xdist worker too). A module loaded from outside
the candidate whose content differs from the candidate's own file for that module means
the run tested other code: the check is invalid and the verdict cannot pass. A copy with
the same content (the project installed from the candidate) and modules the candidate
does not have (generated, third-party) are fine.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.verify.where import project_files

BUGGY = "def add(a, b):\n    return a - b\n"
GOOD = "def add(a, b):\n    return a + b\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _toml(pythonpath: Path | None, args: str = "", mandatory: str = "true") -> str:
    env = f'env = {{ PYTHONPATH = "{pythonpath}" }}\n' if pythonpath else ""
    return (
        f'python = {sys.executable!r}\n\n[[obligations]]\nid = "tests"\nkind = "regression"\n'
        f'mandatory = {mandatory}\ncommand = ["{{python}}", "-m", "pytest", "-q",'
        f' "-p", "no:cacheprovider"{args}, "tests"]\n{env}'
    )


def _repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    elsewhere: str | None,
    args: str = "",
    mandatory: str = "true",
    extra_test: str = "",
) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(GOOD)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    if extra_test:  # outside the acceptance tests
        (repo / "tests" / "test_known.py").write_text("from calc import add" + extra_test)
    other = None
    if elsewhere is not None:
        other = tmp_path / "other-checkout"
        other.mkdir()
        (other / "calc.py").write_text(elsewhere)
        (other / "vendored_helper.py").write_text("X = 1\n")
    (repo / "ohx.toml").write_text(_toml(other, args, mandatory))
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args_new = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args_new += ["--acceptance", "tests/test_calc.py"]
    assert main([*args_new, "--accept", "--sandbox", "none"]) == EXIT_OK
    return repo


def _report(tmp_path: Path) -> dict[str, Any]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return report


def _tests_observation(report: dict[str, Any]) -> dict[str, Any]:
    return next(o for o in report["observations"] if o["obligation_id"] == "tests")


def test_tests_that_ran_another_checkouts_code_are_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, elsewhere=GOOD)
    (repo / "calc.py").write_text(BUGGY)  # the candidate is broken
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK  # the other copy passes the tests
    report = _report(tmp_path)
    assert report["readiness"] not in ("ready", "no-regressions")
    observation = _tests_observation(report)
    assert observation["outcome"] == "invalid"
    assert "calc" in observation["note"] and "other-checkout" in observation["note"]


def test_also_when_the_tests_run_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, elsewhere=GOOD, args=', "-n", "2"')
    (repo / "calc.py").write_text(BUGGY)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    assert _tests_observation(_report(tmp_path))["outcome"] == "invalid"


def test_an_identical_copy_of_the_candidate_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, monkeypatch, elsewhere=GOOD)  # like `pip install .` from the candidate
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_modules_the_candidate_does_not_have_are_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, elsewhere=GOOD)
    (repo / "tests" / "test_helper.py").write_text(
        "import vendored_helper\n\n\ndef test_helper():\n    assert vendored_helper.X == 1\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def test_an_ordinary_project_is_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch, elsewhere=None)
    (repo / "calc.py").write_text(GOOD + "\n\ndef sub(a, b):\n    return a - b\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert _tests_observation(_report(tmp_path))["outcome"] == "pass"


def test_project_modules_are_found_in_flat_and_src_layouts(tmp_path: Path) -> None:
    files = [
        "calc.py",
        "src/pkg/__init__.py",
        "src/pkg/sub/mod.py",
        "app/__init__.py",
        "app/views.py",
        "tests/test_calc.py",
        "tests/conftest.py",
        "docs/conf.py",
        "scripts/tool.py",
    ]
    found = project_files(files)
    assert found["calc"] == "calc.py"
    assert found["pkg"] == "src/pkg/__init__.py"
    assert found["pkg.sub.mod"] == "src/pkg/sub/mod.py"
    assert found["app.views"] == "app/views.py"
    for name in ("tests", "tests.test_calc", "docs.conf", "scripts.tool", "conftest"):
        assert name not in found


# As in a gate or a locked suite: an advisory suite compared test by test.
OLD_FAILURE = "\n\ndef test_known_bug():\n    assert add(0.1, 0.2) == 0.3\n"


def test_a_compared_suite_that_ran_other_code_cannot_be_compared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, elsewhere=GOOD, mandatory="false")
    (repo / "calc.py").write_text(BUGGY)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report = _report(tmp_path)
    compared = next(o for o in report["observations"] if o["obligation_id"] == "no-new-failures")
    assert compared["outcome"] == "invalid" and "cannot be compared" in compared["note"]


def test_a_compared_suite_with_an_old_failure_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, None, mandatory="false", extra_test=OLD_FAILURE)
    (repo / "calc.py").write_text(GOOD + "\n\ndef sub(a, b):\n    return a - b\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report = _report(tmp_path)
    compared = next(o for o in report["observations"] if o["obligation_id"] == "no-new-failures")
    assert compared["outcome"] == "pass" and "test_known_bug" in compared["note"]
