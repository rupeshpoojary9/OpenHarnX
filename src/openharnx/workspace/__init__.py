"""Read-only inspection of the project repository (ADR-0005)."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from openharnx.kernel.canonical import digest

MANIFEST_VERSION = "1"
DEFAULT_EXCLUDES = (".openharnx/",)


class NotARepository(Exception):
    pass


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _norm(path: str) -> str:
    return unicodedata.normalize("NFC", path.replace(os.sep, "/"))


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def repo_root(path: Path) -> Path:
    try:
        out = _git(path, "rev-parse", "--show-toplevel")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise NotARepository(str(path)) from exc
    return Path(out.decode().strip()).resolve()


def root_commit(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True,
        text=True,
    )
    lines = proc.stdout.split()
    return lines[0] if proc.returncode == 0 and lines else "unknown"


def build_manifest(repo: Path, excludes: tuple[str, ...] = DEFAULT_EXCLUDES) -> dict[str, Any]:
    """Tracked, modified and untracked-but-not-ignored files, bound by content digest."""
    listed = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = sorted({_norm(p) for p in listed.decode("utf-8", "surrogateescape").split("\0") if p})
    entries: list[dict[str, Any]] = []
    for rel in paths:
        if any(rel.startswith(ex) for ex in excludes):
            continue
        full = repo / rel
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            entries.append({"path": rel, "type": "deleted"})
            continue
        if stat.S_ISLNK(st.st_mode):
            entries.append({"path": rel, "type": "symlink", "target": _norm(os.readlink(full))})
        elif stat.S_ISREG(st.st_mode):
            entries.append(
                {
                    "path": rel,
                    "type": "file",
                    "exec": bool(st.st_mode & stat.S_IXUSR),
                    "digest": _file_digest(full),
                }
            )
        else:
            entries.append({"path": rel, "type": "other"})
    ignored = _git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
    )
    body = {"manifest_version": MANIFEST_VERSION, "algorithm": "sha256", "entries": entries}
    return {
        **body,
        "digest": digest(body),
        # Recorded, but outside the identity: a commit is an alias, not the candidate.
        "base_commit": head.stdout.strip() or "unknown",
        "excludes": list(excludes),
        "ignored_present": len([p for p in ignored.split(b"\0") if p]),
    }


def changed_paths(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    a = {e["path"]: e for e in before["entries"]}
    b = {e["path"]: e for e in after["entries"]}
    return sorted(p for p in a.keys() | b.keys() if a.get(p) != b.get(p))


def tree_digest(root: Path) -> str:
    """Digest of a directory of protected material, independent of git."""
    entries = []
    for p in sorted(root.rglob("*")):
        rel = _norm(str(p.relative_to(root)))
        if "__pycache__" in rel.split("/") or not p.is_file():
            continue
        entries.append({"path": rel, "digest": _file_digest(p)})
    return digest({"entries": entries})
