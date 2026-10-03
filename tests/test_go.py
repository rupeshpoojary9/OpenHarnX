"""Acceptance tests for Go (T82 slice 3, contracts/0032).

- Weakening: new `//nolint`, `//lint:ignore`, `#nosec`, `t.Skip`, a build constraint
  added to a test file (it can switch the file off), fewer `Test`/`Fuzz`/`Example`
  functions or `t.Error`/`t.Fatal`/`assert`/`require` calls, removed `_test.go` files, and
  changed golangci-lint or staticcheck configuration. Baselines made before Go support
  (versions 1 and 2) are compared as they were.
- Per-test results from `go test -json` (`package::Test/sub`). A test reported both
  passing and failing counts as failing, so a test cannot print its own pass.
- `ohx gate` locks every `_test.go` file of the base at its path and runs
  `go test -json ./...`; `ohx contract new --acceptance x_test.go` locks the file and runs
  its package. Go runs with GOTOOLCHAIN=local (no toolchain download) and its build cache
  in the run's temporary folder.

The text checks run anywhere; the runs need Go (`go` on PATH).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main
from openharnx.regression import read_go_results
from openharnx.weakening import compare, snapshot

CALC = """\
package calc

func Add(a, b int) int {
	return a + b
}

func Mul(a, b int) int {
	return a * b
}
"""
CALC_TEST = """\
package calc

import "testing"

func TestAdd(t *testing.T) {
	if got := Add(2, 3); got != 5 {
		t.Fatalf("Add(2, 3) = %d", got)
	}
}

