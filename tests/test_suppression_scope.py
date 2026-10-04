"""Suppressions count only for checkers the contract runs; conditional skips are not
suppressions (T90a, contracts/0044).

Found by replaying the gate over 29 Copilot pull requests of github/spec-kit
(2026-10-04): 2 of 20 merged ones were blocked only by the weakening check, for
`# noqa: BLE001`, `# type: ignore[union-attr]` and skips such as
`@pytest.mark.skipif(not hasattr(os, "symlink"))` in new tests. The gate's contract
ran only pytest, so the comments lowered no bar it checked, and a skip that depends on
the platform skips nothing on the platform where it matters.

Now a suppression counts when the contract runs the checker it silences (`noqa` with
ruff or flake8, `type: ignore` with mypy or pyright, `pragma: no cover` with coverage,
and so on), and every suppression counts when a command is not recognised, such as a
script. Unconditional skips (`@pytest.mark.skip`, a bare `pytest.skip()`, `xfail`
without a condition) still count everywhere; conditional ones (`skipif` with a
condition, a skip inside an `if` or `except`, `importorskip`) do not. Skipping a test
that passed is still caught by the no-new-failures check. Suppressions not counted are
listed in the report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.weakening import active_checkers, compare, snapshot


def _found(
    before: str, after: str, tmp_path: Path, rel: str, active: frozenset[str] | None = None
) -> list[str]:
    a, b = tmp_path / "a", tmp_path / "b"
    for root, text in ((a, before), (b, after)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return compare(snapshot(a, [rel]), snapshot(b, [rel]), active)


TEST_BASE = "import os\nimport sys\n\nimport pytest\nimport unittest\n\n\ndef test_a():\n    pass\n"


@pytest.mark.parametrize(
    "added",
    [
        '@pytest.mark.skipif(sys.platform == "win32", reason="chmod")\ndef test_b():\n    pass\n',
        "@pytest.mark.xfail(sys.version_info < (3, 11), reason='old')\ndef test_b():\n    pass\n",
        "def test_b():\n    if not hasattr(os, 'symlink'):\n        pytest.skip('no symlinks')\n",
        "def test_b():\n    try:\n        os.symlink('a', 'b')\n    except OSError:\n"
        "        pytest.skip('cannot create symlinks')\n",
        "def test_b():\n    np = pytest.importorskip('numpy')\n",
        "class T(unittest.TestCase):\n    @unittest.skipIf(sys.platform == 'win32', 'x')\n"
        "    def test_b(self):\n        pass\n",
        "class T(unittest.TestCase):\n    @unittest.skipUnless(hasattr(os, 'fork'), 'x')\n"
        "    def test_b(self):\n        pass\n",
    ],
)
def test_conditional_skips_are_not_suppressions(tmp_path: Path, added: str) -> None:
    rel = "tests/test_x.py"
    assert _found(TEST_BASE, TEST_BASE + "\n\n" + added, tmp_path, rel) == []


@pytest.mark.parametrize(
    "added",
    [
        '@pytest.mark.skip(reason="flaky")\ndef test_b():\n    pass\n',
        "@pytest.mark.skip\ndef test_b():\n    pass\n",
        "@pytest.mark.xfail\ndef test_b():\n    pass\n",
        "@pytest.mark.xfail(reason='later')\ndef test_b():\n    pass\n",
        "@pytest.mark.skipif(True, reason='x')\ndef test_b():\n    pass\n",
        "def test_b():\n    pytest.skip('not now')\n",
        "def test_b():\n    pytest.xfail('not now')\n",
        "pytestmark = pytest.mark.skip(reason='all')\n",
        "class T(unittest.TestCase):\n    @unittest.skip('x')\n"
        "    def test_b(self):\n        pass\n",
        "class T(unittest.TestCase):\n    @unittest.expectedFailure\n    def test_b(self):\n"
        "        pass\n",
        "class T(unittest.TestCase):\n    def test_b(self):\n        self.skipTest('x')\n",
    ],
)
def test_unconditional_skips_still_count(tmp_path: Path, added: str) -> None:
    rel = "tests/test_x.py"
    assert _found(TEST_BASE, TEST_BASE + "\n\n" + added, tmp_path, rel) == [
        f"{rel}: 1 new skip or xfail"
    ]


SOURCE = "def f():\n    return 1\n"
SUPPRESSED = (
    "def f():  # noqa: C901\n    x = g()  # type: ignore[attr-defined]\n"
    "    return 1  # pragma: no cover\n"
)


def test_suppressions_for_checkers_the_contract_does_not_run_are_not_counted(
    tmp_path: Path,
) -> None:
    assert _found(SOURCE, SUPPRESSED, tmp_path, "m.py", frozenset({"pytest"})) == []


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        (frozenset({"pytest", "ruff"}), ["m.py: 1 new noqa"]),
        (frozenset({"pytest", "flake8"}), ["m.py: 1 new noqa"]),
        (frozenset({"mypy"}), ["m.py: 1 new type: ignore"]),
        (frozenset({"pyright"}), ["m.py: 1 new type: ignore"]),
        (frozenset({"coverage"}), ["m.py: 1 new pragma: no cover"]),
        (None, ["m.py: 1 new noqa", "m.py: 1 new pragma: no cover", "m.py: 1 new type: ignore"]),
    ],
)
def test_suppressions_count_for_the_checkers_that_run(
    tmp_path: Path, active: frozenset[str] | None, expected: list[str]
) -> None:
    assert _found(SOURCE, SUPPRESSED, tmp_path, "m.py", active) == expected


def test_typescript_and_go_suppressions_follow_their_checkers(tmp_path: Path) -> None:
    ts_before, ts_after = (
        "export const a = 1;\n",
        "// @ts-ignore\n// eslint-disable-next-line\nexport const a = 1;\n",
    )
    assert _found(ts_before, ts_after, tmp_path / "t", "a.ts", frozenset({"vitest"})) == []
    assert _found(ts_before, ts_after, tmp_path / "u", "a.ts", frozenset({"tsc"})) == [
        "a.ts: 1 new @ts-ignore"
    ]
    go_before, go_after = "package a\n", "package a\n\nvar x = 1 //nolint\n"
    assert _found(go_before, go_after, tmp_path / "g", "a.go", frozenset({"go"})) == []
    assert _found(go_before, go_after, tmp_path / "h", "a.go", frozenset({"golangci-lint"})) == [
        "a.go: 1 new nolint"
    ]


def test_source_checks_and_test_counts_ignore_which_checkers_run(tmp_path: Path) -> None:
    patch = "import random\nrandom.randint = lambda a, b: 0\n"
    assert _found("x = 1\n", patch, tmp_path, "m.py", frozenset()) == [
        "m.py: 1 new patch of an imported module"
    ]


def _ob(*command: str) -> dict[str, Any]:
    return {"id": "x", "kind": "check", "mandatory": True, "command": list(command)}


@pytest.mark.parametrize(
    ("commands", "expected"),
    [
        ([["{python}", "-m", "pytest", "-q", "tests"]], {"pytest"}),
        ([["{python}", "-m", "ruff", "check", "."], ["{python}", "-m", "mypy"]], {"ruff", "mypy"}),
        ([["uv", "run", "flake8", "src"]], {"flake8"}),
        ([["{bindir}/pyright"]], {"pyright"}),
        ([["{python}", "-m", "pytest", "--cov=src", "tests"]], {"pytest", "coverage"}),
        ([["{python}", "-m", "coverage", "run", "-m", "pytest"]], {"coverage", "pytest"}),
        ([["node_modules/.bin/eslint", "."], ["npx", "tsc", "--noEmit"]], {"eslint", "tsc"}),
        ([["go", "test", "./..."], ["golangci-lint", "run"]], {"go", "golangci-lint"}),
        ([["{bindir}/lint-imports", "--no-cache"]], {"lint-imports"}),
        ([["{python}", "-m", "pytest"], ["./scripts/check.sh"]], None),
        ([["npx", "--yes", "eslint", "."]], {"eslint"}),
        ([["hatch", "env", "ruff"]], None),
        ([["make", "test"]], None),
        ([["npm", "test"]], None),
    ],
)
def test_the_checkers_a_contract_runs_are_read_from_its_commands(
    tmp_path: Path, commands: list[list[str]], expected: set[str] | None
) -> None:
    found = active_checkers([_ob(*c) for c in commands], tmp_path)
    assert found == (frozenset(expected) if expected is not None else None)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--cov=src --mypy"\n'),
        ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = ["--cov", "src", "--mypy"]\n'),
        ("pytest.ini", "[pytest]\naddopts = --cov=src --mypy\n"),
        ("setup.cfg", "[tool:pytest]\naddopts = --cov=src --mypy\n"),
        ("tox.ini", "[pytest]\naddopts = --cov=src --mypy\n"),
    ],
)
def test_pytest_options_in_configuration_turn_on_their_checkers(
    tmp_path: Path, name: str, text: str
) -> None:
    (tmp_path / name).write_text(text)
    found = active_checkers([_ob("{python}", "-m", "pytest")], tmp_path)
    assert found == frozenset({"pytest", "coverage", "mypy"})


def test_builtin_checks_are_not_commands(tmp_path: Path) -> None:
    builtin = {**_ob("ohx", "builtin", "weakening"), "builtin": "weakening"}
    assert active_checkers([builtin, _ob("{python}", "-m", "pytest")], tmp_path) == frozenset(
        {"pytest"}
    )


# End to end: a gate whose base runs only pytest.

CALC = "def add(a, b):\n    return a + b\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml: str) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n" + toml)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


NEW_CODE = {
    "calc.py": CALC + "\n\ndef load(path):\n    try:\n        return open(path).read()\n"
    "    except Exception:  # noqa: BLE001\n        return None  # type: ignore[return-value]\n",
    "tests/test_load.py": "import os\n\nimport pytest\n\nfrom calc import load\n\n\n"
    '@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")\n'
    "def test_load_missing():\n    assert load('/nonexistent') is None\n",
}


def _gate(tmp_path: Path) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)])
    return code, json.loads((out / "report.json").read_text())


def _change(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")


def test_a_pull_request_with_harmless_suppressions_is_ready_and_they_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, monkeypatch, "")
    _change(repo, NEW_CODE)
    code, report = _gate(tmp_path)
    assert code == EXIT_OK
    weakening = next(o for o in report["observations"] if o["obligation_id"] == "weakening")
    assert "not counted" in weakening["note"] and "noqa" in weakening["note"]
    assert "(pytest)" in weakening["note"]  # the checkers the contract runs


def test_when_the_contract_runs_the_linter_its_suppressions_still_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lint = (
        '\n[[obligations]]\nid = "lint"\nkind = "check"\nmandatory = false\n'
        'command = ["{python}", "-m", "ruff", "--version"]\n'
    )
    repo = _repo(tmp_path, monkeypatch, lint)
    _change(repo, NEW_CODE)
    code, report = _gate(tmp_path)
    assert code != EXIT_OK
    weakening = next(o for o in report["observations"] if o["obligation_id"] == "weakening")
    assert "1 new noqa" in weakening["note"]
