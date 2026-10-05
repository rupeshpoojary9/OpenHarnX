"""The report opens with a review brief (T96, contracts/0054).

A reviewer reading a report wants five answers before the detail: what was asked for,
what changed, what was verified, what is still unverified, and what needs their
judgment. The report held most of the facts but in the order the checker produced them,
and some it never recorded: which files the task changed, which acceptance tests passed
one by one, and which changed modules the tests even imported.

Now every report starts with those five sections, built only from records (no model
calls), with the existing detail beneath. Every verification claim links to the check's
recorded output. A passing test is never presented as proof that changed code ran, and
a report made stale by later edits says so in the brief itself.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.report import render_markdown

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
ACCEPTANCE = """\
from calc import half


def test_half_of_ten():
    assert half(10) == 5


def test_half_of_zero():
    assert half(0) == 0
"""
FIXED = CALC.replace("    return a\n", "    return a / 2\n")
SECTIONS = [
    "## Requested outcome",
    "## What changed",
    "## What was verified",
    "## What remains unverified",
    "## Decisions for you",
    "## Details",
]


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "other.py").write_text("def unused():\n    return 1\n")
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


def _contract(acceptance: bool = True) -> None:
    if not acceptance:  # the existing tests locked, nothing agreed for the task itself
        assert main(["init", "--lock-tests", "--sandbox", "none"]) == EXIT_OK
        return
    args = ["contract", "new", "--mode", "bugfix", "--title", "Fix half"]
    args += ["--summary", "half() returns half of its argument", "--sandbox", "none"]
    args += ["--acceptance", "acceptance/test_half.py"]
    assert main([*args, "--accept"]) == EXIT_OK


def _run(tmp_path: Path) -> tuple[dict[str, Any], str, Path]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    return json.loads(runs[-1].read_text()), (runs[-1].parent / "report.md").read_text(), runs[-1]


def _section(markdown: str, heading: str) -> str:
    start = markdown.index(heading)
    end = markdown.find("\n## ", start + len(heading))
    return markdown[start : end if end != -1 else None]


def test_a_ready_change_gets_all_five_sections_in_order(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown, _ = _run(tmp_path)
    assert report["readiness"] == "ready"
    positions = [markdown.index(h) for h in SECTIONS]
    assert positions == sorted(positions)
    assert markdown.startswith("# OpenHarnX report: READY")
    outcome = _section(markdown, "## Requested outcome")
    assert "Fix half" in outcome and "half() returns half of its argument" in outcome
    assert report["contract"]["revision_id"] in outcome
    changed = _section(markdown, "## What changed")
    assert "`calc.py`" in changed and "modified" in changed
    assert "`other.py`" not in changed  # unchanged files are not listed
    verified = _section(markdown, "## What was verified")
    assert "test_half_of_ten" in verified and "test_half_of_zero" in verified
    assert "does not show that every changed line ran" in verified


def test_every_verification_claim_links_to_its_recorded_output(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown, path = _run(tmp_path)
    claims = [
        line for line in _section(markdown, "## What was verified").splitlines()
        if line.startswith("- ")
    ]  # fmt: skip
    assert claims
    for line in claims:
        if line.startswith("- Note:"):
            continue
        link = re.search(r"\]\((evidence/[^)]+)\)", line)
        assert link, f"no evidence link: {line}"
        assert (path.parent / link.group(1)).is_file()
    acceptance = next(o for o in report["observations"] if o["obligation_id"].startswith("accept"))
    evidence = report["evidence"][acceptance["obligation_id"]]
    assert evidence["output"] == acceptance["output_blob"]
    assert "2 passed" in (path.parent / evidence["file"]).read_text()


def test_no_regressions_without_acceptance_asks_the_reviewer_to_judge_the_outcome(
    repo: Path, tmp_path: Path
) -> None:
    _contract(acceptance=False)
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown, _ = _run(tmp_path)
    assert report["readiness"] == "no-regressions"
    verified = _section(markdown, "## What was verified")
    assert "acceptance" not in verified.lower().replace("no acceptance", "")
    unverified = _section(markdown, "## What remains unverified")
    assert "no acceptance tests were agreed" in unverified
    decisions = _section(markdown, "## Decisions for you")
    assert "Is the requested outcome done?" in decisions


def test_a_failed_mandatory_check_is_not_presented_as_verified(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    report, markdown, _ = _run(tmp_path)
    assert report["readiness"] == "blocked"
    failed = [o["obligation_id"] for o in report["gate"]["obligations"] if o["status"] == "fail"]
    assert failed
    verified = _section(markdown, "## What was verified")
    unverified = _section(markdown, "## What remains unverified")
    for ob in failed:
        assert f"`{ob}`" not in verified and f"`{ob}`" in unverified
    decisions = _section(markdown, "## Decisions for you")
    assert "Send it back" in decisions and "cannot waive" in decisions


def test_an_unavailable_mandatory_check_is_shown_as_unverified(repo: Path, tmp_path: Path) -> None:
    contract = repo / "contracts" / "manual.toml"
    contract.parent.mkdir()
    contract.write_text(
        'title = "Fix half"\nmode = "bugfix"\nchange_summary = "s"\n'
        f"python = {sys.executable!r}\n\n"
        '[[obligations]]\nid = "acceptance-half"\nkind = "acceptance"\nmandatory = true\n'
        'protected = "../acceptance/test_half.py"\n'
        'command = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "{protected}"]\n\n'
        '[[obligations]]\nid = "lint"\nkind = "check"\nmandatory = true\n'
        'command = ["no-such-linter-ohx", "."]\n'
    )
    assert main(["contract", "accept", str(contract), "--sandbox", "none"]) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    _, markdown, _ = _run(tmp_path)
    unverified = _section(markdown, "## What remains unverified")
    assert "`lint`" in unverified and "unavailable" in unverified
    assert "`lint`" not in _section(markdown, "## What was verified")


def test_changed_code_no_acceptance_test_imported_is_named(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    (repo / "other.py").write_text("def unused():\n    return 2\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown, _ = _run(tmp_path)
    acceptance = next(k for k in report["imported"] if k.startswith("acceptance"))
    assert "calc.py" in report["imported"][acceptance]
    assert "other.py" not in report["imported"][acceptance]
    unverified = _section(markdown, "## What remains unverified")
    assert "`other.py`" in unverified and "`calc.py`" not in unverified
    assert "`other.py`" in _section(markdown, "## Decisions for you")


def test_requirement_evidence_that_is_missing_is_said_plainly(repo: Path, tmp_path: Path) -> None:
    """A passing acceptance check whose per-test results were not recorded (a runner
    without JUnit output) is evidence for the check, not for each agreed case."""
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _, _ = _run(tmp_path)
    acceptance = next(k for k in report["acceptance_tests"])
    report["acceptance_tests"][acceptance] = None
    report["imported"] = {}
    markdown = render_markdown(report)
    verified = _section(markdown, "## What was verified")
    assert "per-test results were not recorded" in verified
    unverified = _section(markdown, "## What remains unverified")
    assert "which changed files the tests imported is not recorded" in unverified


def test_changes_after_verification_make_the_brief_stale(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    (repo / "other.py").write_text("def unused():\n    return 3\n")
    capsys.readouterr()
    assert main(["report"]) != EXIT_OK
    markdown = capsys.readouterr().out
    assert markdown.startswith("# OpenHarnX report: STALE")
    verified = _section(markdown, "## What was verified")
    assert "an earlier state of the files" in verified
    assert "`other.py`" in verified
    assert "Verify again" in _section(markdown, "## Decisions for you")


def test_test_and_configuration_changes_are_put_to_the_reviewer(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    (repo / "tests" / "test_more.py").write_text(
        "from calc import half\n\n\ndef test_half_four():\n    assert half(4) == 2\n"
    )
    (repo / "requirements.txt").write_text("requests\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    _, markdown, _ = _run(tmp_path)
    changed = _section(markdown, "## What changed")
    assert re.search(r"`tests/test_more.py`.*added.*test", changed)
    assert re.search(r"`requirements.txt`.*added.*dependencies", changed)
    decisions = _section(markdown, "## Decisions for you")
    assert "`tests/test_more.py`" in decisions and "`requirements.txt`" in decisions


def test_a_report_from_an_earlier_version_says_what_it_did_not_record(
    repo: Path, tmp_path: Path
) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, _, _ = _run(tmp_path)
    for key in ("changes", "evidence", "acceptance_tests", "imported"):
        report.pop(key)
    markdown = render_markdown(report)
    assert "not recorded by the OpenHarnX version that made this report" in markdown
    assert "## Details" in markdown


def test_the_gate_brief_lists_the_pull_requests_files_with_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "ci"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    (repo / "calc.py").write_text(FIXED)
    _git(repo, "commit", "-qam", "fix half")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    out = tmp_path / "gate-out"
    assert main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)]) == EXIT_OK
    markdown = (out / "report.md").read_text()
    changed = _section(markdown, "## What changed")
    assert "`calc.py`" in changed and "`tests/test_calc.py`" not in changed
    for link in re.findall(r"\]\((evidence/[^)]+)\)", _section(markdown, "## What was verified")):
        assert (out / link).is_file()


def test_the_brief_makes_no_model_calls_and_authorizes_nothing(repo: Path, tmp_path: Path) -> None:
    _contract()
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report, markdown, _ = _run(tmp_path)
    assert report["cost"]["overhead"]["model_calls"] == 0
    assert "This report authorizes nothing." in markdown
