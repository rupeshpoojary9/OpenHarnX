"""Checker environments built from an accepted lockfile, outside the candidate (T77 item 10).

The candidate's own `.venv` is git-ignored and so outside the candidate digest;
an agent can replace the interpreter or an installed checker there. A protected
environment is built by uv from the accepted copy of `uv.lock` into the
OpenHarnX store. Only locked wheels are installed (`--no-install-project
--no-build`), so no project or package build code runs. A `.pth` file appends
the candidate after the installed packages: project code stays importable but
cannot shadow the checker.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

UV_ENV = "OHX_UV"
LOCKFILE = "uv.lock"
NPM_ENV = "OHX_NPM"
NPM_LOCKFILE = "package-lock.json"
LOCKFILES = {"uv": LOCKFILE, "npm": NPM_LOCKFILE}
_COMPLETE = ".ohx-complete"


class EnvironmentUnavailable(Exception):
    """The environment could not be built; checks cannot run."""


@dataclass(frozen=True)
class CheckerEnvironment:
    python: Path
    root: Path


def find_uv() -> Path | None:
    configured = os.environ.get(UV_ENV)
    if configured:
        return Path(configured)
    found = shutil.which("uv")
    return Path(found) if found else None


def import_roots(candidate: Path) -> list[Path]:
    """The candidate root, and `src/` for src-layout projects."""
    roots = [candidate]
    if (candidate / "src").is_dir():
        roots.append(candidate / "src")
    return roots


def ensure(envs: Path, lockfile: Path, candidate: Path) -> CheckerEnvironment:
    """Build, or reuse, the environment for this lockfile, project file and candidate."""
    pyproject = candidate / "pyproject.toml"
    key = hashlib.sha256()
    for part in (lockfile.read_bytes(), _read(pyproject), str(candidate).encode()):
        key.update(hashlib.sha256(part).digest())
    root = envs / key.hexdigest()[:16]
    venv = root / "venv"
    python = venv / "bin" / "python"
    if (root / _COMPLETE).exists() and python.exists():
        return CheckerEnvironment(python, root)

    uv = find_uv()
    if uv is None:
        raise EnvironmentUnavailable("uv not found (set OHX_UV)")
    shutil.rmtree(root, ignore_errors=True)
    project = root / "project"
    project.mkdir(parents=True)
    shutil.copyfile(lockfile, project / LOCKFILE)
    if pyproject.exists():
        shutil.copyfile(pyproject, project / "pyproject.toml")
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    cmd = [str(uv), "sync", "--frozen", "--no-install-project", "--no-build", "--quiet"]
    try:
        proc = subprocess.run(cmd, cwd=project, env=env, capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentUnavailable(f"uv sync could not run: {exc}") from exc
    if proc.returncode != 0 or not python.exists():
        out = (proc.stdout + proc.stderr).decode(errors="replace").strip()[-2000:]
        raise EnvironmentUnavailable(f"uv sync failed ({proc.returncode}): {out}")
    # Isolated (-I) and run from the store: OpenHarnX runs inside the candidate, whose
    # files must never be importable by its own orchestration (review 2026-10-03).
    site = subprocess.run(
        [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not site:
        raise EnvironmentUnavailable("could not locate the environment's site-packages")
    lines = "".join(f"{p}\n" for p in import_roots(candidate))
    (Path(site) / "_ohx_candidate.pth").write_text(lines)
    (root / _COMPLETE).write_text("ok\n")
    return CheckerEnvironment(python, root)


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def find_npm() -> Path | None:
    configured = os.environ.get(NPM_ENV)
    if configured:
        return Path(configured)
    found = shutil.which("npm")
    return Path(found) if found else None


def ensure_npm(envs: Path, lockfile: Path, package: Path) -> Path:
    """Build, or reuse, node_modules for an accepted package-lock.json and package.json (T82).

    `npm ci --ignore-scripts`: exactly the locked packages, and no install script runs, so
    nothing a pull request adds to its dependencies runs outside the sandbox."""
    key = hashlib.sha256()
    for part in (lockfile.read_bytes(), _read(package)):
        key.update(hashlib.sha256(part).digest())
    root = envs / f"npm-{key.hexdigest()[:16]}"
    modules = root / "project" / "node_modules"
    if (root / _COMPLETE).exists() and modules.is_dir():
        return modules
    npm = find_npm()
    if npm is None:
        raise EnvironmentUnavailable("npm not found (set OHX_NPM)")
    shutil.rmtree(root, ignore_errors=True)
    project = root / "project"
    project.mkdir(parents=True)
    shutil.copyfile(lockfile, project / NPM_LOCKFILE)
    if package.exists():
        shutil.copyfile(package, project / "package.json")
    cmd = [str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    try:
        proc = subprocess.run(cmd, cwd=project, capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnvironmentUnavailable(f"npm ci could not run: {exc}") from exc
    if proc.returncode != 0 or not modules.is_dir():
        out = (proc.stdout + proc.stderr).decode(errors="replace").strip()[-2000:]
        raise EnvironmentUnavailable(f"npm ci failed ({proc.returncode}): {out}")
    (root / _COMPLETE).write_text("ok\n")
    return modules
