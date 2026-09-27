"""Positive and negative fixtures for the ADR-05 candidate identity spike."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from manifest import StatCache, build_manifest

FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "backend-bugfix" / "service"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "svc"
    shutil.copytree(FIXTURE, r)
    (r / ".gitignore").write_text("*.log\n")
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return r


def d(repo: Path) -> str:
    return str(build_manifest(repo)["digest"])


def test_deterministic(repo: Path) -> None:
    assert d(repo) == d(repo)


def test_dirty_tracked_edit_changes_identity(repo: Path) -> None:
    before = d(repo)
    (repo / "items.py").write_text((repo / "items.py").read_text() + "\n# human edit\n")
    assert d(repo) != before


def test_untracked_source_changes_identity(repo: Path) -> None:
    before = d(repo)
    (repo / "helpers.py").write_text("X = 1\n")
    assert d(repo) != before


def test_ignored_file_does_not_change_identity_but_is_reported(repo: Path) -> None:
    before = build_manifest(repo)
    (repo / "debug.log").write_text("noise\n")
    after = build_manifest(repo)
    assert after["digest"] == before["digest"]
    assert after["ignored_present"] == 1


def test_openharnx_output_is_excluded(repo: Path) -> None:
    before = d(repo)
    (repo / ".openharnx").mkdir()
    (repo / ".openharnx" / "report.json").write_text("{}")
    assert d(repo) == before


def test_exec_bit_changes_identity(repo: Path) -> None:
    before = d(repo)
    os.chmod(repo / "items.py", 0o755)
    assert d(repo) != before


def test_symlink_recorded_by_target_not_followed(repo: Path) -> None:
    (repo / "link.py").symlink_to("/etc/hosts")
    m = build_manifest(repo)
    link = next(e for e in m["entries"] if e["path"] == "link.py")  # type: ignore[union-attr]
    assert link == {"path": "link.py", "type": "symlink", "target": "/etc/hosts"}
    before = m["digest"]
    (repo / "link.py").unlink()
    (repo / "link.py").symlink_to("items.py")
    assert d(repo) != before


def test_rename_with_same_content_changes_identity(repo: Path) -> None:
    before = d(repo)
    (repo / "items.py").rename(repo / "listing.py")
    assert d(repo) != before


def test_case_only_rename_changes_identity(repo: Path) -> None:
    before = d(repo)
    git(repo, "mv", "items.py", "Items.py")
    after = build_manifest(repo)
    assert after["digest"] != before
    assert any(e["path"] == "Items.py" for e in after["entries"])  # type: ignore[union-attr]


def test_deleted_tracked_file_changes_identity(repo: Path) -> None:
    before = d(repo)
    (repo / "items.py").unlink()
    m = build_manifest(repo)
    assert m["digest"] != before
    assert {"path": "items.py", "type": "deleted"} in m["entries"]  # type: ignore[operator]


def test_committing_same_content_keeps_identity(repo: Path) -> None:
    (repo / "helpers.py").write_text("X = 1\n")
    before = build_manifest(repo)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c2")
    after = build_manifest(repo)
    assert after["digest"] == before["digest"]
    assert after["aliases"] != before["aliases"]  # the commit is an alias, not the identity


def test_mutation_during_verification_is_detected(repo: Path) -> None:
    before = d(repo)
    (repo / "items.py").write_text("# changed while tests ran\n")
    assert d(repo) != before  # before/after comparison marks the run invalid


def test_inspection_is_read_only(repo: Path) -> None:
    (repo / "items.py").write_text((repo / "items.py").read_text() + "\n# wip\n")
    (repo / "new.py").write_text("Y = 2\n")
    status = git(repo, "status", "--porcelain")
    stats = {p: os.stat(repo / p).st_mtime_ns for p in ("items.py", "new.py")}
    build_manifest(repo)
    assert git(repo, "status", "--porcelain") == status
    assert {p: os.stat(repo / p).st_mtime_ns for p in stats} == stats


def test_stat_cache_reuses_unchanged_files(repo: Path) -> None:
    cache = StatCache()
    first = build_manifest(repo, cache=cache)
    misses = cache.misses
    second = build_manifest(repo, cache=cache)
    assert second["digest"] == first["digest"]
    assert cache.misses == misses and cache.hits >= misses


def test_stat_cache_does_not_hide_edits(repo: Path) -> None:
    cache = StatCache()
    before = build_manifest(repo, cache=cache)["digest"]
    (repo / "items.py").write_text((repo / "items.py").read_text() + "\n# edit\n")
    assert build_manifest(repo, cache=cache)["digest"] != before
