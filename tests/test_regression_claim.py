""" "No regressions" is claimed only when a regression check ran (T93, contracts/0051).

Found by a simulated user trial (2026-10-05, TypeScript developer on unjs/ufo): after
`ohx init --lock-tests` and then `ohx contract new --acceptance ...`, the new contract
held the acceptance test, the weakening check and mutation, and no regression suite:
`ohx contract new` added the project's suite only for a Python `tests/` folder. A change
that broke 4 other tests was READY, and the report said "No regressions: yes, every test
that passed before still passes", because the claim counted every passing check that was
not acceptance, the weakening check included.

Now `ohx contract new` adds the project's whole suite as a regression check for
TypeScript, JavaScript and Go projects too, as `ohx gate` and `ohx init --lock-tests`
already do, and the no-regressions claim is made only from regression checks: with none,
the report says "not checked".
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

URL = """\
export function withSlash(path) {
  return path.endsWith("/") ? path : path + "/";
}

export function withoutSlash(path) {
  return path.endsWith("/") ? path.slice(0, -1) || "/" : path;
}
"""
URL_TESTS = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { withSlash, withoutSlash } from "../src/url.js";

test("adds a slash", () => assert.equal(withSlash("/a"), "/a/"));
test("keeps the root", () => assert.equal(withoutSlash("/"), "/"));
test("removes a slash", () => assert.equal(withoutSlash("/a/"), "/a"));
"""
ISSUE_TEST = """\
import { test } from "node:test";
import assert from "node:assert/strict";
import { withSlash } from "../src/url.js";

test("keeps the query", () => assert.equal(withSlash("/a?x=1"), "/a/?x=1"));
"""
FIXED = URL.replace(
    '  return path.endsWith("/") ? path : path + "/";',
    '  const [p, q] = path.split("?");\n'
    '  const slashed = p.endsWith("/") ? p : p + "/";\n'
    '  return q === undefined ? slashed : slashed + "?" + q;',
)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def js(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "test").mkdir()
    (repo / "src" / "url.js").write_text(URL)
    (repo / "test" / "url.test.js").write_text(URL_TESTS)
    (repo / "package.json").write_text('{"name": "url", "type": "module"}\n')
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "test" / "issue.test.js").write_text(ISSUE_TEST)
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _report(tmp_path: Path) -> tuple[dict[str, Any], str]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    return json.loads(runs[-1].read_text()), (runs[-1].parent / "report.md").read_text()


def _contract() -> None:
    args = ["contract", "new", "--mode", "bugfix", "--title", "Keep the query", "--summary", "s"]
    assert main([*args, "--acceptance", "test/issue.test.js", "--accept", "--sandbox", "none"]) == 0


@needs_node
def test_after_the_lock_an_acceptance_contract_still_checks_the_whole_suite(
    js: Path, tmp_path: Path
) -> None:
    assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
    _contract()
    (js / "src" / "url.js").write_text(FIXED.replace('|| "/"', '|| ""'))  # fixed, and broken
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["readiness"] == "blocked"
    assert report["claims"]["no_regressions"] is False
    assert "keeps the root" in json.dumps(report["observations"])
    assert "No regressions: yes" not in markdown


@needs_node
def test_the_genuine_fix_is_ready_with_both_claims(js: Path, tmp_path: Path) -> None:
    assert main(["init"]) == EXIT_OK
    _contract()
    (js / "src" / "url.js").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _ = _report(tmp_path)
    assert report["readiness"] == "ready"
    assert report["claims"]["no_regressions"] is True
    assert report["claims"]["acceptance"] == "met"


def test_without_a_regression_check_no_regressions_is_not_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "py"
    (repo / "acceptance").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "acceptance" / "test_add.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\nobligations = []\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    assert (
        main([*args, "--acceptance", "acceptance/test_add.py", "--accept", "--sandbox", "none"])
        == 0
    )
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown = _report(tmp_path)
    assert report["claims"]["no_regressions"] is None
    assert "No regressions: not checked" in markdown


@needs_node
def test_a_test_that_already_failed_does_not_block_a_genuine_fix(js: Path, tmp_path: Path) -> None:
    broken = 'test("known bug", () => assert.equal(withSlash(""), "/"));\n'
    (js / "test" / "url.test.js").write_text(URL_TESTS + broken.replace('"/"', '"//"'))
    _git(js, "commit", "-qam", "a test that already fails")
    assert main(["init"]) == EXIT_OK
    _contract()
    (js / "src" / "url.js").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _ = _report(tmp_path)
    assert report["readiness"] == "ready" and report["claims"]["no_regressions"] is True
