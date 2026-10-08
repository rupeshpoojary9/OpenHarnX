"""The whole-suite commands OpenHarnX adds (T107): the project's pytest run, its
TypeScript or JavaScript runner and Go's tests, read from a base's `ohx.toml`.

Shared by `ohx gate` and contract acceptance, so it sits below both.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openharnx.app.core import UsageError

PYTEST = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
# Whole-suite commands for TypeScript and JavaScript (T82), with per-test results.
JS_SUITES: dict[str, list[str]] = {
    "vitest": [
        "node_modules/.bin/vitest",
        "run",
        "--reporter=default",
        "--reporter=junit",
        "--outputFile.junit={junit}",
    ],
    "jest": ["node_modules/.bin/jest", "--ci"],
    "node": [
        "node",
        "--test",
        "--test-reporter=spec",
        "--test-reporter-destination=stdout",
        "--test-reporter=junit",
        "--test-reporter-destination={junit}",
        "**/*.{test,spec}.{ts,mts,cts,js,mjs,cjs}",
    ],
}


SUITE_TIMEOUT_S = 300


def _suite_timeout(defaults: dict[str, Any]) -> int | float:
    """Seconds a whole suite OpenHarnX adds may run (`suite_timeout_s` in ohx.toml): a
    slow suite under the sandbox on a CI runner outgrew the fixed default (T100)."""
    value = defaults.get("suite_timeout_s", SUITE_TIMEOUT_S)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise UsageError("suite_timeout_s in ohx.toml must be a positive number of seconds")
    return value


def _pytest_args(defaults: dict[str, Any]) -> list[str]:
    """The project's own pytest options (`pytest_args` in ohx.toml, such as pytest-xdist's
    `-n auto`), added to the locked run and the default `tests` run (T80)."""
    args = defaults.get("pytest_args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise UsageError("pytest_args in ohx.toml must be a list of strings")
    return args


def _js_suite(base: Path, defaults: dict[str, Any]) -> list[str] | None:
    """The base's TypeScript or JavaScript runner: `js_runner` in ohx.toml, else Vitest or
    Jest when package.json lists it, else Node's own; None when the base has no package.json."""
    package_file = base / "package.json"
    if not package_file.is_file():
        return None
    runner = defaults.get("js_runner")
    if runner is None:
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            package = {}
        listed: set[str] = set()
        for key in ("dependencies", "devDependencies"):
            if isinstance(package, dict) and isinstance(package.get(key), dict):
                listed |= set(package[key])
        runner = next((r for r in ("vitest", "jest") if r in listed), "node")
    if runner not in JS_SUITES:
        raise UsageError(f"js_runner in the base's ohx.toml must be one of {sorted(JS_SUITES)}")
    return list(JS_SUITES[runner])


GO_ENV = {"GOTOOLCHAIN": "local", "GOFLAGS": "-mod=readonly", "GOCACHE": "{tmp}/go-build"}
GO_SUITE = ["go", "test", "-json", "-count=1", "./..."]


def _go_suite(base: Path) -> list[str] | None:
    return list(GO_SUITE) if (base / "go.mod").is_file() else None


def _suite_fields(suite: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {"command": suite}
    if suite[0] == "go":
        fields["env"] = dict(GO_ENV)
    return fields
