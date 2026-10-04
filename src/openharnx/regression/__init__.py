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

import ast
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MAX_JUNIT_BYTES = 50_000_000
LISTED = 20  # test names shown per category


JUNIT_ENV = "OHX_JUNIT"


def junit_env(path: Path) -> dict[str, str]:
    """Environment that makes pytest write per-test results to `path`.

    Other runners write JUnit XML when their command uses the `{junit}` placeholder,
    which names the same path (T82)."""
    return {"PYTEST_ADDOPTS": f"--junitxml={path}", JUNIT_ENV: str(path)}


# Loaded into pytest with -p for the order check: keeps only the tests listed in the file
# named by OHX_ORDER_IDS and runs them in reverse order. Ids are made the way pytest's
# JUnit XML names tests, so they match read_results.
ORDER_PLUGIN = """\
import os
import re


def _junit_id(nodeid):
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]) + "::" + names[-1]


def pytest_collection_modifyitems(config, items):
    with open(os.environ["OHX_ORDER_IDS"], encoding="utf-8") as f:
        wanted = set(f.read().splitlines())
    keep = [i for i in items if _junit_id(i.nodeid) in wanted]
    dropped = [i for i in items if _junit_id(i.nodeid) not in wanted]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = keep[::-1]
"""
ORDER_MODULE = "ohx_order"


