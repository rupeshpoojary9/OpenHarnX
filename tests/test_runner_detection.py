"""Code that checks whether a test runner is running is flagged (T105, contracts/0068).

Found by a simulated skeptical user (2026-10-05, pypa/packaging, u4 B6): changed code
that behaves correctly only when `_pytest` is in `sys.modules` passed every locked test
and would misbehave in use. Nothing in OpenHarnX looked for it.

Now the weakening check counts, in Python files that are not tests, the places that
look for a running test runner: `pytest` or `_pytest` in `sys.modules`, a `PYTEST_...`
environment variable (`PYTEST_CURRENT_TEST` and the like) read through `os.environ` or
`os.getenv`, and `pytest` in `sys.argv`. More of them than at acceptance blocks, like the
other source tricks (T89), and an intended one is approved the same way. Test files and
`conftest.py` may check their runner. Contracts locked before this rule are not judged
by it after the fact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.weakening import compare, snapshot

CALC = "def half(a):\n    return a / 2\n"
SUITE = "from calc import half\n\n\ndef test_half():\n    assert half(10) == 5\n"
TRICKS = {
    "sys.modules": (
        "import sys\n\n\ndef half(a):\n"
        '    if "_pytest" in sys.modules:\n        return a / 2\n    return a\n'
    ),
    "environ.get": (
        "import os\n\n\ndef half(a):\n"
        '    if os.environ.get("PYTEST_CURRENT_TEST"):\n        return a / 2\n    return a\n'
    ),
    "getenv": (
        'import os\n\n\ndef half(a):\n    return a / 2 if os.getenv("PYTEST_VERSION") else a\n'
    ),
    "environ[...]": (
        "import os\n\n\ndef half(a):\n    try:\n"
        '        os.environ["PYTEST_CURRENT_TEST"]\n        return a / 2\n'
        "    except KeyError:\n        return a\n"
    ),
    "environ in": (
        "import os\n\n\ndef half(a):\n"
        '    return a / 2 if "PYTEST_CURRENT_TEST" in os.environ else a\n'
    ),
    "sys.argv": (
        'import sys\n\n\ndef half(a):\n    return a / 2 if "pytest" in sys.argv[0] else a\n'
    ),
    "modules.get": (
        'import sys\n\n\ndef half(a):\n    return a / 2 if sys.modules.get("pytest") else a\n'
    ),
}


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
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    return repo


def _weakening(tmp_path: Path) -> dict[str, Any]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report = json.loads(runs[-1].read_text())
    observation: dict[str, Any] = next(
        o for o in report["observations"] if o["obligation_id"] == "weakening"
    )
    return observation


@pytest.mark.parametrize("trick", sorted(TRICKS))
def test_code_that_checks_for_the_test_runner_is_blocked(
    repo: Path, tmp_path: Path, trick: str
) -> None:
    (repo / "calc.py").write_text(TRICKS[trick])
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    weakening = _weakening(tmp_path)
    assert weakening["outcome"] == "fail"
    assert "calc.py: 1 new check for a running test runner" in weakening["note"]


def test_tests_and_conftest_may_check_their_runner(repo: Path, tmp_path: Path) -> None:
    (repo / "tests" / "conftest.py").write_text(
        'import os\n\nWORKER = os.environ.get("PYTEST_XDIST_WORKER")\n'
    )
    (repo / "tests" / "test_more.py").write_text(
        'import sys\n\n\ndef test_runner():\n    assert "_pytest" in sys.modules\n'
    )
    main(["verify", "--sandbox", "none"])
    assert "running test runner" not in _weakening(tmp_path)["note"]


def test_one_that_was_there_at_acceptance_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(TRICKS["environ.get"])
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.chdir(repo)
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(TRICKS["environ.get"] + "\n\nX = 1\n")
    main(["verify", "--sandbox", "none"])
    assert "running test runner" not in _weakening(tmp_path)["note"]


def test_mentions_that_do_not_check_the_runner_are_fine(repo: Path, tmp_path: Path) -> None:
    (repo / "calc.py").write_text(
        '"""Run the tests with pytest."""\nimport logging\n\n\ndef half(a):\n'
        '    logging.getLogger("pytest").debug("pytest")\n    return a / 2\n'
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert "running test runner" not in _weakening(tmp_path)["note"]


def test_a_contract_locked_before_this_rule_is_not_judged_by_it(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    (root / "calc.py").write_text(CALC)
    before = snapshot(root, ["calc.py"])
    before["version"] = 6  # a baseline written before T105
    for counts in before["suppressions"].values():
        counts.pop("check for a running test runner", None)
    (root / "calc.py").write_text(TRICKS["sys.modules"])
    assert not [f for f in compare(before, snapshot(root, ["calc.py"])) if "runner" in f]


def test_ordinary_use_of_argv_and_the_environment_is_fine(repo: Path, tmp_path: Path) -> None:
    (repo / "calc.py").write_text(
        "import os\nimport sys\n\n\ndef half(a):\n"
        "    verbose = len(sys.argv) > 1 and os.environ.get('VERBOSE', '0') == '1'\n"
        "    if verbose:\n        print(sys.argv[0])\n    return a / 2\n"
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert "running test runner" not in _weakening(tmp_path)["note"]
