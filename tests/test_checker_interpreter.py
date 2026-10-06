"""The checker interpreter's environment is fingerprinted at acceptance and checked before
every verification (T99, contracts/0058).

Found by a simulated skeptical user (2026-10-05, pypa/packaging, u4 B7): checks ran with
a virtual environment outside the repository, named by an absolute `python` in ohx.toml.
A `.pth` file dropped into its site-packages after the contract was accepted ran before
every check and rewrote failures to passes; the report gave READY and did not name the
interpreter at all, because the existing limitation only covered interpreters inside the
repository.

Now, without a locked environment (`environment = "uv"`), accepting a contract records a
fingerprint of the checker interpreter's environment: path, size and change time of every
file in its site-packages and standard library, not counting `__pycache__`. Every
verification takes it again before running anything; if it differs, every check is
invalid and the note names the files changed since acceptance. The interpreter is found
without running its site setup, so a planted `.pth` does not run during the check. Every
report without a locked environment names the interpreter and what is and is not covered.
"""

from __future__ import annotations

import json
import subprocess
import sysconfig
import venv
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n"
FIXED = "def add(a, b):\n    return a + b  # same behaviour\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"
# What u4 planted: a .pth line runs at interpreter start, before any test or conftest.
EVIL_PTH = "import os; os.environ.setdefault('OHX_PLANTED', '1')\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _outside_venv(where: Path) -> tuple[Path, Path]:
    """A real virtual environment outside the repository that can run pytest: the test
    run's own site-packages are added with a path .pth, set up before acceptance."""
    venv.EnvBuilder(with_pip=False, symlinks=True).create(where)
    python = where / "bin" / "python"
    site = Path(
        subprocess.run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    )  # fmt: skip
    assert site.is_relative_to(where)  # never write into the base installation
    (site / "host.pth").write_text(sysconfig.get_path("purelib") + "\n")
    return python, site


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    python, site = _outside_venv(tmp_path / "elsewhere" / "venv")
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_zero.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {str(python)!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_zero.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    return repo, python, site


def _verify(tmp_path: Path) -> tuple[int, dict[str, Any]]:
    code = main(["verify", "--sandbox", "none"])
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return code, report


def test_an_unchanged_environment_verifies_and_the_interpreter_is_named(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, python, _ = setup
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code == EXIT_OK, report["gate"]
    assert report["readiness"] == "ready"
    limits = " ".join(report["limitations"])
    assert str(python) in limits  # named although it is outside the repository
    assert "fingerprint" in limits and 'environment = "uv"' in limits


def test_a_pth_file_planted_after_acceptance_makes_every_check_invalid(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    (site / "zz_planted.pth").write_text(EVIL_PTH)
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code != EXIT_OK
    assert report["readiness"] in ("invalid", "unknown", "blocked")
    notes = [o["note"] for o in report["observations"]]
    assert notes and all("zz_planted.pth" in n for n in notes), notes
    assert all(o["outcome"] == "invalid" for o in report["observations"])


def test_the_planted_file_does_not_run_while_the_environment_is_checked(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    marker = tmp_path / "ran"
    (site / "zz_planted.pth").write_text(f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n")
    (repo / "calc.py").write_text(FIXED)
    _verify(tmp_path)
    assert not marker.exists()  # no check ran, and finding the environment ran no .pth


def test_an_edited_installed_package_is_caught(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    package = site / "helper_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("X = 1\n")
    # Installed before acceptance would be fine; here it appears after.
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code != EXIT_OK
    assert any("helper_pkg/__init__.py" in o["note"] for o in report["observations"])


def test_a_removed_file_is_caught(setup: tuple[Path, Path, Path], tmp_path: Path) -> None:
    repo, _, site = setup
    (site / "host.pth").unlink()
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code != EXIT_OK
    assert any("removed" in o["note"] for o in report["observations"])


def test_bytecode_written_by_running_the_tests_does_not_count(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    cache = site / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "something.cpython-312.pyc").write_bytes(b"\0" * 16)
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code == EXIT_OK, [o["note"] for o in report["observations"]]


def test_accepting_again_takes_a_new_fingerprint(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    (site / "intended.pth").write_text("\n")  # the owner installs something on purpose
    contract = next((repo / "contracts").glob("*.toml"))
    assert main(["contract", "accept", str(contract), "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    code, _ = _verify(tmp_path)
    assert code == EXIT_OK


def test_the_note_says_how_to_accept_an_intended_change(
    setup: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    repo, _, site = setup
    (site / "intended.pth").write_text("\n")
    (repo / "calc.py").write_text(FIXED)
    _, report = _verify(tmp_path)
    note = report["observations"][0]["note"]
    assert "ohx contract accept" in note


def test_an_interpreter_that_cannot_be_asked_still_runs_the_checks_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a fingerprint (an interpreter that refuses `-S`, or a contract accepted
    before T99) the checks run as before, and the report says changes are not detected."""
    python, _ = _outside_venv(tmp_path / "elsewhere" / "venv")
    wrapper = tmp_path / "odd" / "python"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f'#!/bin/sh\nfor a in "$@"; do [ "$a" = "-S" ] && exit 3; done\nexec {python} "$@"\n'
    )
    wrapper.chmod(0o755)
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_zero.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {str(wrapper)!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_zero.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify(tmp_path)
    assert code == EXIT_OK, [o["note"] for o in report["observations"]]
    limits = " ".join(report["limitations"])
    assert str(wrapper) in limits and "no fingerprint" in limits
