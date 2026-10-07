"""Checker environments: locked environments, lockfiles and the interpreter fingerprint."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from openharnx.app.core import UsageError
from openharnx.environment import (
    LOCKFILES,
    EnvironmentUnavailable,
    ensure,
    ensure_npm,
    interpreter_changes,
    interpreter_fingerprint,
)
from openharnx.kernel.canonical import digest
from openharnx.store import Store
from openharnx.workspace import (
    tree_digest,
)


def _checker_python(
    body_python: str,
    environment: dict[str, Any] | None,
    pdir: Path,
    root: Path,
    python_root: Path | None = None,
) -> tuple[str, str, str]:
    """The checkers' interpreter, and an outcome and note when its environment is unusable.

    A relative `python` resolves against `python_root` (default `root`): in CI the base
    is a bare copy without the candidate's virtual environment."""
    where = python_root or root
    python = str(where / body_python) if body_python != "unknown" else sys.executable
    if environment and environment["kind"] == "uv":
        try:
            python = str(_checker_environment(environment, pdir, root))
        except _EnvironmentChanged as exc:
            return python, "invalid", str(exc)
        except EnvironmentUnavailable as exc:
            return python, "unavailable", f"checker environment unavailable: {exc}"
    return python, "", ""


class _EnvironmentChanged(Exception):
    """The candidate's lockfile, or its accepted copy, differs from what was accepted."""


def _lock_environment(raw: dict[str, Any], pdir: Path, root: Path) -> dict[str, Any] | None:
    """At acceptance, lock `uv.lock` (T77 item 10) or `package-lock.json` with its
    `package.json` (T82) like a protected test."""
    if raw.get("environment") is None:
        return None
    kind = raw["environment"]
    name = LOCKFILES[kind]
    lockfile = root / name
    if not lockfile.is_file():
        raise UsageError(f'environment = "{kind}" needs {name} in the repository root')
    tdig = tree_digest(lockfile)
    extra: dict[str, Any] = {}
    folder = tdig.removeprefix("sha256:")[:16]
    if kind == "npm":
        package = root / "package.json"
        if not package.is_file():
            raise UsageError('environment = "npm" needs package.json in the repository root')
        extra["package_digest"] = pdig = tree_digest(package)
        folder = digest({"lock": tdig, "package": pdig}).removeprefix("sha256:")[:16]
    dest = pdir / "protected" / folder / name
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lockfile, dest)
        if kind == "npm":
            shutil.copy2(root / "package.json", dest.parent / "package.json")
    return {
        "kind": kind,
        "lock_digest": tdig,
        "lock_store_path": str(dest.relative_to(pdir)),
        **extra,
    }


_PACKAGE = re.compile(r"(?m)^\[\[package\]\]\s*$")


_OWN_SOURCE = re.compile(r'(?m)^source = \{ (?:editable|virtual) = "\." \}\s*$')


_VERSION_LINE = re.compile(r'(?m)^version = "[^"\n]*"\s*$')


def _without_own_version(text: str) -> str:
    """`uv.lock` with the version line of the project's own entry (source editable or
    virtual ".") blanked. The protected environment is built with --no-install-project,
    so that line never reaches it; every other line still counts."""
    parts = _PACKAGE.split(text)
    for i, block in enumerate(parts[1:], 1):
        if _OWN_SOURCE.search(block):
            parts[i] = _VERSION_LINE.sub('version = ""', block, count=1)
    return "[[package]]".join(parts)


def _same_lock(kind: str, candidate: Path, accepted: Path) -> bool:
    """Whether the candidate's lockfile is the accepted one; for uv, a bump of the
    project's own version is the same lockfile (T100)."""
    if tree_digest(candidate) == tree_digest(accepted):
        return True
    if kind != "uv":
        return False
    try:
        mine = candidate.read_text(encoding="utf-8")
        theirs = accepted.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _without_own_version(mine) == _without_own_version(theirs)


