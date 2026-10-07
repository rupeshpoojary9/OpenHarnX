"""`ohx doctor` finds what stands between a new user and a first verification, and says
the fix (T103, contracts/0067).

The simulated user trial (2026-10-05) lost most of its setup time to things `ohx doctor`
did not look at: the sandbox (`srt`) not installed, the checks running with an
interpreter that has no pytest, and on Linux the programs the sandbox needs. Doctor
checked only Python, git and the platform.

Now it also checks, each with the command that fixes it: `srt` and its version; Node,
which `srt` needs; on Linux, bubblewrap, socat and ripgrep; inside a repository, which
interpreter the checks will use and whether it has pytest, and whether `ohx.toml` reads.
A missing sandbox is a warning (verification still runs with `--sandbox none`, and says
so); a broken `ohx.toml` fails, since nothing can be verified until it reads.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

SRT_INSTALL = "npm install -g @anthropic-ai/sandbox-runtime@0.0.77"


def _exe(folder: Path, name: str, script: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH with git and a Python but no srt and no node; outside any repository."""
    bindir = tmp_path / "bin"
    _exe(
        bindir,
        "git",
        f'exec {shutil.which("git")} "$@"',
    )
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.delenv("OHX_SRT", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    work = tmp_path / "elsewhere"
    work.mkdir()
    monkeypatch.chdir(work)
    return bindir


def _doctor(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capsys.readouterr()
    code = main(["doctor"])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_a_missing_sandbox_is_a_warning_with_the_install_command(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _doctor(capsys)
    assert code == EXIT_OK  # --sandbox none still works
    line = next(x for x in out.splitlines() if " srt:" in x)
    assert line.startswith("warn") and SRT_INSTALL in out


def test_a_sandbox_that_is_installed_is_shown_with_its_version(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _exe(bare, "srt", 'echo "0.0.77"')
    _exe(bare, "node", 'echo "v22.18.0"')
    code, out = _doctor(capsys)
    srt = next(x for x in out.splitlines() if " srt:" in x)
    assert srt.startswith("ok") and "0.0.77" in srt


def test_node_is_checked_because_the_sandbox_needs_it(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _doctor(capsys)
    node = next(x for x in out.splitlines() if " node:" in x)
    assert node.startswith("warn") and "20" in node  # what version it needs


def test_an_old_node_is_named(bare: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _exe(bare, "node", 'echo "v18.19.0"')
    _, out = _doctor(capsys)
    node = next(x for x in out.splitlines() if " node:" in x)
    assert node.startswith("warn") and "18.19.0" in node


@pytest.mark.skipif(sys.platform != "linux", reason="the sandbox's Linux helpers")
def test_on_linux_the_sandboxs_helpers_are_checked(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _doctor(capsys)
    for helper in ("bubblewrap", "socat", "ripgrep"):
        assert helper in out


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml: str | None) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if toml is not None:
        (repo / "ohx.toml").write_text(toml)
    monkeypatch.chdir(repo)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    return repo


def test_in_a_project_it_names_the_interpreter_and_finds_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path, monkeypatch, f"python = {sys.executable!r}\n")
    _, out = _doctor(capsys)
    line = next(x for x in out.splitlines() if " checks run with:" in x)
    assert line.startswith("ok") and sys.executable in line and "pytest" in line


def test_an_interpreter_without_pytest_is_a_warning_with_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    python = _exe(tmp_path / "venv" / "bin", "python", f'exec {sys.executable} -S "$@"')
    _repo(tmp_path, monkeypatch, f"python = {str(python)!r}\n")
    code, out = _doctor(capsys)
    line = next(x for x in out.splitlines() if " checks run with:" in x)
    assert line.startswith("warn") and "no pytest" in line
    assert f"{python} -m pip install pytest" in out or "python =" in out


def test_without_ohx_toml_the_projects_own_venv_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, monkeypatch, None)
    _exe(repo / ".venv" / "bin", "python", f'exec {sys.executable} "$@"')
    _, out = _doctor(capsys)
    line = next(x for x in out.splitlines() if " checks run with:" in x)
    assert ".venv/bin/python" in line


def test_a_protected_environment_is_named_instead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path, monkeypatch, 'environment = "uv"\n')
    _, out = _doctor(capsys)
    line = next(x for x in out.splitlines() if " checks run with:" in x)
    assert line.startswith("ok") and "uv.lock" in line


def test_an_ohx_toml_that_does_not_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path, monkeypatch, "python = \n")
    code, out = _doctor(capsys)
    assert code == EXIT_BLOCKED
    line = next(x for x in out.splitlines() if " ohx.toml:" in x)
    assert line.startswith("FAIL")


def test_outside_a_repository_the_project_checks_say_so(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _doctor(capsys)
    assert "not inside a git repository" in out


def test_the_existing_checks_are_still_there(
    bare: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out = _doctor(capsys)
    for name in (" python:", " git:", " platform:"):
        assert name in out
    assert os.environ["PATH"]  # the fixture's PATH, so nothing leaked from this machine
