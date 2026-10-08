"""The application package is split by use case, in layers (T107, contracts/0068).

`openharnx/app/__init__.py` had grown to about 1,800 lines holding init, contract
acceptance, verification, the evidence store and every helper they share, so a reader
could not tell what depended on what. It is now a set of modules in three layers:
the use cases (verification, contracts, evidence) above the shared machinery
(environments, trees, checks, suites) above `core`. An import-linter contract in
pyproject.toml keeps the layers, and `__init__` only re-exports the names the rest of
OpenHarnX uses, so nothing outside the package changed.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import openharnx.app as app

ROOT = Path.cwd()
PUBLIC = (
    "HOME_ENV",
    "UsageError",
    "accept_contract",
    "check_store",
    "current_report",
    "init_project",
    "new_contract",
    "now_utc",
    "ohx_home",
    "project_python",
    "sign_evidence",
    "verify",
)


def test_the_names_other_modules_use_still_come_from_the_package() -> None:
    for name in PUBLIC:
        assert hasattr(app, name), name


def test_the_package_init_only_re_exports() -> None:
    source = (ROOT / "src" / "openharnx" / "app" / "__init__.py").read_text()
    code = [
        line
        for line in source.splitlines()
        if line.strip() and not line.startswith(("from ", '"""')) and '"""' not in line
    ]
    assert len(code) <= 3, code  # the docstring's body only


def test_the_layers_are_kept_by_import_linter() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    contracts = config["tool"]["importlinter"]["contracts"]
    layered = next(c for c in contracts if c.get("containers") == ["openharnx.app"])
    assert layered["type"] == "layers"
    assert layered["layers"][-1] == "core"
    lowest_use_cases = {m.strip() for m in layered["layers"][0].split("|")}
    assert {"verification", "contracts", "evidence"} <= lowest_use_cases
    for layer in layered["layers"]:
        for module in layer.split("|"):
            importlib.import_module(f"openharnx.app.{module.strip()}")


def test_no_module_in_the_package_is_as_large_as_the_old_one() -> None:
    sizes = {
        p.name: len(p.read_text().splitlines())
        for p in (ROOT / "src" / "openharnx" / "app").glob("*.py")
    }
    assert max(sizes.values()) < 1000, sizes
