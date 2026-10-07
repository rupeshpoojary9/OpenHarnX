"""Copies of the candidate tree that locked tests run in."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from openharnx.weakening import JS_SOURCE, is_test_file
from openharnx.workspace import (
    file_digest,
)


class _TreeChanged(Exception):
    """A file changed while the tree was being copied for a locked run."""


# `protected_at = "."`: the locked material is a folder of test files at their own paths,
# laid over the tree in place of the candidate's TypeScript and JavaScript test files (T82).
OVERLAY = "."


def _copy_tree(manifest: dict[str, Any], root: Path, dest: Path, skip: str | None = None) -> None:
    """Copy the tree as `manifest` records it, checking each file against its digest."""
    for e in manifest["entries"]:
        rel = e["path"]
        if skip == OVERLAY:
            if is_test_file(rel) and rel.endswith((*JS_SOURCE, ".go")):
                continue
        elif skip is not None and (rel == skip or rel.startswith(skip + "/")):
            continue
        if e["type"] not in ("file", "symlink"):
            continue
        src, dst = root / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if e["type"] == "symlink":
            os.symlink(os.readlink(src), dst)
            continue
        shutil.copy2(src, dst)
        if file_digest(dst) != e["digest"]:
            raise _TreeChanged(f"{rel} changed while the tree was being copied")


def _link_node_modules(modules: Path, dest: Path) -> None:
    """Git ignores node_modules, so a copy of the tree lacks it. Link the protected one
    (`environment = "npm"`), else the candidate's own (named in the limitations)."""
    if modules.is_dir() and not (dest / "node_modules").exists():
        (dest / "node_modules").symlink_to(modules.resolve())


def _modules_view(manifest: dict[str, Any], root: Path, modules: Path, dest: Path) -> Path:
    """A copy of the tree with the protected node_modules, for checks that run on the tree."""
    if not dest.exists():
        _copy_tree(manifest, root, dest)
        _link_node_modules(modules, dest)
    return dest


def _tree_view(
    manifest: dict[str, Any],
    root: Path,
    protected: Path,
    at: str,
    dest: Path,
    modules: Path | None = None,
) -> Path:
    """A copy of the tree as `manifest` records it, with `at` replaced by the locked copy.

    Locked tests then run where they would run in the repository, so tests that find
    files relative to their own location work (RC-31). Each copied file is checked
    against its digest: the copy is the judged candidate, or the run is invalid.
    """
    _copy_tree(manifest, root, dest, skip=at)
    _link_node_modules(modules or root / "node_modules", dest)
    if at == OVERLAY:
        shutil.copytree(
            protected, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
        )
    elif protected.is_dir():
        shutil.copytree(protected, dest / at, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        (dest / at).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(protected, dest / at)
    return dest
