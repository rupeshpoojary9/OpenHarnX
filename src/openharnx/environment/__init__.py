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
import json
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


# Where an interpreter's code comes from, asked without its site setup (-S), so no `.pth`
# file or sitecustomize in that environment runs while it is being checked (T99).
_WHERE_PROBE = """\
import json, site, sys, sysconfig
paths = sysconfig.get_paths()
print(json.dumps({
    "executable": sys.executable,
    "stdlib": [paths["stdlib"], paths["platstdlib"]],
    "base_site": [paths["purelib"], paths["platlib"]],
    "user_site": site.getusersitepackages(),
    "version": "%d.%d" % sys.version_info[:2],
}))
"""
_VENV_PROBE = """\
import json, sys, sysconfig
root = sys.argv[1]
print(json.dumps([sysconfig.get_path(p, vars={"base": root, "platbase": root})
                  for p in ("purelib", "platlib")]))
"""
LISTED_CHANGES = 8


def _probe(python: str, code: str, *args: str) -> object:
    out = subprocess.run(
        [python, "-I", "-S", "-c", code, *args], capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise EnvironmentUnavailable(f"{python} could not be asked: {out.stderr.strip()[-300:]}")
    return json.loads(out.stdout)


def _venv_config(executable: Path) -> tuple[Path, bool] | None:
    """The virtual environment the executable belongs to, and whether it sees the base
    installation's packages; None for a plain installation."""
    for root in (executable.parent.parent, executable.parent):
        cfg = root / "pyvenv.cfg"
        if cfg.is_file():
            text = cfg.read_text(encoding="utf-8", errors="replace").lower()
            system = any(
                line.split("=", 1)[0].strip() == "include-system-site-packages"
                and line.split("=", 1)[1].strip() == "true"
                for line in text.splitlines()
                if "=" in line
            )
            return root, system
    return None


def interpreter_dirs(python: str) -> tuple[list[Path], list[Path], list[Path]]:
    """Folders whose files the interpreter loads code from, folders inside them that it
    does not, and single files that decide which it is (T99)."""
    where = _probe(python, _WHERE_PROBE)
    assert isinstance(where, dict)
    executable = Path(where["executable"])
    stdlib = [Path(p) for p in where["stdlib"]]
    base_site = [Path(p) for p in where["base_site"]]
    venv = _venv_config(executable)
    files = [executable]
    if venv is None:
        dirs = [*stdlib, *base_site, Path(where["user_site"])]
        skip: list[Path] = []
    else:
        root, system = venv
        files.append(root / "pyvenv.cfg")
        own = _probe(python, _VENV_PROBE, str(root))
        assert isinstance(own, list)
        dirs = [*stdlib, *(Path(p) for p in own)]
        skip = [] if system else base_site  # the base packages it cannot import
        if system:
            dirs += [*base_site, Path(where["user_site"])]
    unique = sorted({d for d in dirs if d.is_dir()})
    return unique, skip, files


def _walk(dirs: list[Path], skip: list[Path]) -> dict[str, tuple[int, int]]:
    """Path to (size, change time) for every file under `dirs`, without `__pycache__`."""
    found: dict[str, tuple[int, int]] = {}
    pruned = {str(s) for s in skip}
    for top in dirs:
        for folder, subdirs, names in os.walk(top):
            subdirs[:] = [
                s for s in subdirs if s != "__pycache__" and os.path.join(folder, s) not in pruned
            ]
            for name in names:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(folder, name)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                found[full] = (st.st_size, st.st_ctime_ns)
    return found


def interpreter_fingerprint(python: str, now_ns: int) -> dict[str, object]:
    """Path, size and change time of every file the interpreter can load code from. A
    file's change time moves on any write and cannot be set back by an ordinary user, so
    a later fingerprint names exactly the files changed after this one (T99)."""
    dirs, skip, single = interpreter_dirs(python)
    files = _walk(dirs, skip)
    for path in single:
        try:
            st = path.stat()  # follows the link: the interpreter actually run
            files[str(path)] = (st.st_size, st.st_ctime_ns)
        except OSError:
            files[str(path)] = (-1, -1)
    lines = sorted(f"{p}\0{size}\0{ctime}" for p, (size, ctime) in files.items())
    return {
        "python": python,
        "dirs": [str(d) for d in dirs],
        "files": len(files),
        "digest": "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest(),
        "taken_ns": str(now_ns),  # the record's canonical JSON holds no integer this big
        "_entries": files,
    }


def _listed(paths: list[str]) -> str:
    more = f" and {len(paths) - LISTED_CHANGES} more" if len(paths) > LISTED_CHANGES else ""
    return ", ".join(paths[:LISTED_CHANGES]) + more


def interpreter_changes(
    then: dict[str, object], then_paths: set[str] | None, now: dict[str, object]
) -> str:
    """Empty when the environment is as accepted; else what changed, for the report, with
    the files first so a shortened note still names them. `then_paths` is the accepted
    file list, when it could be read back."""
    if then["digest"] == now["digest"]:
        return ""
    taken = int(str(then["taken_ns"]))
    entries = now["_entries"]
    assert isinstance(entries, dict)
    listed = now["dirs"]
    assert isinstance(listed, list)
    dirs = sorted((str(d) for d in listed), key=len, reverse=True)

    def short(path: str) -> str:  # site-packages/x.pth rather than the whole path
        top = next((d for d in dirs if path.startswith(d + os.sep)), None)
        return path if top is None else f"{os.path.basename(top)}/{path[len(top) + 1 :]}"

    newer = sorted(short(p) for p, (_, ctime) in entries.items() if ctime > taken)
    parts = []
    if newer:
        parts.append(f"changed or added: {_listed(newer)}")
    if then_paths is not None:
        removed = sorted(short(p) for p in then_paths - set(entries))
        if removed:
            parts.append(f"removed: {_listed(removed)}")
    if not parts:
        parts.append("files were replaced or moved")
    return (
        f"the checker interpreter's environment changed since the contract was accepted"
        f" ({'; '.join(parts)}), so no check ran with it: code there runs before any test."
        f" Interpreter: {now['python']}. If you changed it on purpose, accept the contract"
        ' again (`ohx contract accept <file>`), or lock it with environment = "uv"'
    )
