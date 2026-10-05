"""Which code a pytest run executed: the candidate's, or another copy (T90c).

Replaying spec-kit's pull requests (2026-10-04), the checker environment held the
project installed in editable mode from another checkout, so the tests ran that code and
the gate said READY. A plugin loaded with `-p` records, at the end of each pytest
session (every pytest-xdist worker too), where each of the project's modules was loaded
from. A module loaded from outside the candidate whose content differs from the
candidate's own file for it means the run tested other code. Same content (the project
installed from the candidate), modules the candidate does not have, and the checker's
own modules (loaded before the plugin, such as pytest itself, which a candidate file must
never replace, T17) are fine.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

PLUGIN_MODULE = "ohx_where"
PLUGIN = """\
import json
import os
import sys

# Loaded with -p, before any conftest or project code: what is here now is the checker's.
CHECKER = set(sys.modules)


def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["OHX_WHERE_NAMES"], encoding="utf-8") as f:
        names = set(f.read().split())
    loaded = {}
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if name in names and path and name not in CHECKER:
            loaded[name] = os.path.realpath(path)
    out = os.path.join(os.environ["OHX_WHERE_DIR"], "where-%d.json" % os.getpid())
    with open(out, "w", encoding="utf-8") as f:
        json.dump(loaded, f)
"""
# Top-level folders that hold tests or tooling, not the project's importable code.
NOT_CODE = frozenset({"tests", "test", "testing", "docs", "doc", "scripts", "examples"})
NOT_MODULES = frozenset({"conftest", "setup", "noxfile", "fabfile", "manage"})


def project_files(paths: list[str]) -> dict[str, str]:
    """The candidate's importable Python modules: name to file, in flat and src layouts.
    Root-level modules, and packages (folders with `__init__.py`) at the root or in src/."""
    files = {p for p in paths if p.endswith(".py")}
    found: dict[str, str] = {}
    for rel in sorted(files):
        parts = PurePosixPath(rel).parts
        if parts[0] == "src" and len(parts) > 1:
            parts = parts[1:]
            prefix = "src/"
        else:
            prefix = ""
        if parts[0] in NOT_CODE:
            continue
        if len(parts) == 1:
            stem = parts[0][:-3]
            if stem not in NOT_MODULES and not stem.startswith("test_"):
                found[stem] = rel
            continue
        # The top folder must be a package; folders below may be namespace packages.
        folders = parts[:-1]
        if f"{prefix}{folders[0]}/__init__.py" not in files:
            continue
        leaf = parts[-1][:-3]
        name = ".".join(folders if leaf == "__init__" else (*folders, leaf))
        if not leaf.startswith("test_"):
            found[name] = rel
    return found


def where_env(folder: Path, names: list[str], pythonpath: str = "") -> dict[str, str]:
    """Environment that loads the plugin; results go to `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{PLUGIN_MODULE}.py").write_text(PLUGIN, encoding="utf-8")
    (folder / "names.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    return {
        "PYTEST_ADDOPTS": f"-p {PLUGIN_MODULE}",
        "PYTHONPATH": str(folder) + (f":{pythonpath}" if pythonpath else ""),
        "OHX_WHERE_NAMES": str(folder / "names.txt"),
        "OHX_WHERE_DIR": str(folder),
    }


def loaded_modules(folder: Path) -> dict[str, str]:
    """The project's modules a run loaded, name to file, from every pytest process."""
    loaded: dict[str, str] = {}
    for record in sorted(folder.glob("where-*.json")):
        try:
            loaded |= json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return loaded


def foreign_code(folder: Path, modules: dict[str, str], candidate: Path, ran_in: Path) -> list[str]:
    """Project modules the run loaded from outside the candidate with other content."""
    loaded = loaded_modules(folder)
    inside = [candidate.resolve(), ran_in.resolve()]
    problems = []
    for name, path in sorted(loaded.items()):
        rel = modules.get(name)
        if rel is None:
            continue
        where = Path(path)
        if any(where.is_relative_to(root) for root in inside):
            continue
        try:
            same = where.read_bytes() == (candidate / rel).read_bytes()
        except OSError:
            same = False
        if not same:
            problems.append(f"{name} ran from {where}, not the candidate's {rel}")
    return problems