def order_env(
    folder: Path, test_ids: list[str], junit: Path, pythonpath: str = ""
) -> dict[str, str]:
    """Environment for the order check run: only `test_ids`, in reverse order, results to
    `junit`. Writes the plugin and the id list into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ORDER_MODULE}.py").write_text(ORDER_PLUGIN, encoding="utf-8")
    (folder / "ids.txt").write_text("\n".join(test_ids) + "\n", encoding="utf-8")
    path = str(folder) + (f":{pythonpath}" if pythonpath else "")
    return {
        "PYTEST_ADDOPTS": f"-p {ORDER_MODULE} --junitxml={junit}",
        JUNIT_ENV: str(junit),
        "PYTHONPATH": path,
        "OHX_ORDER_IDS": str(folder / "ids.txt"),
    }


def newly_passing(base: dict[str, Any], tests: dict[str, str] | None) -> list[str]:
    """Tests that pass now and did not at acceptance; every passing test when the suite
    had no per-test baseline because it crashed or ran nothing."""
    if not tests:
        return []
    before: dict[str, str] | None = base.get("tests")
    if base.get("outcome") == "crash" or before == {}:
        return sorted(t for t, o in tests.items() if o == "pass")
    if before is None:
        return []
    return sorted(t for t, o in tests.items() if o == "pass" and before.get(t) in ("fail", "skip"))


def order_problems(test_ids: list[str], tests: dict[str, str] | None, outcome: str) -> list[str]:
    """Tests from `test_ids` that did not pass when run on their own in reverse order."""
    if tests is None:
        return [
            f"the {len(test_ids)} test(s) that newly pass could not be run again on their own"
            f" (the run ended with {outcome})"
        ]
    problems = []
    for test_id in test_ids:
        now = tests.get(test_id)
        if now != "pass":
            state = {"fail": "fails", "skip": "is skipped"}.get(now or "", "does not run")
            problems.append(f"{test_id} passes in the full run but {state} on its own")
    return problems


def _relative(file: str, root: Path | None) -> str:
    if root is None:
        return file
    for base in (root, root.resolve()):
        try:
            return str(Path(file).resolve().relative_to(base.resolve()))
        except ValueError:
            try:
                return str(Path(file).relative_to(base))
            except ValueError:
                continue
    return file


def _cases(node: ET.Element, suites: tuple[str, ...]) -> list[tuple[ET.Element, tuple[str, ...]]]:
    found: list[tuple[ET.Element, tuple[str, ...]]] = []
    for child in node:
        if child.tag == "testcase":
            found.append((child, suites))
        elif child.tag == "testsuite":
            found += _cases(child, (*suites, child.get("name", "")))
    return found


def read_details(path: Path, root: Path | None = None) -> dict[str, tuple[str, str]] | None:
    """Per-test outcome (pass, fail or skip) and failure reason by test id.

    The reason is the exception name when the failure names one, AssertionError
    for a failed assert; None when results are not available. A test case with a
    `file` attribute (Node's runner, whose class name is always "test") is named by
    its file relative to `root` and its enclosing suites; others by class name, as
    pytest's ids have always been.
    """
    try:
        if not path.is_file() or path.stat().st_size > MAX_JUNIT_BYTES:
            return None
        tree = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    results: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    for case, suites in _cases(tree, ()):
        file = case.get("file")
        if file or case.get("classname") == "test":
            # Node's runner: class name always "test"; Node 22 writes no file name.
            name = " > ".join((*suites, case.get("name", "")))
            test_id = f"{_relative(file, root) if file else 'test'}::{name}"
            if test_id in seen:
                return None  # two tests share an id: per-test results would merge them
            seen.add(test_id)
        else:
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


def read_results(path: Path, root: Path | None = None) -> dict[str, str] | None:
    """Per-test outcome (pass, fail or skip) by test id; None when not available."""
    details = read_details(path, root)
    return None if details is None else {t: o for t, (o, _) in details.items()}


def read_go_results(output: bytes) -> dict[str, str] | None:
    """Per-test outcome by `package::Test` from `go test -json` output; None without events.

    Lines that are not events (build errors) are ignored. A test reported both passing and
    failing counts as failing, so output a test prints cannot turn its failure into a pass."""
    results: dict[str, str] = {}
    rank = {"pass": 0, "skip": 1, "fail": 2}
    for line in output.splitlines():
        if not line.startswith(b"{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("Action") not in rank:
            continue
        package, test = event.get("Package"), event.get("Test")
        if not isinstance(package, str) or not isinstance(test, str):
            continue  # package-level result
        test_id = f"{package}::{test}"
        results[test_id] = max(event["Action"], results.get(test_id, "pass"), key=rank.__getitem__)
    return results or None


def baseline(outcome: str, tests: dict[str, str] | None) -> dict[str, Any]:
    return {"outcome": outcome, "tests": tests}


def _names(tests: list[str]) -> str:
    shown = ", ".join(tests[:LISTED])
    return shown + (f" and {len(tests) - LISTED} more" if len(tests) > LISTED else "")


def compare(
    base: dict[str, Any],
    outcome: str,
    tests: dict[str, str] | None,
    removed_ok: bool = False,
) -> tuple[str, str]:
    """Outcome (pass, fail or unavailable) and note for the no-new-failures check.

    Per-test results count only when the suite ran properly (it passed or had failing
    tests) and ran at least one test: a suite that collected nothing, crashed or timed
    out is never evidence of a pass (review 2026-10-03). When the suite crashed or ran no
    test at acceptance, a later run counts only if it passed and every test in it passed
    (impossible-tasks replay, 2026-10-04). With `removed_ok`, a maintainer approved the
    change's test changes (T90b): a test that passed and no longer runs or is skipped is
    listed as approved instead of failing; one that now fails still fails."""
    before: dict[str, str] | None = base.get("tests")
    # A crash at collection (a test imports code that does not exist yet) or no tests at
    # all; an invalid or timed-out baseline is not covered and stays unavailable.
    no_baseline = base.get("outcome") == "crash" or before == {}
    if no_baseline and outcome == "pass" and tests and set(tests.values()) == {"pass"}:
        # Nothing passed at acceptance, so nothing can regress; a full pass is enough.
        return "pass", (
            f"no baseline (the suite could not run at acceptance); all {len(tests)}"
            " test(s) pass now"
        )
    if base.get("outcome") not in ("pass", "fail"):
        return "unavailable", (
            f"no baseline: the suite could not run at acceptance ({base.get('outcome')});"
            " fix that and accept a contract revision"
        )
    if outcome not in ("pass", "fail"):
        if base.get("outcome") == "pass":
            return "fail", f"the suite passed at acceptance and now ends with {outcome}"
        return "unavailable", f"the suite now ends with {outcome}, so nothing can be compared"
    if before is not None and not before:
        return "unavailable", "no test ran at acceptance, so there is nothing to compare"
    if before is not None and tests is not None:
        problems, removed = [], []
        for test_id, was in sorted(before.items()):
            if was != "pass":
                continue
            now = tests.get(test_id)
            if now != "pass":
                state = {"fail": "fails", "skip": "is skipped"}.get(now or "", "no longer runs")
                if removed_ok and now != "fail":
                    removed.append(test_id)
                else:
                    problems.append(f"{test_id} passed at acceptance and {state}")
        added = sorted(t for t, o in tests.items() if t not in before and o == "fail")
        problems += [f"{t} is new and fails" for t in added[:LISTED]]
        if problems:
            return "fail", "; ".join(problems)
        if removed:
            return "pass", (
                f"{len(removed)} test(s) that passed at acceptance no longer run or are"
                f" skipped, approved: {_names(removed)}"
            )
        already = sorted(t for t, o in before.items() if o == "fail" and tests.get(t) == "fail")
        if already:
            return "pass", f"failing before this change, still failing: {_names(already)}"
        return "pass", ""
    if base.get("outcome") == "pass":
        if outcome == "pass":
            return "pass", ""
        return "fail", f"the suite passed at acceptance and now ends with {outcome}"
    return "unavailable", (
        "cannot compare: the suite was already failing at acceptance"
        " and per-test results are not available"
    )


def _test_node(root: Path, test_id: str) -> tuple[Path, str | None] | None:
    """Where a pytest test lives under `root` and its source, normalized (no positions or
    formatting); None for the source when the file is there and the test is not. None
    overall when `root` has no file for this id."""
    classname, _, name = test_id.partition("::")
    name = name.split("[", 1)[0]
    parts = [p for p in classname.split(".") if p]
    for start in (0, 1):  # ids may or may not start with the folder's own name
        for end in range(len(parts), start, -1):
            path = root.joinpath(*parts[start:end]).with_suffix(".py")
            if not path.is_file():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                return path.relative_to(root), None
            body: list[ast.stmt] = tree.body
            for cls in parts[end:]:
                found = [n for n in body if isinstance(n, ast.ClassDef) and n.name == cls]
                if not found:
                    return path.relative_to(root), None
                body = found[0].body
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    return path.relative_to(root), ast.dump(node)
            return path.relative_to(root), None
    return None


def edited_tests(locked: Path, working: Path, test_ids: list[str]) -> list[str]:
    """Tests from `test_ids` whose source in `working` differs from the locked copy, or
    is gone (impossible-tasks replay, 2026-10-04). Python only; ids the locked copy
    cannot place are skipped."""
    found = []
    for test_id in sorted(test_ids):
        was = _test_node(locked, test_id)
        if was is None or was[1] is None:
            continue
        now = _test_node(working, test_id)
        if now is None or now[1] is None:
            found.append(f"{test_id} was failing when locked and has been removed")
        elif now[1] != was[1]:
            found.append(f"{test_id} was failing when locked and has been changed")
    return found
