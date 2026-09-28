"""Acceptance tests for source tracing, `ohx trace` (contracts/0002).

Written before the feature. Self-contained: the protected copy runs from the
OpenHarnX store. The scenario replays the owner's T01 case: a BRD business
rule silently dropped between requirements and delivery.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main

BRD = """# Invoice approval BRD

## Rules

- Invoices above 10,000 need a second approver.
- Duplicate invoice numbers from the same vendor are rejected.
- Approved invoices are exported to the ERP nightly.

| Field | Rule |
|---|---|
| Currency | Must match the vendor's contract currency |

Background: the finance team currently approves by email. This is slow.
"""

DECISIONS = """# Interrogation decisions

- Credit notes skip the second approver.
"""

TESTS = """
from rules import needs_second_approver, is_duplicate, currency_ok


def test_second_approver():
    assert needs_second_approver(10_001) and not needs_second_approver(10_000)


def test_duplicates():
    assert is_duplicate("V1", "INV-1", {("V1", "INV-1")})


def test_currency():
    assert currency_ok("EUR", "EUR") and not currency_ok("USD", "EUR")


def test_credit_note():
    assert not needs_second_approver(50_000, credit_note=True)
"""

RULES_OK = """
def needs_second_approver(amount, credit_note=False):
    return amount > 10_000 and not credit_note


def is_duplicate(vendor, number, seen):
    return (vendor, number) in seen


def currency_ok(invoice, contract):
    return invoice == contract
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "docs").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs" / "BRD.md").write_text(BRD)
    (repo / "docs" / "decisions.md").write_text(DECISIONS)
    (repo / "tests" / "test_rules.py").write_text(TESTS)
    (repo / "rules.py").write_text(RULES_OK)
    (repo / "ohx.toml").write_text(f'python = "{sys.executable}"\n')
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


def _init() -> int:
    return main(["trace", "init", "docs/BRD.md", "docs/decisions.md"])


def _load(repo: Path) -> dict[str, Any]:
    return tomllib.loads((repo / "trace.toml").read_text())


def _units(repo: Path) -> dict[str, dict[str, Any]]:
    return {u["text"]: u for u in _load(repo)["unit"]}


def _mark(repo: Path, marks: dict[str, dict[str, Any]]) -> None:
    """Rewrite trace.toml with markings keyed by a substring of the unit text."""
    text = (repo / "trace.toml").read_text()
    data = _load(repo)
    for unit in data["unit"]:
        for needle, fields in marks.items():
            if needle in unit["text"]:
                block_start = text.index(f'id = "{unit["id"]}"')
                block_end = text.find("[[unit]]", block_start)
                block_end = len(text) if block_end == -1 else block_end
                block = text[block_start:block_end]
                new = block.replace('status = "unmarked"', f'status = "{fields["status"]}"')
                if "tests" in fields:
                    listed = ", ".join(f'"{x}"' for x in fields["tests"])
                    new = new.replace("tests = []", f"tests = [{listed}]")
                if "note" in fields:
                    new = new.replace('note = ""', f'note = "{fields["note"]}"')
                text = text[:block_start] + new + text[block_end:]
    (repo / "trace.toml").write_text(text)


T = "tests/test_rules.py::"
ALL_MAPPED: dict[str, dict[str, Any]] = {
    "above 10,000": {"status": "requirement", "tests": [T + "test_second_approver"]},
    "Duplicate invoice": {"status": "requirement", "tests": [T + "test_duplicates"]},
    "exported to the ERP": {"status": "excluded", "note": "phase 2"},
    "contract currency": {"status": "requirement", "tests": [T + "test_currency"]},
    "Credit notes": {"status": "requirement", "tests": [T + "test_credit_note"]},
    "Background": {"status": "context"},
    "This is slow": {"status": "context"},
}


# Splitting and numbering (deterministic, no model calls)


def test_init_splits_sources_into_numbered_units(repo: Path) -> None:
    assert _init() == EXIT_OK
    units = _load(repo)["unit"]
    texts = [u["text"] for u in units]
    assert "Invoices above 10,000 need a second approver." in texts
    assert any("Must match the vendor's contract currency" in t for t in texts)
    assert "Background: the finance team currently approves by email." in texts
    assert "This is slow." in texts
    assert "Credit notes skip the second approver." in texts
    assert not any(t.startswith("#") for t in texts)  # headings are context, not units
    assert not any(set(t) <= set("|-: ") for t in texts)  # table separators skipped
    assert len(units) == 7
    ids = [u["id"] for u in units]
    assert len(set(ids)) == 7
    assert all(u["status"] == "unmarked" for u in units)
    by_source = {u["source"] for u in units}
    assert by_source == {"docs/BRD.md", "docs/decisions.md"}


