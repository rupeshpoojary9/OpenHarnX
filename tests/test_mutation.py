"""Acceptance tests for mutation checks (T87 item 5, contracts/0028).

From the owner's real `ohx bug` run (2026-10-03): the approved tests are the
oracle, but nothing showed whether they would catch a plausible wrong fix. A
test like `percent(1, 1) > 10` fails on the bug and passes on the fix, yet
also passes when the fix multiplies where it should divide.

At verification, after the acceptance tests pass, OpenHarnX makes small
changes (mutants) to the changed lines of source files, one at a time, in a
copy of the tree, and runs the acceptance tests against each. A mutant the
tests still pass "survived": the tests do not pin that part of the change.
The check is advisory (owner default 2026-10-03): it names the survivors and
never changes the verdict. A mutant counts only when the tests actually
imported the mutated file; otherwise it is "not exercised", never a survivor
or a kill. Self-contained.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

CALC = """\
def add(a, b):
    return a + b


def percent(part, whole):
    return part * 10 / whole  # the bug
"""
FIXED = CALC.replace("return part * 10 / whole  # the bug", "return part * 100 / whole")

WEAK = "from calc import percent\n\n\ndef test_percent():\n    assert percent(1, 1) > 10\n"
STRONG = "from calc import percent\n\n\ndef test_percent():\n    assert percent(1, 4) == 25\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acceptance_test: str) -> Path:
    acceptance = tmp_path / "outside" / "test_percent.py"
    acceptance.parent.mkdir()
    acceptance.write_text(acceptance_test)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix percent", "--summary", "percent uses 100"]
    assert main([*new, "--acceptance", str(acceptance), "--accept", "--sandbox", "none"]) == 0
    return repo


def _verify(sandbox: str = "none") -> tuple[int, dict[str, Any]]:
    code = main(["verify", "--sandbox", sandbox])
    home = Path(os.environ["OHX_HOME"])
    reports = sorted(home.glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime)
    return code, json.loads(reports[-1].read_text())


def _mutation(report: dict[str, Any]) -> dict[str, Any]:
    found: list[dict[str, Any]] = [
        o for o in report["observations"] if o["obligation_id"] == "mutation"
    ]
    assert len(found) == 1, [o["obligation_id"] for o in report["observations"]]
    return found[0]


def test_weak_tests_let_a_wrong_fix_survive_and_the_verdict_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch, WEAK)
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK and report["readiness"] == "ready"  # advisory
    m = _mutation(report)
    assert m["outcome"] == "fail"
    assert "2 of 3" in m["note"] and "survived" in m["note"]
    assert "calc.py:6" in m["note"]
    assert "calc.py:2" not in m["note"]  # unchanged lines are not mutated
    gate = report["gate"]["obligations"]
    assert [o for o in gate if o["obligation_id"] == "mutation"][0]["mandatory"] is False


def test_strong_tests_kill_every_mutant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make(tmp_path, monkeypatch, STRONG)
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK
    m = _mutation(report)
    assert m["outcome"] == "pass", m["note"]
    assert "3 of 3" in m["note"] and "killed" in m["note"]


def test_no_changed_source_lines_is_unavailable_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch, "def test_nothing():\n    assert True\n")
    (repo / "NOTES.md").write_text("only docs changed\n")
    code, report = _verify()
    assert code == EXIT_OK
    m = _mutation(report)
    assert m["outcome"] == "unavailable"
    assert "no changed source lines" in m["note"]


def test_failing_acceptance_tests_are_not_mutated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch, STRONG)
    (repo / "calc.py").write_text(FIXED.replace("100", "1000"))
    code, report = _verify()
    assert code == EXIT_BLOCKED
    m = _mutation(report)
    assert m["outcome"] == "unavailable"
    assert "acceptance tests did not pass" in m["note"]


def test_mutation_leaves_the_repository_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch, WEAK)
    (repo / "calc.py").write_text(FIXED)
    _, report = _verify()
    assert report["candidate"]["changed_during_verification"] is False
    assert (repo / "calc.py").read_text() == FIXED
    assert sorted(p.name for p in repo.iterdir()) == [".git", "calc.py", "contracts", "ohx.toml"]


def test_mutation_is_a_reserved_obligation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch, STRONG)
    bad = repo / "contracts" / "bad.toml"
    bad.write_text(
        'title = "x"\nmode = "task"\nchange_summary = "x"\n\n[[obligations]]\n'
        'id = "mutation"\nkind = "check"\nmandatory = false\ncommand = ["true"]\n'
    )
    assert main(["contract", "accept", str(bad), "--sandbox", "none"]) != EXIT_OK


def test_the_report_shows_the_survivors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make(tmp_path, monkeypatch, WEAK)
    (repo / "calc.py").write_text(FIXED)
    main(["verify", "--sandbox", "none"])
    home = Path(os.environ["OHX_HOME"])
    md = sorted(home.glob("projects/*/runs/*/report.md"), key=lambda p: p.stat().st_mtime)[-1]
    text = md.read_text()
    assert "mutation" in text and "survived" in text


# The trap found while designing this: a protected checker environment (`environment = "uv"`)
# makes the repository importable through a .pth file, so a mutated copy elsewhere would be
# ignored and every mutant would wrongly survive. Mutants must be imported from the copy.
PLAIN = "import sys\n\nimport calc\n\nsys.exit(0 if calc.percent(1, 4) == 25 else 1)\n"
PYPROJECT = '[project]\nname = "calc"\nversion = "0"\nrequires-python = ">=3.12"\n'
LOCK = 'version = 1\nrequires-python = ">=3.12"\n'
STAND_IN_UV = f"""#!{sys.executable}
import os, subprocess, sys
args = sys.argv[1:]
assert args[0] == "sync", args
target = os.environ["UV_PROJECT_ENVIRONMENT"]
subprocess.run([{sys.executable!r}, "-m", "venv", "--without-pip", target], check=True)
"""


def test_mutants_are_imported_from_the_copy_with_a_protected_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = tmp_path / "stand-in-uv"
    stand_in.write_text(STAND_IN_UV)
    stand_in.chmod(0o755)
    monkeypatch.setenv("OHX_UV", str(stand_in))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    acceptance = tmp_path / "outside" / "check_percent.py"
    acceptance.parent.mkdir()
    acceptance.write_text(PLAIN)
    repo = tmp_path / "proj"
    (repo / "contracts").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "uv.lock").write_text(LOCK)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    rel = os.path.relpath(acceptance, repo / "contracts")
    (repo / "contracts" / "c.toml").write_text(
        'title = "Fix percent"\nmode = "bugfix"\nchange_summary = "percent uses 100"\n'
        'python = ".venv/bin/python"\nenvironment = "uv"\n\n[[obligations]]\n'
        'id = "acceptance"\nkind = "acceptance"\nmandatory = true\n'
        f'protected = {rel!r}\ncommand = ["{{python}}", "{{protected}}"]\n'
    )
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["contract", "accept", "contracts/c.toml", "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify()
    assert code == EXIT_OK
    m = _mutation(report)
    assert m["outcome"] == "pass", m["note"]  # every mutant ran from the copy and was killed
    assert "3 of 3" in m["note"]


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_weak_tests_are_found_under_srt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _make(tmp_path, monkeypatch, WEAK)
    (repo / "calc.py").write_text(FIXED)
    code, report = _verify("srt")
    assert code == EXIT_OK
    m = _mutation(report)
    assert m["outcome"] == "fail" and "2 of 3" in m["note"], m["note"]
