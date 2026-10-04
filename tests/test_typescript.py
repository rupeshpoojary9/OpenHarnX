"""Acceptance tests for TypeScript and JavaScript, local verification (T82 slice 1, contracts/0029).

The gate was Python only: the weakening check knew `# noqa` and
`pytest.mark.skip` but not `// @ts-ignore` or `it.skip`, acceptance tests
always ran with pytest, and per-test results came only from pytest.

Now:
- The weakening check also finds new `@ts-ignore`, `@ts-expect-error`,
  `@ts-nocheck`, `eslint-disable`, `biome-ignore`, skipped or focused tests
  (`.skip`, `.only`, `xit`, `{ skip: true }`, `test.fails`), fewer tests or
  `expect`/`assert` calls, removed test files, and changed checker
  configuration (`tsconfig*.json`, Vitest, Jest, ESLint, Biome, Babel and Vite
  config, and the checker scripts and settings in `package.json`). Baselines
  made before this change compare Python only, so old contracts are unchanged.
- A TypeScript or JavaScript acceptance test is locked and runs at its own
  path in a copy of the tree, because it imports the code next to it. The
  runner is Vitest or Jest when the project has it, else `node --test`.
- Any runner that writes JUnit XML gives per-test results through the
  `{junit}` placeholder; Node's results are named by file.

Self-contained: TypeScript runs through Node's own test runner (Node 22.18 or
later strips types). Real Vitest runs when OHX_VITEST_NODE_MODULES names a
node_modules folder that has it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main
from openharnx.regression import read_results
from openharnx.weakening import compare, snapshot


def _node_strips_types() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    m = re.match(r"v(\d+)\.(\d+)", out)
    return m is not None and (int(m.group(1)), int(m.group(2))) >= (22, 18)


needs_node = pytest.mark.skipif(not _node_strips_types(), reason="needs Node 22.18 or later")


def _node_junit_names_files() -> bool:
    """Node 24 writes each test's file into its JUnit report; Node 22 does not."""
    if not _node_strips_types():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.test.mjs").write_text(
            'import { test } from "node:test";\ntest("t", () => {});\n'
        )
        subprocess.run(
            [
                "node",
                "--test",
                "--test-reporter=junit",
                "--test-reporter-destination=j.xml",
                "a.test.mjs",
            ],
            cwd=tmp,
            capture_output=True,
        )
        report = Path(tmp) / "j.xml"
        return report.is_file() and "file=" in report.read_text()


# --- the weakening check, on files ---------------------------------------------------------

SOURCE = "export function add(a: number, b: number): number {\n  return a + b;\n}\n"
TEST = """\
import { describe, expect, it } from "vitest";
import { add } from "./calc";

describe("add", () => {
  it("adds", () => {
    expect(add(2, 3)).toBe(5);
  });
  it("adds negatives", () => {
    expect(add(-2, -3)).toBe(-5);
  });
});
"""
PACKAGE: dict[str, Any] = {
    "name": "calc",
    "version": "1.0.0",
    "scripts": {"test": "vitest run", "build": "tsc"},
    "devDependencies": {"vitest": "^3.0.0"},
}


