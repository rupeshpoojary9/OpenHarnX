"""Acceptance tests for TypeScript and JavaScript in `ohx gate` (T82 slice 2, contracts/0031).

In CI the base branch is the contract. For Python the gate locked `tests/`; TypeScript
and JavaScript tests sit next to the code, so the gate now locks every test file of the
base (`*.test.*`, `*.spec.*`, `__tests__/`) wherever it is: the locked run uses the
pull request's code with the base's test files in place of the pull request's.

The runner is `js_runner` in the base's `ohx.toml`, else Vitest or Jest when the base's
`package.json` lists it, else Node's own runner.

`environment = "npm"` protects the packages: running `npm ci` on a pull request runs
its install scripts outside any sandbox, and a git-ignored `node_modules` is outside the
candidate identity. The gate installs from the base's `package-lock.json` itself, with
install scripts off, into its own store, and every check uses that copy. A pull request
that changes the lockfile runs nothing until a contract revision accepts it.

Self-contained: Node's own test runner, and a stand-in for npm.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main


def _node_strips_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    m = re.match(r"v(\d+)\.(\d+)", out)
    return m is not None and (int(m.group(1)), int(m.group(2))) >= (22, 18)


pytestmark = pytest.mark.skipif(not _node_strips_types(), reason="needs Node 22.18 or later")

CALC = (
    "export function add(a: number, b: number): number {\n  return a + b;\n}\n\n"
    "export function mul(a: number, b: number): number {\n  return a * b;\n}\n"
)
CALC_TEST = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { add, mul } from "./calc.ts";

test("adds", () => {
  assert.equal(add(2, 3), 5);
});

test("multiplies", () => {
  assert.equal(mul(2, 3), 6);
});
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    _write(
        repo,
        {
            "package.json": json.dumps({"name": "calc", "type": "module", "scripts": {}}),
            ".gitignore": "node_modules\n",
            "src/calc.ts": CALC,
            "src/calc.test.ts": CALC_TEST,
        },
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _pr(repo: Path, files: dict[str, str], remove: tuple[str, ...] = ()) -> None:
    _write(repo, files)
    for rel in remove:
        (repo / rel).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _gate(tmp_path: Path, sandbox: str = "none") -> tuple[int, dict[str, Any]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", sandbox, "--out", str(out)])
    return code, json.loads((out / "report.json").read_text())


def _not_passing(report: dict[str, Any]) -> list[str]:
    return [o["obligation_id"] for o in report["gate"]["obligations"] if o["status"] != "pass"]


def _notes(report: dict[str, Any]) -> str:
    return " ".join(o["note"] for o in report["observations"])


def test_a_genuine_change_with_a_new_test_is_ready(repo: Path, tmp_path: Path) -> None:
    sub = "import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
    sub += "import { sub } from './calc.ts';\n\ntest('subtracts', () => {\n"
    sub += "  assert.equal(sub(5, 3), 2);\n});\n"
    calc = CALC + "\nexport const sub = (a: number, b: number): number => a - b;\n"
    _pr(repo, {"src/calc.ts": calc, "src/sub.test.ts": sub})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK, (_not_passing(report), _notes(report))
    ids = [o["obligation_id"] for o in report["observations"]]
    assert "locked-tests" in ids


def test_editing_a_colocated_test_to_match_broken_code_is_blocked(
    repo: Path, tmp_path: Path
) -> None:
    _pr(
        repo,
        {
            "src/calc.ts": CALC.replace("a * b", "a * b + 1"),
            "src/calc.test.ts": CALC_TEST.replace("mul(2, 3), 6", "mul(2, 3), 7"),
        },
    )
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "multiplies" in _notes(report)


def test_a_skipped_test_is_blocked(repo: Path, tmp_path: Path) -> None:
    skipped = CALC_TEST.replace('test("multiplies",', 'test.skip("multiplies",')
    _pr(repo, {"src/calc.ts": CALC.replace("a * b", "a + b"), "src/calc.test.ts": skipped})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "weakening" in _not_passing(report)


def test_a_deleted_test_file_is_blocked(repo: Path, tmp_path: Path) -> None:
    _pr(repo, {"src/calc.ts": CALC.replace("a * b", "a + b")}, remove=("src/calc.test.ts",))
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED


def test_a_changed_test_script_or_runner_setting_is_blocked(repo: Path, tmp_path: Path) -> None:
    package = {"name": "calc", "type": "module", "scripts": {"test": "true"}}
    _pr(repo, {"package.json": json.dumps(package), "ohx.toml": 'js_runner = "jest"\n'})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "package.json: check configuration" in _notes(report)


# --- the protected node_modules -----------------------------------------------------------

LIB = "src/lib.ts"
LIB_TEST = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { origin } from "mathlib";

test("packages come from the accepted lockfile", () => {
  assert.equal(origin(), "base lockfile");
});
"""
# Stand-in for npm: checks it was asked for a clean, script-free install, then installs one
# package, which says where it came from.
STAND_IN_NPM = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
assert args[0] == "ci", args
assert "--ignore-scripts" in args, args
lock = json.load(open("package-lock.json"))
pkg = os.path.join("node_modules", "mathlib")
os.makedirs(pkg)
open(os.path.join(pkg, "package.json"), "w").write(
    '{{"name": "mathlib", "type": "module", "main": "index.js"}}'
)
open(os.path.join(pkg, "index.js"), "w").write(
    "export const origin = () => " + json.dumps(lock["origin"]) + ";\\n"
)
"""


@pytest.fixture
def npm_repo(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    npm = tmp_path / "stand-in-npm"
    npm.write_text(STAND_IN_NPM)
    npm.chmod(0o755)
    monkeypatch.setenv("OHX_NPM", str(npm))
    _git(repo, "checkout", "-q", "main")
    lock = {"name": "calc", "lockfileVersion": 3, "origin": "base lockfile"}
    _write(
        repo,
        {
            "ohx.toml": 'environment = "npm"\n',
            "package-lock.json": json.dumps(lock),
            "src/lib.test.ts": LIB_TEST,
        },
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "protected packages")
    _git(repo, "checkout", "-qB", "pr")
    return repo


def _plant(repo: Path, origin: str) -> None:
    """A node_modules in the checkout, as `npm ci` on the pull request would leave it."""
    pkg = repo / "node_modules" / "mathlib"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name": "mathlib", "type": "module", "main": "index.js"}')
    (pkg / "index.js").write_text(f"export const origin = () => {json.dumps(origin)};\n")


def test_checks_use_packages_installed_from_the_base_lockfile(
    npm_repo: Path, tmp_path: Path
) -> None:
    _plant(npm_repo, "pull request's own node_modules")
    _pr(npm_repo, {"README.md": "docs\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK, (_not_passing(report), _notes(report))
    assert not any("node_modules in the candidate" in x for x in report["limitations"])


def test_a_changed_lockfile_runs_nothing_and_is_not_ready(npm_repo: Path, tmp_path: Path) -> None:
    lock = {"name": "calc", "lockfileVersion": 3, "origin": "pull request lockfile"}
    _pr(npm_repo, {"package-lock.json": json.dumps(lock)})
    code, report = _gate(tmp_path)
    assert code != EXIT_OK and report["readiness"] != "ready"
    assert "package-lock.json" in _notes(report)


def test_without_the_protected_environment_the_report_names_the_blind_spot(
    repo: Path, tmp_path: Path
) -> None:
    _plant(repo, "anything")
    _pr(repo, {"README.md": "docs\n"})
    code, report = _gate(tmp_path)
    assert code == EXIT_OK
    assert any("node_modules in the candidate" in x for x in report["limitations"])


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_the_typescript_gate_under_srt(npm_repo: Path, tmp_path: Path) -> None:
    _pr(npm_repo, {"src/calc.ts": CALC.replace("a * b", "a * b + 1")})
    code, report = _gate(tmp_path, "srt")
    assert code == EXIT_BLOCKED
    assert report["protection"]["verifier"].startswith("enforced")
    (tmp_path / "gate-out").rename(tmp_path / "blocked-out")
    _git(npm_repo, "checkout", "-q", "main")
    _git(npm_repo, "checkout", "-qB", "pr2")
    _pr(npm_repo, {"README.md": "docs\n"})
    code, report = _gate(tmp_path, "srt")
    assert code == EXIT_OK, (_not_passing(report), _notes(report))
