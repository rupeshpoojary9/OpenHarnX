"""Acceptance tests for T77 item 4, STATE-14 (contracts/0010).

Found by the independent review on `fb39881`: changing the file a symlink
points to left the candidate digest and the report unchanged. The manifest
recorded only the link's target path, never what it resolves to.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main
from openharnx.workspace import build_manifest

FIXED = "def add(a, b):\n    return a + b\n"
BUGGY = "def add(a, b):\n    return a - b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    return repo


def _commit(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")


def _readiness(capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    main(["report", "--json"])
    readiness: str = json.loads(capsys.readouterr().out)["readiness"]
    return readiness


def test_changing_a_symlinked_file_outside_the_repo_makes_the_report_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "elsewhere" / "calc_impl.py"
    target.parent.mkdir()
    target.write_text(FIXED)
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = _repo(tmp_path)
    (repo / "calc.py").symlink_to(target)
    _commit(repo)
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert _readiness(capsys) == "ready"

    target.write_text(BUGGY)
    assert _readiness(capsys) == "stale"
    assert main(["report"]) == EXIT_BLOCKED


def test_manifest_changes_when_a_symlinked_file_changes(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "data.txt"
    target.parent.mkdir()
    target.write_text("one")
    repo = _repo(tmp_path)
    (repo / "data.txt").symlink_to(target)
    _commit(repo)
    before = build_manifest(repo)["digest"]
    target.write_text("two")
    assert build_manifest(repo)["digest"] != before


def test_manifest_changes_when_a_file_in_a_symlinked_directory_changes(tmp_path: Path) -> None:
    folder = tmp_path / "elsewhere" / "pkg"
    folder.mkdir(parents=True)
    (folder / "mod.py").write_text("x = 1\n")
    repo = _repo(tmp_path)
    (repo / "pkg").symlink_to(folder, target_is_directory=True)
    _commit(repo)
    before = build_manifest(repo)["digest"]
    (folder / "mod.py").write_text("x = 2\n")
    assert build_manifest(repo)["digest"] != before


def test_manifest_changes_when_a_symlink_target_disappears(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "data.txt"
    target.parent.mkdir()
    target.write_text("one")
    repo = _repo(tmp_path)
    (repo / "data.txt").symlink_to(target)
    _commit(repo)
    before = build_manifest(repo)["digest"]
    target.unlink()
    assert build_manifest(repo)["digest"] != before


def test_symlink_loop_does_not_crash(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "a").symlink_to(repo / "b")
    (repo / "b").symlink_to(repo / "a")
    _commit(repo)
    assert build_manifest(repo)["digest"].startswith("sha256:")


def test_unchanged_symlink_keeps_the_same_digest(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "data.txt"
    target.parent.mkdir()
    target.write_text("one")
    repo = _repo(tmp_path)
    (repo / "data.txt").symlink_to(target)
    _commit(repo)
    assert build_manifest(repo)["digest"] == build_manifest(repo)["digest"]
