"""`ohx history` says what to do in a shallow or partial clone (T92, contracts/0050).

Found running `ohx history` on anthropics/claude-agent-sdk-python (2026-10-05) from a
partial clone (`--filter=blob:none`): the throwaway clone it judges in shares the
repository's objects but cannot fetch the missing file contents, so every one of 31
commits failed with the same git error. A shallow clone lacks the history itself. Both
are now refused before any work, with what fixes them. The check looks for the file
contents of the commits to judge, not at git's configuration (removing the partial
clone settings, as tried during that run, leaves the contents missing).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import main

CALC = "def add(a, b):\n    return a + b\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "src-repo"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    (src / "calc.py").write_text(CALC)
    (src / "tests").mkdir()
    (src / "tests" / "test_calc.py").write_text(SUITE)
    (src / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git("add", "-A", cwd=src)
    _git("commit", "-qm", "start", cwd=src)
    for i in range(3):  # each change rewrites a file, so old contents differ
        (src / "notes.txt").write_text(f"{i}\n" * (i + 1))
        _git("add", "-A", cwd=src)
        _git("commit", "-qm", f"change {i}", cwd=src)
    _git("config", "uploadpack.allowFilter", "true", cwd=src)
    return src


def _run(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    monkeypatch.chdir(repo)
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    code = main(["history", "--last", "2", "--sandbox", "none", "--out", str(tmp_path / "o")])
    return code, ""


def test_a_partial_clone_is_refused_with_the_fix(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone = tmp_path / "partial"
    _git("clone", "-q", "--filter=blob:none", f"file://{source}", str(clone))
    code, _ = _run(clone, tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert code != 0 and "partial clone" in err and "without --filter" in err
    assert not (tmp_path / "o" / "history.json").exists()


def test_missing_contents_are_found_whatever_the_config_says(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone = tmp_path / "partial-unmarked"
    _git("clone", "-q", "--filter=blob:none", f"file://{source}", str(clone))
    for key in ("remote.origin.promisor", "remote.origin.partialclonefilter"):
        _git("config", "--unset-all", key, cwd=clone)
    code, _ = _run(clone, tmp_path, monkeypatch)
    assert code != 0 and "without --filter" in capsys.readouterr().err


def test_a_shallow_clone_is_refused_with_the_fix(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone = tmp_path / "shallow"
    _git("clone", "-q", "--depth", "1", f"file://{source}", str(clone))
    code, _ = _run(clone, tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert code != 0 and "shallow clone" in err and "git fetch --unshallow" in err


def test_a_full_clone_works(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clone = tmp_path / "full"
    _git("clone", "-q", f"file://{source}", str(clone))
    code, _ = _run(clone, tmp_path, monkeypatch)
    assert code == 0 and (tmp_path / "o" / "history.json").exists()