def _tree(root: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _base(root: Path) -> dict[str, Any]:
    files = {
        "src/calc.ts": SOURCE,
        "src/calc.test.ts": TEST,
        "package.json": json.dumps(PACKAGE),
        "tsconfig.json": '{"compilerOptions": {"strict": true}}\n',
    }
    return snapshot(root, _tree(root, files))


def _findings(root: Path, baseline: dict[str, Any], files: dict[str, str]) -> list[str]:
    paths = _tree(root, files)
    return compare(baseline, snapshot(root, paths))


@pytest.mark.parametrize(
    "line",
    [
        "// @ts-ignore",
        "// @ts-expect-error",
        "// @ts-nocheck",
        "// eslint-disable-next-line @typescript-eslint/no-explicit-any",
        "/* eslint-disable */",
        "// biome-ignore lint: reason",
    ],
)
def test_new_typescript_suppressions_are_found(tmp_path: Path, line: str) -> None:
    baseline = _base(tmp_path)
    found = _findings(tmp_path, baseline, {"src/calc.ts": line + "\n" + SOURCE})
    assert found and all(f.startswith("src/calc.ts: 1 new") for f in found), found


@pytest.mark.parametrize(
    "change",
    [
        ('it("adds",', 'it.skip("adds",'),
        ('it("adds",', 'it.only("adds",'),
        ('describe("add",', 'describe.skip("add",'),
        ('it("adds",', 'xit("adds",'),
        ('it("adds",', 'it("adds", { skip: true },'),
        ('it("adds",', 'test.fails("adds",'),
    ],
)
def test_skipped_or_focused_tests_are_found(tmp_path: Path, change: tuple[str, str]) -> None:
    baseline = _base(tmp_path)
    found = _findings(tmp_path, baseline, {"src/calc.test.ts": TEST.replace(*change)})
    assert any("src/calc.test.ts" in f for f in found), found


def test_fewer_tests_or_assertions_and_removed_test_files_are_found(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    fewer = TEST.replace("    expect(add(-2, -3)).toBe(-5);\n", "")
    assert any(
        "fewer assertions" in f for f in _findings(tmp_path, baseline, {"src/calc.test.ts": fewer})
    )
    one = TEST.split('  it("adds negatives"')[0] + "});\n"
    assert any("fewer tests" in f for f in _findings(tmp_path, baseline, {"src/calc.test.ts": one}))
    (tmp_path / "src" / "calc.test.ts").unlink()
    found = compare(baseline, snapshot(tmp_path, _tree(tmp_path, {})))
    assert any("src/calc.test.ts: test file removed" in f for f in found), found


@pytest.mark.parametrize(
    "rel, text",
    [
        ("tsconfig.json", '{"compilerOptions": {"strict": false}}\n'),
        ("tsconfig.build.json", '{"extends": "./tsconfig.json"}\n'),
        ("vitest.config.ts", "export default { test: { passWithNoTests: true } };\n"),
        ("vite.config.ts", "export default { test: { exclude: ['src/**'] } };\n"),
        ("jest.config.js", "module.exports = { testPathIgnorePatterns: ['src'] };\n"),
        ("eslint.config.js", "export default [];\n"),
        ("biome.json", "{}\n"),
        ("vitest.setup.ts", "globalThis.expect = () => ({ toBe() {} });\n"),
        (
            "package.json",
            json.dumps({**PACKAGE, "scripts": {**PACKAGE["scripts"], "test": "true"}}),
        ),
        ("package.json", json.dumps({**PACKAGE, "jest": {"bail": 0}})),
    ],
)
def test_changed_checker_configuration_is_found(tmp_path: Path, rel: str, text: str) -> None:
    baseline = _base(tmp_path)
    found = _findings(tmp_path, baseline, {rel: text})
    assert any(f.startswith(f"{rel}: check configuration") for f in found), found


def test_ordinary_changes_need_no_approval(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    package = {**PACKAGE, "version": "1.1.0", "dependencies": {"zod": "^3.0.0"}}
    package["scripts"] = {**PACKAGE["scripts"], "build": "tsc -p tsconfig.json"}
    new_test = (
        'import { it, expect } from "vitest";\n\nit("x", () => {\n  expect(1).toBe(1);\n});\n'
    )
    files = {
        "src/calc.ts": SOURCE + "\nexport const sub = (a: number, b: number) => a - b;\n",
        "src/sub.test.ts": new_test,
        "package.json": json.dumps(package),
        "README.md": "docs\n",
    }
    assert _findings(tmp_path, baseline, files) == []


def test_baselines_made_before_typescript_support_compare_python_only(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    old = {
        "version": 1,
        "config": {k: v for k, v in baseline["config"].items() if k.endswith(".toml")},
        "suppressions": {k: v for k, v in baseline["suppressions"].items() if k.endswith(".py")},
        "tests": {k: v for k, v in baseline["tests"].items() if k.endswith(".py")},
    }
    files = {"src/calc.ts": "// @ts-ignore\n" + SOURCE, "tsconfig.json": "{}\n"}
    assert _findings(tmp_path, old, files) == []


# --- verification, end to end --------------------------------------------------------------

BUGGY = "export function add(a: number, b: number): number {\n  return a - b;\n}\n"
FIXED = SOURCE
NODE_TEST = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { add } from "./calc.ts";

test("adds", () => {
  assert.equal(add(2, 3), 5);
});
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str], ohx_toml: str = ""
) -> Path:
    repo = tmp_path / "proj"
    _tree(repo, {"package.json": json.dumps({"name": "calc", "type": "module"}), **files})
    (repo / ".gitignore").write_text("node_modules\n")
    (repo / "ohx.toml").write_text(ohx_toml)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


def _accept(*tests: str) -> None:
    new = ["contract", "new", "--title", "Fix add", "--summary", "add adds"]
    for t in tests:
        new += ["--acceptance", t]
    assert main([*new, "--accept", "--sandbox", "none"]) == EXIT_OK


def _verify(sandbox: str = "none") -> tuple[int, dict[str, Any]]:
    code = main(["verify", "--sandbox", sandbox])
    home = Path(os.environ["OHX_HOME"])
    reports = sorted(home.glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime)
    return code, json.loads(reports[-1].read_text())


def _observation(report: dict[str, Any], prefix: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = [
        o for o in report["observations"] if o["obligation_id"].startswith(prefix)
    ]
    assert found, [o["obligation_id"] for o in report["observations"]]
    return found[0]


@needs_node
def test_a_typescript_acceptance_test_is_locked_and_runs_at_its_own_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, {"src/calc.ts": BUGGY, "src/calc.test.ts": NODE_TEST})
    _accept("src/calc.test.ts")
    contract = sorted((repo / "contracts").glob("*.toml"))[-1].read_text()
    assert 'protected_at = "src/calc.test.ts"' in contract
    assert '"node", "--test"' in contract
    code, report = _verify()
    assert code == EXIT_BLOCKED and report["readiness"] == "blocked"

    (repo / "src" / "calc.ts").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK, [o["note"] for o in report["observations"]]
    assert "Python only" in _observation(report, "mutation")["note"]


@needs_node
def test_editing_the_locked_typescript_test_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, {"src/calc.ts": BUGGY, "src/calc.test.ts": NODE_TEST})
    _accept("src/calc.test.ts")
    (repo / "src" / "calc.test.ts").write_text(NODE_TEST.replace("5);", "-1);"))
    code, report = _verify()
    assert code == EXIT_BLOCKED
    assert _observation(report, "acceptance")["outcome"] == "fail"


OTHER = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { add } from "./calc.ts";

test("adds", () => {
  assert.equal(add(1, 1), 2);
});

test("known broken", () => {
  assert.equal(0.1 + 0.2, 0.3);
});
"""
SUITE = (
    "[[obligations]]\n"
    'id = "tests"\nkind = "regression"\nmandatory = false\n'
    'command = ["node", "--test", "--test-reporter=junit",'
    ' "--test-reporter-destination={junit}", "src/*.test.ts"]\n'
)


@pytest.mark.skipif(not _node_junit_names_files(), reason="this Node does not name test files")
def test_per_test_results_come_from_the_junit_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"src/calc.ts": FIXED, "src/calc.test.ts": NODE_TEST, "src/other.test.ts": OTHER}
    repo = _repo(tmp_path, monkeypatch, files, SUITE)
    _accept("src/calc.test.ts")
    # A failure already there before the change is named, not blocking: only possible
    # with per-test results, since the suite as a whole was already failing.
    (repo / "src" / "calc.ts").write_text(FIXED + "\nexport const one = 1;\n")
    code, report = _verify()
    assert code == EXIT_OK
    note = _observation(report, "no-new-failures")["note"]
    assert "src/other.test.ts::known broken" in note, note

    # Breaking a test that passed: named by file, though both files have a test "adds".
    (repo / "src" / "calc.ts").write_text(FIXED.replace("a + b", "a + b + (a === 1 ? 1 : 0)"))
    code, report = _verify()
    assert code == EXIT_BLOCKED
    note = _observation(report, "no-new-failures")["note"]
    assert "src/other.test.ts::adds passed at acceptance and fails" in note, note
    assert "src/calc.test.ts::adds" not in note


# Node 22's JUnit report, as written on Linux in the ohx-linux image (2026-10-03): no file
# names, so two files with a test "adds" give the same id twice.
NODE_22_REPORT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testcase name="adds" time="0.0004" classname="test"/>
  <testsuite name="d" tests="1"><testcase name="x" time="0.0001" classname="test"/></testsuite>
  <testcase name="adds" time="0.0004" classname="test"><failure message="5 !== 6"/></testcase>
  <testsuite name="d" tests="1"><testcase name="x" time="0.0001" classname="test"/></testsuite>
</testsuites>
"""


def test_node_results_that_cannot_be_told_apart_are_not_used(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(NODE_22_REPORT)
    # Per-test results would merge two different tests; the whole suite is compared instead.
    assert read_results(report, tmp_path) is None
    unique = NODE_22_REPORT.replace(
        'name="adds" time="0.0004" classname="test">',
        'name="adds 2" time="0.0004" classname="test">',
    )
    unique = unique.replace(
        '<testsuite name="d" tests="1"><testcase name="x"',
        '<testsuite name="e" tests="1"><testcase name="x"',
        1,
    )
    assert read_results(report.parent / "missing.xml") is None
    report.write_text(unique)
    assert read_results(report, tmp_path) == {
        "test::adds": "pass",
        "test::e > x": "pass",
        "test::adds 2": "fail",
        "test::d > x": "pass",
    }


@needs_node
def test_a_new_ts_ignore_is_listed_when_no_type_checker_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Node strips types without checking them, so with only `node --test` in the
    # contract a @ts-ignore lowers no bar; it is listed, not counted (T90a).
    repo = _repo(tmp_path, monkeypatch, {"src/calc.ts": BUGGY, "src/calc.test.ts": NODE_TEST})
    _accept("src/calc.test.ts")
    (repo / "src" / "calc.ts").write_text("// @ts-ignore\n" + FIXED)
    code, report = _verify()
    assert code == EXIT_OK
    assert "not counted" in _observation(report, "weakening")["note"]


@needs_node
@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_typescript_under_srt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch, {"src/calc.ts": BUGGY, "src/calc.test.ts": NODE_TEST})
    _accept("src/calc.test.ts")
    assert _verify("srt")[0] == EXIT_BLOCKED
    (repo / "src" / "calc.ts").write_text(FIXED)
    code, report = _verify("srt")
    assert code == EXIT_OK
    assert report["protection"]["verifier"].startswith("enforced")


GREETING_TEST = (
    NODE_TEST.replace(
        'import { add } from "./calc.ts";',
        'import { add } from "./calc.ts";\nimport { hi } from "greet";',
    )
    + 'test("greets", () => {\n  assert.equal(hi(), "hi");\n});\n'
)


@needs_node
def test_packages_in_node_modules_resolve_from_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {"src/calc.ts": BUGGY, "src/calc.test.ts": GREETING_TEST}
    repo = _repo(tmp_path, monkeypatch, files)
    package = repo / "node_modules" / "greet"  # git-ignored, so not in the copy by itself
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"name": "greet", "type": "module", "main": "index.js"}')
    (package / "index.js").write_text('export const hi = () => "hi";\n')
    _accept("src/calc.test.ts")
    (repo / "src" / "calc.ts").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK, [o["note"] for o in report["observations"]]
    assert any("node_modules" in limit for limit in report["limitations"])


VITEST = """\
import { expect, it } from "vitest";
import { add } from "./calc";

it("adds", () => {
  expect(add(2, 3)).toBe(5);
});
"""


@pytest.mark.skipif(
    not os.environ.get("OHX_VITEST_NODE_MODULES"),
    reason="set OHX_VITEST_NODE_MODULES to a node_modules folder with vitest",
)
def test_vitest_is_used_when_the_project_has_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, {"src/calc.ts": BUGGY, "src/calc.test.ts": VITEST})
    (repo / "node_modules").symlink_to(os.environ["OHX_VITEST_NODE_MODULES"])
    _accept("src/calc.test.ts")
    contract = sorted((repo / "contracts").glob("*.toml"))[-1].read_text()
    assert "node_modules/.bin/vitest" in contract
    assert _verify()[0] == EXIT_BLOCKED
    (repo / "src" / "calc.ts").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK, [o["note"] for o in report["observations"]]
    assert any("node_modules" in limit for limit in report["limitations"])
