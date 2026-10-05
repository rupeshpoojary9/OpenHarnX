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
    project_python,
    verify,
)
from openharnx.app import approval as approvals
from openharnx.app.signed_approval import signed_approval
from openharnx.report import render_markdown
from openharnx.store import Record
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


def _gate_contract(
    base: Path,
    base_sha: str,
    head_sha: str,
    scratch: Path | None = None,
    working_tree: bool = False,
    approved: approvals.Approval | None = None,
    project: Path | None = None,
) -> dict[str, Any]:
    """The contract the base implies: its tests locked, its own checks, its policy.

    With `working_tree`, the base is the working tree itself (`ohx init --lock-tests`, T80);
    locked copies then go to `scratch`, never beside the repository. With `approved`, a
    maintainer accepted the pull request's test changes (T90b): the base's tests are not
    locked, and the pull request's own tests are compared with the base's results."""
    defaults: dict[str, Any] = {}
    if (base / "ohx.toml").is_file():
        try:
            defaults = tomllib.loads((base / "ohx.toml").read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise UsageError(f"the base commit's ohx.toml is not valid TOML: {exc}") from exc
    pytest = [*PYTEST, *_pytest_args(defaults)]
    obligations: list[dict[str, Any]] = []
    if (base / "tests").is_dir() and approved is None:
        obligations.append(
            {
                "id": "locked-tests",
                "kind": "regression",
                "mandatory": False,
                "protected": str(base / "tests"),
                # Run inside a copy of the tree with tests/ replaced by the locked copy,
                # so tests see the repository's layout and keep the same names (RC-31).
                "protected_at": "tests",
                "command": [*pytest, "{protected}"],
            }
        )
    # TypeScript, JavaScript and Go tests sit next to the code: the base's test files are
    # laid over a copy of the tree in place of the pull request's, wherever they are (T82).
    suites = {
        lang: suite
        for lang, suite in (("js", _js_suite(base, defaults)), ("go", _go_suite(base)))
        if suite is not None
    }
    scratch = scratch or base.parent
    locked = (
        _lock_overlay_tests(base, scratch / "locked-overlay")
        if suites and approved is None
        else None
    )
    for lang, suite in suites.items():
        if locked is None:
            break
        obligations.append(
            {
                "id": f"locked-{lang}-tests" if obligations else "locked-tests",
                "kind": "regression",
                "mandatory": False,
                "protected": str(locked),
                "protected_at": ".",
                **_suite_fields(suite),
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
                    "command": [*pytest, "tests"],
                }
            )
        for lang, suite in suites.items():
            taken = {o["id"] for o in obligations}
            obligations.append(
                {
                    "id": "tests" if "tests" not in taken else f"{lang}-tests",
                    "kind": "regression",
                    "mandatory": False,
                    **_suite_fields(suite),
                }
            )
    if not obligations:
        where = "this repository has" if working_tree else "the base commit has"
        raise UsageError(
            f"{where} no tests (tests/ or *.test.* files) and no obligations in ohx.toml"
        )
    raw: dict[str, Any] = {
        "title": f"Gate: {head_sha[:12]} against base {base_sha[:12]}",
        "mode": "gate",
        "change_summary": f"Pull request head {head_sha[:12]} judged against base {base_sha[:12]}",
    }
    if working_tree:
        raw = {
            "title": f"Locked suite at {head_sha[:12]}",
            "mode": "suite",
            "change_summary": f"The test suite of the working tree at {head_sha[:12]}, locked",
        }
    for key in ("python", "environment"):
        if key in defaults:
            raw[key] = defaults[key]
    if "python" not in raw and "environment" not in raw:
        found = project_python(project or base)  # the project's own environment (T94)
        if found:
            raw["python"] = found
    if approved is not None:
        raw |= {f"approved_{k}": v for k, v in approvals.as_dict(approved).items()}
    raw["obligations"] = obligations
    return raw


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


def _lock_overlay_tests(base: Path, dest: Path) -> Path | None:
    """Copy the base's TypeScript, JavaScript and Go test files, at their paths, into `dest`."""
    tracked = _git(base, "ls-files", "-z").split("\0")
    files = [f for f in tracked if f and f.endswith((*JS_SOURCE, ".go")) and is_test_file(f)]
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


def lock_tests(cwd: Path, sandbox: str = "auto") -> tuple[Record, dict[str, Any]]:
    """`ohx init --lock-tests`: the working tree's own test suite becomes the contract."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    work = Path(tempfile.mkdtemp(prefix="ohx-lock-"))
    try:
        raw = _gate_contract(root, head, head, scratch=work, working_tree=True)
        contract_file = work / "locked-suite.toml"
        _write_contract(raw, contract_file)
        init_project(root)
        record = accept_contract(root, contract_file, sandbox=sandbox)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return record, raw


def gate(
    cwd: Path,
    base_ref: str,
    *,
    sandbox: str = "auto",
    out: Path,
    contract: str | None = None,
    home: Path | None = None,
    approve_label: str | None = None,
    approval_file: Path | None = None,
) -> dict[str, Any]:
    """Verify the checked-out pull request against `base_ref`; returns the report.

    With `approve_label`, the GitHub label a maintainer adds to approve intended test
    changes is looked up (T90b); a refused approval changes nothing and says why. A
    signature from `ohx approve-tests` (a git note, or `approval_file`) is checked on any
    platform against the base's approvers (T90e)."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    base_sha = _git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    head_sha = _git(root, "rev-parse", "HEAD")
    looked_up = (
        approvals.github_approval(approve_label, head_sha, os.environ) if approve_label else None
    )
    approved = looked_up.approved if looked_up else None
    work = Path(tempfile.mkdtemp(prefix="ohx-gate-"))
    previous_home = os.environ.get(HOME_ENV)
    os.environ[HOME_ENV] = str(home or work / "home")
    try:
        base = work / "base"
        _base_copy(root, base_sha, base)
        signed = signed_approval(root, base, head_sha, approval_file)
        if signed is not None and (signed.approved or not approved):
            looked_up, approved = signed, signed.approved
        if contract:
            contract_file = base / contract
            if not contract_file.is_file():
                raise UsageError(f"{contract} does not exist in the base commit {base_sha[:12]}")
        else:
            contract_file = work / "gate-contract.toml"
            raw = _gate_contract(base, base_sha, head_sha, approved=approved, project=root)
            _write_contract(raw, contract_file)
        init_project(root)
        accept_contract(root, contract_file, sandbox=sandbox, baseline_root=base)
        record, _ = verify(root, sandbox=sandbox)
        report = dict(record.body)
        report["ci"] = {"base_ref": base_ref, "base_commit": base_sha, "head_commit": head_sha}
        if looked_up is not None:
            report["approval"] = (
                approvals.as_dict(approved)
                if approved and not contract
                else {
                    "refused": looked_up.refused
                    or "a contract file was given, so the approval does not apply",
                }
            )
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