def test_unmarked_units_block(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init()
    capsys.readouterr()
    assert main(["trace", "check"]) == EXIT_BLOCKED
    assert "open" in capsys.readouterr().out


# The T01 replay: a business rule silently dropped


def test_requirement_without_tests_is_not_built(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init()
    marks = dict(ALL_MAPPED)
    marks["Duplicate invoice"] = {"status": "requirement"}  # rule kept, but nothing proves it
    _mark(repo, marks)
    main(["trace", "approve", "--yes"])
    capsys.readouterr()
    assert main(["trace", "check"]) == EXIT_BLOCKED
    out = capsys.readouterr().out
    assert "not built" in out and "Duplicate invoice" in out


def test_rule_silently_marked_as_context_blocks_until_owner_approves(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init()
    marks = dict(ALL_MAPPED)
    marks["Duplicate invoice"] = {"status": "context"}  # the silent drop
    _mark(repo, marks)
    capsys.readouterr()
    assert main(["trace", "check"]) == EXIT_BLOCKED
    out = capsys.readouterr().out
    assert "not approved" in out and "Duplicate invoice" in out
    assert main(["trace", "approve", "--yes"]) == EXIT_OK
    assert main(["trace", "check"]) == EXIT_OK


def test_changing_dropped_units_after_approval_blocks_again(repo: Path) -> None:
    _init()
    _mark(repo, ALL_MAPPED)
    assert main(["trace", "approve", "--yes"]) == EXIT_OK
    assert main(["trace", "check"]) == EXIT_OK
    text = (repo / "trace.toml").read_text()
    (repo / "trace.toml").write_text(
        text.replace('status = "requirement"', 'status = "context"', 1)
    )
    assert main(["trace", "check"]) == EXIT_BLOCKED


def test_excluded_needs_a_reason(repo: Path) -> None:
    _init()
    marks = dict(ALL_MAPPED)
    marks["exported to the ERP"] = {"status": "excluded"}  # no reason given
    _mark(repo, marks)
    assert main(["trace", "approve", "--yes"]) == EXIT_USAGE
    assert main(["trace", "check"]) == EXIT_BLOCKED


def test_questions_block(repo: Path) -> None:
    _init()
    marks = dict(ALL_MAPPED)
    marks["Credit notes"] = {"status": "question"}
    _mark(repo, marks)
    main(["trace", "approve", "--yes"])
    assert main(["trace", "check"]) == EXIT_BLOCKED


def test_fully_mapped_and_approved_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _init()
    _mark(repo, ALL_MAPPED)
    assert main(["trace", "approve", "--yes"]) == EXIT_OK
    capsys.readouterr()
    assert main(["trace", "check"]) == EXIT_OK
    out = capsys.readouterr().out
    # Without --run nothing was executed, so the tests are only linked, never "verified".
    assert "4 linked" in out and "verified" not in out and "3 dropped (approved)" in out
    assert main(["trace", "check", "--run"]) == EXIT_OK
    assert "4 verified" in capsys.readouterr().out


# Sources change after mapping


def test_new_brd_line_after_mapping_blocks_and_reinit_keeps_markings(repo: Path) -> None:
    _init()
    _mark(repo, ALL_MAPPED)
    main(["trace", "approve", "--yes"])
    assert main(["trace", "check"]) == EXIT_OK
    brd = repo / "docs" / "BRD.md"
    brd.write_text(
        brd.read_text().replace(
            "- Approved invoices", "- Rejected invoices notify the vendor.\n- Approved invoices"
        )
    )
    assert main(["trace", "check"]) == EXIT_BLOCKED  # untracked source text
    assert _init() == EXIT_OK  # merge
    units = _units(repo)
    assert units["Rejected invoices notify the vendor."]["status"] == "unmarked"
    kept = units["Duplicate invoice numbers from the same vendor are rejected."]
    assert kept["status"] == "requirement"
    assert main(["trace", "check"]) == EXIT_BLOCKED


# Running the linked tests


def test_run_blocks_on_failing_or_missing_tests(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _init()
    _mark(repo, ALL_MAPPED)
    main(["trace", "approve", "--yes"])
    assert main(["trace", "check", "--run"]) == EXIT_OK
    (repo / "rules.py").write_text(RULES_OK.replace("return invoice == contract", "return True"))
    capsys.readouterr()
    assert main(["trace", "check", "--run"]) == EXIT_BLOCKED
    assert "contract currency" in capsys.readouterr().out
    (repo / "rules.py").write_text(RULES_OK)
    text = (repo / "trace.toml").read_text()
    (repo / "trace.toml").write_text(text.replace("test_currency", "test_does_not_exist"))
    assert main(["trace", "check", "--run"]) == EXIT_BLOCKED


def test_check_without_trace_file_is_usage_error(repo: Path) -> None:
    assert main(["trace", "check"]) == EXIT_USAGE