func TestMul(t *testing.T) {
	if got := Mul(2, 3); got != 6 {
		t.Errorf("Mul(2, 3) = %d", got)
	}
}
"""


def _tree(root: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _base(root: Path) -> dict[str, Any]:
    files = {"calc/calc.go": CALC, "calc/calc_test.go": CALC_TEST, "go.mod": "module x\n"}
    return snapshot(root, _tree(root, files))


def _findings(root: Path, baseline: dict[str, Any], files: dict[str, str]) -> list[str]:
    return compare(baseline, snapshot(root, _tree(root, files)))


@pytest.mark.parametrize(
    "rel, change",
    [
        ("calc/calc.go", ("return a + b", "return a + b //nolint:all")),
        ("calc/calc.go", ("func Add", "//lint:ignore U1000 reason\nfunc Add")),
        ("calc/calc.go", ("return a + b", "return a + b // #nosec G404")),
        (
            "calc/calc_test.go",
            ("func TestMul(t *testing.T) {", "func TestMul(t *testing.T) {\n\tt.Skip()"),
        ),
        ("calc/calc_test.go", ("package calc", "//go:build never\n\npackage calc")),
    ],
)
def test_new_go_suppressions_skips_and_constraints_are_found(
    tmp_path: Path, rel: str, change: tuple[str, str]
) -> None:
    baseline = _base(tmp_path)
    text = (tmp_path / rel).read_text().replace(*change)
    found = _findings(tmp_path, baseline, {rel: text})
    assert any(f.startswith(f"{rel}: 1 new") for f in found), found


def test_fewer_go_tests_or_checks_and_removed_test_files_are_found(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    fewer = CALC_TEST.replace('\t\tt.Errorf("Mul(2, 3) = %d", got)\n', "")
    found = _findings(tmp_path, baseline, {"calc/calc_test.go": fewer})
    assert any("fewer assertions" in f for f in found), found
    one = CALC_TEST.split("func TestMul")[0]
    found = _findings(tmp_path, baseline, {"calc/calc_test.go": one})
    assert any("fewer tests" in f for f in found), found
    (tmp_path / "calc" / "calc_test.go").unlink()
    found = compare(baseline, snapshot(tmp_path, _tree(tmp_path, {})))
    assert any("calc/calc_test.go: test file removed" in f for f in found), found


@pytest.mark.parametrize("rel", [".golangci.yml", ".golangci.toml", "staticcheck.conf"])
def test_changed_go_checker_configuration_is_found(tmp_path: Path, rel: str) -> None:
    baseline = _base(tmp_path)
    found = _findings(tmp_path, baseline, {rel: "linters:\n  disable-all: true\n"})
    assert any(f.startswith(f"{rel}: check configuration") for f in found), found


def test_ordinary_go_changes_need_no_approval(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    new_test = 'package calc\n\nimport "testing"\n\nfunc TestSub(t *testing.T) {\n'
    new_test += '\tif Sub(5, 3) != 2 {\n\t\tt.Fatal("Sub")\n\t}\n}\n'
    files = {
        "calc/calc.go": CALC + "\nfunc Sub(a, b int) int {\n\treturn a - b\n}\n",
        "calc/sub_test.go": new_test,
        "calc/calc_linux.go": "//go:build linux\n\npackage calc\n",  # not a test file
        "go.mod": "module x\n\ngo 1.22\n",
    }
    assert _findings(tmp_path, baseline, files) == []


def test_baselines_made_before_go_support_are_compared_as_before(tmp_path: Path) -> None:
    baseline = _base(tmp_path)
    old = {
        "version": 2,
        "config": {},
        "suppressions": {},
        "tests": {k: v for k, v in baseline["tests"].items() if not k.endswith(".go")},
    }
    files = {"calc/calc.go": CALC.replace("a + b", "a + b //nolint"), ".golangci.yml": "x\n"}
    assert _findings(tmp_path, old, files) == []


# --- per-test results from go test -json --------------------------------------------------


def _events(*events: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(e).encode() + b"\n" for e in events)


def test_go_test_json_gives_per_test_results() -> None:
    out = (
        _events(
            {"Action": "run", "Package": "x/calc", "Test": "TestAdd"},
            {"Action": "fail", "Package": "x/calc", "Test": "TestAdd"},
            {"Action": "skip", "Package": "x/calc", "Test": "TestSkip"},
            {"Action": "pass", "Package": "x/calc", "Test": "TestSub/inner"},
            {"Action": "pass", "Package": "x/calc", "Test": "TestSub"},
            {"Action": "fail", "Package": "x/calc"},
        )
        + b"# x/other\nother/broken.go:3:1: syntax error\n"
    )
    assert read_go_results(out) == {
        "x/calc::TestAdd": "fail",
        "x/calc::TestSkip": "skip",
        "x/calc::TestSub/inner": "pass",
        "x/calc::TestSub": "pass",
    }
    assert read_go_results(b"plain output, no events\n") is None


def test_a_test_cannot_print_its_own_pass() -> None:
    out = _events(
        {"Action": "fail", "Package": "x/calc", "Test": "TestAdd"},
        {"Action": "pass", "Package": "x/calc", "Test": "TestAdd"},  # printed by the test
    )
    assert read_go_results(out) == {"x/calc::TestAdd": "fail"}


# --- runs ----------------------------------------------------------------------------------

needs_go = pytest.mark.skipif(shutil.which("go") is None, reason="needs Go")


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calc: str = CALC) -> Path:
    repo = tmp_path / "proj"
    _tree(
        repo,
        {
            "go.mod": "module example.com/proj\n\ngo 1.22\n",
            "calc/calc.go": calc,
            "calc/calc_test.go": CALC_TEST,
        },
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _pr(repo: Path, files: dict[str, str]) -> None:
    _git(repo, "checkout", "-qB", "pr")
    _tree(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def _gate(tmp_path: Path, sandbox: str = "none") -> tuple[int, dict[str, Any]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", sandbox, "--out", str(out)])
    return code, json.loads((out / "report.json").read_text())


def _notes(report: dict[str, Any]) -> str:
    return " ".join(o["note"] for o in report["observations"])


@needs_go
def test_a_genuine_go_change_is_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    sub = 'package calc\n\nimport "testing"\n\nfunc TestSub(t *testing.T) {\n'
    sub += '\tif Sub(5, 3) != 2 {\n\t\tt.Fatal("Sub")\n\t}\n}\n'
    _pr(
        repo,
        {
            "calc/calc.go": CALC + "\nfunc Sub(a, b int) int {\n\treturn a - b\n}\n",
            "calc/sub_test.go": sub,
        },
    )
    code, report = _gate(tmp_path)
    assert code == EXIT_OK, _notes(report)
    assert "locked-tests" in [o["obligation_id"] for o in report["observations"]]


@needs_go
def test_editing_a_go_test_to_match_broken_code_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch)
    _pr(
        repo,
        {
            "calc/calc.go": CALC.replace("a * b", "a*b + 1"),
            "calc/calc_test.go": CALC_TEST.replace("got != 6", "got != 7"),
        },
    )
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "example.com/proj/calc::TestMul passed at acceptance and fails" in _notes(report)


@needs_go
def test_skipping_a_go_test_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    skipped = CALC_TEST.replace(
        "func TestMul(t *testing.T) {", "func TestMul(t *testing.T) {\n\tt.Skip()"
    )
    _pr(repo, {"calc/calc.go": CALC.replace("a * b", "a + b"), "calc/calc_test.go": skipped})
    code, report = _gate(tmp_path)
    assert code == EXIT_BLOCKED
    assert "skipped test" in _notes(report)


@needs_go
def test_a_go_acceptance_test_is_locked_and_runs_its_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, calc=CALC.replace("a * b", "a + b"))
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix Mul", "--summary", "Mul multiplies"]
    assert main([*new, "--acceptance", "calc/calc_test.go", "--accept", "--sandbox", "none"]) == 0
    contract = sorted((repo / "contracts").glob("*.toml"))[-1].read_text()
    assert 'protected_at = "calc/calc_test.go"' in contract and '"./calc"' in contract
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    (repo / "calc" / "calc_test.go").write_text(CALC_TEST.replace("got != 6", "got != 5"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED  # the locked copy runs
    (repo / "calc" / "calc_test.go").write_text(CALC_TEST)
    (repo / "calc" / "calc.go").write_text(CALC)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


@needs_go
@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_the_go_gate_under_srt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    _pr(repo, {"calc/calc.go": CALC.replace("a * b", "a*b + 1")})
    code, report = _gate(tmp_path, "srt")
    assert code == EXIT_BLOCKED
    assert report["protection"]["verifier"].startswith("enforced")
    _git(repo, "checkout", "-q", "main")
    (tmp_path / "gate-out").rename(tmp_path / "first")
    _pr(repo, {"README.md": "docs\n"})
    code, report = _gate(tmp_path, "srt")
    assert code == EXIT_OK, _notes(report)
