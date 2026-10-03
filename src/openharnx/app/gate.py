"""`ohx gate`: judge a pull request against its base commit, in any CI (T79).

The base branch is the contract (owner decision 2026-10-03). Everything that
decides the verdict comes from the base commit: `ohx.toml` (interpreter,
environment, checks), the lockfile, the tests, and the weakening and regression
baselines. The base tests run as locked copies against the pull request's code,
so editing them in the pull request changes nothing. The pull request's own
tests run too, so a new test that fails blocks. Nothing the pull request adds
to `ohx.toml` or `contracts/` is read. No model calls.

The base is read from a `git clone --shared` of the repository, which reads
its objects and leaves the repository itself untouched. The evidence store is
a throwaway one unless `--home` keeps it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from openharnx.app import (
    HOME_ENV,
    UsageError,
    _toml_value,
    accept_contract,
    init_project,
    verify,
)
from openharnx.report import render_markdown
from openharnx.weakening import JS_SOURCE, is_test_file
from openharnx.workspace import NotARepository, repo_root

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
SUMMARY_ENV = "GITHUB_STEP_SUMMARY"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise UsageError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def _base_copy(root: Path, base_sha: str, dest: Path) -> None:
    """A checkout of the base commit that shares the repository's objects read-only."""
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(root), str(dest)],
        check=True,
        capture_output=True,
    )
    _git(dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", base_sha)


def _gate_contract(base: Path, base_sha: str, head_sha: str) -> dict[str, Any]:
    """The contract the base implies: its tests locked, its own checks, its policy."""
    defaults: dict[str, Any] = {}
    if (base / "ohx.toml").is_file():
        try:
            defaults = tomllib.loads((base / "ohx.toml").read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise UsageError(f"the base commit's ohx.toml is not valid TOML: {exc}") from exc
    obligations: list[dict[str, Any]] = []
    if (base / "tests").is_dir():
        obligations.append(
            {
                "id": "locked-tests",
                "kind": "regression",
                "mandatory": False,
                "protected": str(base / "tests"),
                # Run inside a copy of the tree with tests/ replaced by the locked copy,
                # so tests see the repository's layout and keep the same names (RC-31).
                "protected_at": "tests",
                "command": [*PYTEST, "{protected}"],
            }
        )
    js_suite = _js_suite(base, defaults)
    if js_suite is not None:
        locked = _lock_js_tests(base, base.parent / "locked-js")
        if locked:
            obligations.append(
                {
                    "id": "locked-js-tests" if obligations else "locked-tests",
                    "kind": "regression",
                    "mandatory": False,
                    "protected": str(locked),
                    # The base's test files laid over a copy of the tree in place of the
                    # pull request's, wherever they are (T82).
                    "protected_at": ".",
                    "command": js_suite,
                }
            )
    if "obligations" in defaults:
        obligations += [dict(o) for o in defaults["obligations"]]
    else:
        if (base / "tests").is_dir():
            obligations.append(
                {
                    "id": "tests",
                    "kind": "regression",
                    "mandatory": False,
                    "command": [*PYTEST, "tests"],
                }
            )
        if js_suite is not None:
            obligations.append(
                {
                    "id": "js-tests" if (base / "tests").is_dir() else "tests",
                    "kind": "regression",
                    "mandatory": False,
                    "command": js_suite,
                }
            )
    if not obligations:
        raise UsageError(
            "the base commit has no tests (tests/ or *.test.* files) and no obligations in ohx.toml"
        )
    raw: dict[str, Any] = {
        "title": f"Gate: {head_sha[:12]} against base {base_sha[:12]}",
        "mode": "gate",
        "change_summary": f"Pull request head {head_sha[:12]} judged against base {base_sha[:12]}",
    }
    for key in ("python", "environment"):
        if key in defaults:
            raw[key] = defaults[key]
    raw["obligations"] = obligations
    return raw


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


def _lock_js_tests(base: Path, dest: Path) -> Path | None:
    """Copy the base's TypeScript and JavaScript test files, at their paths, into `dest`."""
    tracked = _git(base, "ls-files", "-z").split("\0")
    files = [f for f in tracked if f and f.endswith(JS_SOURCE) and is_test_file(f)]
    if not files:
        return None
    for rel in files:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / rel, dest / rel)
    return dest


def _write_contract(raw: dict[str, Any], path: Path) -> None:
    lines = [f"{k} = {_toml_value(v)}" for k, v in raw.items() if k != "obligations"]
    for ob in raw["obligations"]:
        lines += ["", "[[obligations]]", *(f"{k} = {_toml_value(v)}" for k, v in ob.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def gate(
    cwd: Path,
    base_ref: str,
    *,
    sandbox: str = "auto",
    out: Path,
    contract: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Verify the checked-out pull request against `base_ref`; returns the report."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    base_sha = _git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    head_sha = _git(root, "rev-parse", "HEAD")
    work = Path(tempfile.mkdtemp(prefix="ohx-gate-"))
    previous_home = os.environ.get(HOME_ENV)
    os.environ[HOME_ENV] = str(home or work / "home")
    try:
        base = work / "base"
        _base_copy(root, base_sha, base)
        if contract:
            contract_file = base / contract
            if not contract_file.is_file():
                raise UsageError(f"{contract} does not exist in the base commit {base_sha[:12]}")
        else:
            contract_file = work / "gate-contract.toml"
            _write_contract(_gate_contract(base, base_sha, head_sha), contract_file)
        init_project(root)
        accept_contract(root, contract_file, sandbox=sandbox, baseline_root=base)
        record, _ = verify(root, sandbox=sandbox)
        report = dict(record.body)
        report["ci"] = {"base_ref": base_ref, "base_commit": base_sha, "head_commit": head_sha}
    finally:
        if previous_home is None:
            os.environ.pop(HOME_ENV, None)
        else:
            os.environ[HOME_ENV] = previous_home
        shutil.rmtree(work, ignore_errors=True)

    out.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    (out / "report.md").write_text(markdown)
    summary = os.environ.get(SUMMARY_ENV)
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    return report
