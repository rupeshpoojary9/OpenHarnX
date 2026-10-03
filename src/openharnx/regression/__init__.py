"""Regression baseline: tests that passed at acceptance must still pass (T87 item 1).

The project's own suite usually has failures that are not the change's
concern, so requiring it to pass would block every change, and leaving it
advisory let an agent break other tests and still get READY. At acceptance
OpenHarnX records each test's result; at verification a test that passed then
and now fails, is skipped or no longer runs blocks. Per-test results come from
pytest's JUnit XML, requested through the environment so the checker command
stays as the contract wrote it. Without them the whole suite is compared, and a
suite that was already failing cannot be compared: unknown, never a pass.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MAX_JUNIT_BYTES = 50_000_000
LISTED = 20  # test names shown per category


def junit_env(path: Path) -> dict[str, str]:
    """Environment that makes pytest write per-test results to `path`."""
    return {"PYTEST_ADDOPTS": f"--junitxml={path}"}


def read_details(path: Path) -> dict[str, tuple[str, str]] | None:
    """Per-test outcome (pass, fail or skip) and failure reason by test id.

    The reason is the exception name when the failure names one, AssertionError
    for a failed assert; None when results are not available.
    """
    try:
        if not path.is_file() or path.stat().st_size > MAX_JUNIT_BYTES:
            return None
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    results: dict[str, tuple[str, str]] = {}
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        failed = [c for c in case if c.tag in ("failure", "error")]
        if failed:
            results[test_id] = ("fail", _reason(failed[0].get("message", "")))
        elif any(c.tag == "skipped" for c in case):
            results[test_id] = ("skip", "")
        else:
            results[test_id] = results.get(test_id, ("pass", ""))
    return results


def _reason(message: str) -> str:
    named = re.match(r"([A-Za-z_][\w.]*):", message)
    if named:
        return named.group(1).rsplit(".", 1)[-1]
    return "AssertionError" if message.startswith("assert") else "failure"


def read_results(path: Path) -> dict[str, str] | None:
    """Per-test outcome (pass, fail or skip) by test id; None when not available."""
    details = read_details(path)
    return None if details is None else {t: o for t, (o, _) in details.items()}


def baseline(outcome: str, tests: dict[str, str] | None) -> dict[str, Any]:
    return {"outcome": outcome, "tests": tests}


def _names(tests: list[str]) -> str:
    shown = ", ".join(tests[:LISTED])
    return shown + (f" and {len(tests) - LISTED} more" if len(tests) > LISTED else "")


def compare(base: dict[str, Any], outcome: str, tests: dict[str, str] | None) -> tuple[str, str]:
    """Outcome (pass, fail or unavailable) and note for the no-new-failures check."""
    before: dict[str, str] | None = base.get("tests")
    if before is not None and tests is not None:
        problems = []
        for test_id, was in sorted(before.items()):
            if was != "pass":
                continue
            now = tests.get(test_id)
            if now != "pass":
                state = {"fail": "fails", "skip": "is skipped"}.get(now or "", "no longer runs")
                problems.append(f"{test_id} passed at acceptance and {state}")
        added = sorted(t for t, o in tests.items() if t not in before and o == "fail")
        problems += [f"{t} is new and fails" for t in added[:LISTED]]
        if problems:
            return "fail", "; ".join(problems)
        already = sorted(t for t, o in before.items() if o == "fail" and tests.get(t) == "fail")
        if already:
            return "pass", f"failing before this change, still failing: {_names(already)}"
        return "pass", ""
    if base.get("outcome") == "pass":
        if outcome == "pass":
            return "pass", ""
        return "fail", f"the suite passed at acceptance and now ends with {outcome}"
    if base.get("outcome") not in ("pass", "fail"):
        return "unavailable", (
            f"no baseline: the suite could not run at acceptance ({base.get('outcome')});"
            " fix that and accept a contract revision"
        )
    return "unavailable", (
        "cannot compare: the suite was already failing at acceptance"
        " and per-test results are not available"
    )