def _checker_environment(environment: dict[str, Any], pdir: Path, root: Path) -> Path:
    """The protected environment: the interpreter built from `uv.lock`, or the node_modules
    built from `package-lock.json`; nothing from the candidate's `.venv` or node_modules."""
    name = LOCKFILES[environment["kind"]]
    copy = pdir / environment["lock_store_path"]
    if not copy.is_file() or tree_digest(copy) != environment["lock_digest"]:
        raise _EnvironmentChanged(f"the accepted copy of {name} changed in the store")
    lockfile = root / name
    if not lockfile.is_file() or not _same_lock(environment["kind"], lockfile, copy):
        raise _EnvironmentChanged(
            f"{name} changed since contract acceptance; accept a contract revision"
        )
    if environment["kind"] == "npm":
        package = copy.parent / "package.json"
        if not package.is_file() or tree_digest(package) != environment.get("package_digest"):
            raise _EnvironmentChanged("the accepted copy of package.json changed in the store")
        return ensure_npm(pdir / "envs", copy, package)
    return ensure(pdir / "envs", copy, root).python


def _protected_modules(
    environment: dict[str, Any] | None, pdir: Path, root: Path
) -> tuple[Path | None, str, str]:
    """node_modules from the accepted lockfile, and an outcome and note when unusable."""
    if not environment or environment["kind"] != "npm":
        return None, "", ""
    try:
        return _checker_environment(environment, pdir, root), "", ""
    except _EnvironmentChanged as exc:
        return None, "invalid", str(exc)
    except EnvironmentUnavailable as exc:
        return None, "unavailable", f"checker environment unavailable: {exc}"


def _node_modules_limitations(body: dict[str, Any], root: Path) -> list[str]:
    """Name the blind spot when JavaScript checkers resolve packages from the candidate."""
    uses_node = any(
        "node_modules" in " ".join(ob.get("command", [])) or ob.get("command", [""])[0] == "node"
        for ob in body["obligations"]
    )
    if not uses_node or not (root / "node_modules").is_dir():
        return []
    if (body.get("environment") or {}).get("kind") == "npm":
        return []  # checks used the node_modules built from the accepted lockfile
    return [
        "JavaScript checkers resolved packages from node_modules in the candidate, which is"
        " git-ignored and outside the candidate identity, so changes to it are not detected"
    ]


def _interpreter_limitations(
    environment: dict[str, Any] | None,
    python: str,
    root: Path,
    recorded: dict[str, Any] | None = None,
) -> list[str]:
    """Name the interpreter the checkers ran with whenever no locked environment holds it,
    wherever it is, and what its fingerprint covers (T99)."""
    if environment:
        return []
    where = (
        " (inside the candidate, usually a .venv that is git-ignored)"
        if Path(python).is_relative_to(root)
        else ""
    )
    if recorded:
        covered = (
            f"its environment ({recorded['files']} files in"
            f" {', '.join(recorded.get('dirs', [])) or 'unrecorded folders'}) was"
            " fingerprinted at acceptance and matched before the checks ran, so later"
            " changes there are caught; changes made before acceptance, compiled"
            " __pycache__ files, and code loaded from other folders are not"
        )
    else:
        covered = (
            "this contract holds no fingerprint of its environment (accepted before T99, or"
            " the interpreter could not be asked), so changes to it are not detected"
        )
    return [
        f"Checkers ran with {python}{where}, outside the candidate identity and in no"
        f' locked environment: {covered}; environment = "uv" in ohx.toml locks it'
    ]


def _fingerprint(store: Store, python: str) -> dict[str, Any] | None:
    """The checker interpreter's fingerprint for the contract, with its file list kept as a
    blob so a later change can name removed files; None when it cannot be taken (T99)."""
    try:
        taken = interpreter_fingerprint(python, time.time_ns())
    except (EnvironmentUnavailable, OSError, ValueError, subprocess.TimeoutExpired):
        return None
    entries = taken.pop("_entries")
    assert isinstance(entries, dict)
    taken["paths_blob"] = store.put_blob(json.dumps(sorted(entries)).encode())
    return taken


def _interpreter_problem(store: Store, recorded: dict[str, Any], python: str) -> str:
    """Why the checkers must not run with this interpreter; empty when it is as accepted."""
    if recorded.get("python") != python:
        return (
            f"the checker interpreter is {python}, not {recorded.get('python')} as when the"
            " contract was accepted; accept the contract again (`ohx contract accept <file>`)"
        )
    try:
        now = interpreter_fingerprint(python, time.time_ns())
    except (EnvironmentUnavailable, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"the checker interpreter {python} could not be checked: {exc}"
    try:
        paths: set[str] | None = set(
            json.loads(store.blob_path(recorded["paths_blob"]).read_bytes())
        )
    except (OSError, ValueError, KeyError):
        paths = None
    return interpreter_changes(recorded, paths, now)
