"""Spike (ADR-05): candidate manifest and digest from a git working tree.

Read-only with respect to the repository: it runs git plumbing commands and
reads files; it never writes, stages, stashes or resets anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_VERSION = "spike-1"
DEFAULT_EXCLUDES = (".openharnx/",)


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _norm(path: str) -> str:
    return unicodedata.normalize("NFC", path.replace(os.sep, "/"))


@dataclass
class StatCache:
    """Maps (path, size, mtime_ns, inode, mode) to a content digest."""

    entries: dict[tuple[str, int, int, int, int], str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def digest(self, full: Path, rel: str, st: os.stat_result) -> str:
        key = (rel, st.st_size, st.st_mtime_ns, st.st_ino, st.st_mode)
        if key in self.entries:
            self.hits += 1
            return self.entries[key]
        self.misses += 1
        h = hashlib.sha256()
        with open(full, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        value = "sha256:" + h.hexdigest()
        self.entries[key] = value
        return value


def build_manifest(
    repo: Path, excludes: tuple[str, ...] = DEFAULT_EXCLUDES, cache: StatCache | None = None
) -> dict[str, object]:
    cache = cache or StatCache()
    listed = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = sorted({_norm(p) for p in listed.decode("utf-8", "surrogateescape").split("\0") if p})
    entries: list[dict[str, object]] = []
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
            target = os.readlink(full)
            entries.append({"path": rel, "type": "symlink", "target": _norm(target)})
        elif stat.S_ISREG(st.st_mode):
            entries.append(
                {
                    "path": rel,
                    "type": "file",
                    "exec": bool(st.st_mode & stat.S_IXUSR),
                    "digest": cache.digest(full, rel, st),
                }
            )
        else:
            entries.append({"path": rel, "type": "other"})
    ignored = _git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard")
    ignored_count = len([p for p in ignored.split(b"\0") if p])
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True
    )
    body = {"manifest_version": MANIFEST_VERSION, "algorithm": "sha256", "entries": entries}
    return {
        **body,
        "digest": digest_of(body),
        # Aliases and limitations are recorded but excluded from the digest.
        "aliases": {"base_commit": head.stdout.decode().strip() or None},
        "excludes": list(excludes),
        "ignored_present": ignored_count,
    }


def digest_of(body: dict[str, object]) -> str:
    # Canonical JSON: sorted keys, no whitespace, UTF-8. Values here are only strings,
    # booleans and lists/objects of them, where this matches RFC 8785 output.
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
