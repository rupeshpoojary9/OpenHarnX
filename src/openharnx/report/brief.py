"""The review brief at the top of every report (T96). Built from records only.

Five answers for the reviewer, in order: what was asked for, what changed, what was
verified (each claim linked to the check's recorded output), what remains unverified,
and the decisions that need a person. Facts the record does not hold are said to be
missing, never filled in. A passing test is not presented as proof that changed code
ran, and a stale report says so here as well as in its heading.
"""

from __future__ import annotations

from typing import Any

NOT_RECORDED = "not recorded by the OpenHarnX version that made this report"
LISTED_FILES = 40
LISTED_TESTS = 20
NOTE_CHARS = 240
ORDER = {"acceptance": 0, "builtin": 1, "regression": 2, "check": 3}
NO_NEW_FAILURES = "no-new-failures"
BUILTIN = {
    "weakening": "no removed test or assertion, new skip, new suppression or loosened check"
    " configuration was found",
}
PASSING_CAVEAT = (
    "- Note: a passing check does not show that every changed line ran, and a requirement"
    " with a passing test is not thereby fully tested. The mutation check, where it ran, is"
    " the only measure here of how much the tests notice."
)


def compared(report: dict[str, Any], oid: str) -> str:
    """The suite a no-new-failures comparison covers, from the record; the obligation itself
    when it is not one. Reports from before `compares` was recorded fall back to the id,
    which names the suite only when there are several (`no-new-failures-<suite>`)."""
    recorded = report.get("compares")
    if recorded is not None:
        return str(recorded.get(oid, oid))
    prefix = f"{NO_NEW_FAILURES}-"
    return oid.removeprefix(prefix) if oid.startswith(prefix) else oid


def _short(text: str, limit: int = NOTE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _paths(paths: list[str], limit: int = 8) -> str:
    shown = ", ".join(f"`{p}`" for p in paths[:limit])
    return shown + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def _kinds(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Obligation id to its kind and mandatory flag, from the gate and observations."""
    obs = {o["obligation_id"]: o for o in report["observations"]}
    recorded = report.get("obligation_kinds") or {}
    found: dict[str, dict[str, Any]] = {}
    for ob in report["gate"]["obligations"]:
        oid = ob["obligation_id"]
        if oid in recorded:
            kind = recorded[oid]
        elif oid.startswith("acceptance"):
            kind = "acceptance"
        elif oid.startswith("no-new-failures") or oid in ("weakening", "mutation"):
            kind = "builtin"
        elif obs.get(oid, {}).get("argv") and any("pytest" in str(a) for a in obs[oid]["argv"]):
            kind = "regression"
        else:
            kind = "check"
        found[oid] = {"kind": kind, "mandatory": ob["mandatory"], "status": ob["status"]}
    return found


def _changed_code(report: dict[str, Any]) -> list[str]:
    changes = report.get("changes") or {}
    return [
        f["path"]
        for f in changes.get("files", [])
        if f["kind"] == "code" and f["change"] != "deleted"
    ]


def _imported(report: dict[str, Any], only: str | None = None) -> set[str] | None:
    """Files loaded by the test runs (all, or one kind); None when not recorded."""
    imported = report.get("imported")
    if not imported:
        return None
    kinds = _kinds(report)
    runs = [v for k, v in imported.items() if only is None or kinds.get(k, {}).get("kind") == only]
    if not runs:
        return None
    return {p for files in runs for p in files}


def _requested(report: dict[str, Any]) -> list[str]:
    contract = report["contract"]
    summary = contract.get("summary")
    mode = contract.get("mode")
    who = contract.get("accepted_by") or {}
    by = f", accepted by {who.get('name')} <{who.get('email')}>" if who.get("name") else ""
    return [
        "## Requested outcome",
        "",
        f"**{contract['title']}**"
        + (f" ({mode})" if mode else "")
        + f": {summary or NOT_RECORDED}",
        "",
        f"Stated in contract revision `{contract['revision_id']}`{by}. "
        + (
            "No acceptance tests were agreed, so no check looks for it."
            if (report.get("claims") or {}).get("acceptance") == "none defined"
            else "It is checked only through the acceptance tests below, not read for meaning."
        ),
        "",
    ]


def _changed(report: dict[str, Any]) -> list[str]:
    lines = ["## What changed", ""]
    changes = report.get("changes")
    if not changes or not changes.get("known"):
        why = NOT_RECORDED if not changes else "the files accepted with the contract are unknown"
        return [*lines, f"Changed files: {why}.", ""]
    files = changes["files"]
    base = str(changes.get("base_commit") or "unknown")
    if not files:
        return [*lines, "Observed: no file differs from the files accepted with the contract.", ""]
    anywhere = _imported(report)
    if report["readiness"] == "stale":
        lines += ["As verified; the files changed since are listed under What was verified.", ""]
    lines += [
        f"Observed: {len(files)} file(s) differ, by content digest, from the files accepted"
        f" with the contract (base commit `{base[:12]}`). Why each changed is not recorded;"
        " an agent's own account of its change is not evidence.",
        "",
        "| File | Change | Kind | Imported by a test run |",
        "|---|---|---|---|",
    ]
    for f in files[:LISTED_FILES]:
        if not f["path"].endswith(".py") or f["kind"] != "code":
            loaded = ""
        elif anywhere is None:
            loaded = "not recorded"
        else:
            loaded = "yes" if f["path"] in anywhere else "**no**"
        lines.append(f"| `{f['path']}` | {f['change']} | {f['kind']} | {loaded} |")
    if len(files) > LISTED_FILES:
        lines.append(f"| and {len(files) - LISTED_FILES} more, listed in report.json | | | |")
    lines.append("")
    if changes.get("compare_url"):
        lines += [f"Diff: [{base[:12]} to the pull request]({changes['compare_url']})", ""]
    elif base != "unknown":
        lines += [
            f"Diff: `git diff {base[:12]}`, which also shows edits made before the contract"
            " was accepted (such as the acceptance tests).",
            "",
        ]
    return lines


def _evidence(report: dict[str, Any], oid: str) -> str:
    ev = (report.get("evidence") or {}).get(oid)
    if not ev:
        return f" (output not linked: {NOT_RECORDED})"
    return f" ([output]({ev['file']}))"


def _test_names(tests: dict[str, str], outcome: str) -> list[str]:
    return [t.rsplit("::", 1)[-1] for t, o in sorted(tests.items()) if o == outcome]


def _verified(report: dict[str, Any]) -> list[str]:
    lines = ["## What was verified", ""]
    if report["readiness"] == "stale":
        changed = report.get("stale_paths") or []
        lines += [
            f"These results are for an earlier state of the files (candidate"
            f" `{report['candidate']['digest'][:19]}...`), not the files as they are now."
            + (f" Changed since: {_paths(changed)}." if changed else ""),
            "",
        ]
    elif report["readiness"] == "invalid" and report.get("integrity_problems"):
        lines += ["The evidence below no longer checks out, so none of it can be relied on.", ""]
    kinds = _kinds(report)
    notes = {o["obligation_id"]: o["note"] for o in report["observations"]}
    per_test = report.get("acceptance_tests")
    passed = sorted(
        (oid for oid, k in kinds.items() if k["status"] == "pass"),
        key=lambda oid: (not kinds[oid]["mandatory"], ORDER.get(kinds[oid]["kind"], 9), oid),
    )
    for oid in passed:
        k = kinds[oid]
        role = "built-in" if k["kind"] == "builtin" else k["kind"]
        level = "mandatory" if k["mandatory"] else "advisory"
        what = "passed"
        if k["kind"] == "acceptance":
            tests = (per_test or {}).get(oid) if per_test is not None else None
            if tests:
                ok = _test_names(tests, "pass")
                shown = ", ".join(ok[:LISTED_TESTS]) + (" ..." if len(ok) > LISTED_TESTS else "")
                what = f"passed, {len(ok)} of {len(tests)} agreed tests: {shown}"
            else:
                what = (
                    "passed; per-test results were not recorded, so this is evidence for the"
                    " check as a whole, not for each agreed case"
                )
        elif notes.get(oid):
            what = f"passed: {_short(notes[oid])}"
        elif oid in BUILTIN:
            what = BUILTIN[oid]
        elif compared(report, oid) != oid:
            what = f"every test in `{compared(report, oid)}` that passed before passes"
        lines.append(f"- `{oid}` ({role}, {level}): {what}{_evidence(report, oid)}")
    if not passed:
        lines.append("Nothing passed.")
    else:
        lines += [
            PASSING_CAVEAT,
            "",
            "Each output link is a copy of the check's recorded output; report.json gives its"
            " digest and evidence record.",
        ]
    return [*lines, ""]


def _unverified(report: dict[str, Any]) -> list[str]:
    lines = ["## What remains unverified", ""]
    if report["readiness"] == "stale":
        lines.append(
            "- Every change made after verification: "
            + (_paths(report.get("stale_paths") or []) or "the contract was revised")
        )
    if report["candidate"].get("changed_during_verification"):
        lines.append(
            "- The files changed while the checks ran: "
            + _paths(report["candidate"].get("changed_paths", []))
        )
    kinds = _kinds(report)
    notes = {o["obligation_id"]: o["note"] for o in report["observations"]}
    reasons = {o["obligation_id"]: o["reasons"] for o in report["gate"]["obligations"]}
    for oid, k in sorted(kinds.items(), key=lambda kv: (not kv[1]["mandatory"], kv[0])):
        if k["status"] == "pass":
            continue
        why = notes.get(oid) or "; ".join(reasons.get(oid) or []) or "no reason recorded"
        level = "mandatory" if k["mandatory"] else "advisory"
        lines.append(f"- `{oid}` ({level}): {k['status']}: {_short(why)}{_evidence(report, oid)}")
    for oid, tests in (report.get("acceptance_tests") or {}).items():
        failing = _test_names(tests or {}, "fail")
        if failing:
            lines.append(f"- Agreed tests that did not pass in `{oid}`: {', '.join(failing)}")
    claims = report.get("claims") or {}
    if claims.get("acceptance") == "none defined":
        lines.append(
            "- Whether the requested outcome is done: no acceptance tests were agreed, so no"
            " check looked for it"
        )
    if claims.get("regression_checks") == 0:
        lines.append("- Tests that passed before the change: none was run again")
    tests = claims.get("tests") or {}
    if tests.get("failed_both_times") or tests.get("skipped_both_times"):
        lines.append(
            f"- {tests['failed_both_times']} test(s) failed and {tests['skipped_both_times']}"
            " were skipped both before and after the change, so they checked nothing"
        )
    still = claims.get("still_failing") or []
    if still:
        lines.append(f"- Tests failing before and still failing: {len(still)}")
    code = _changed_code(report)
    python = [p for p in code if p.endswith(".py")]
    has_acceptance = claims.get("acceptance") in ("met", "not met")
    loaded = _imported(report, "acceptance" if has_acceptance else None)
    if python and loaded is None:
        lines.append(
            "- Code coverage of the change: which changed files the tests imported is not"
            " recorded (only pytest runs record it)"
        )
    elif python and loaded is not None:
        by = "acceptance test" if has_acceptance else "test run"
        lines += [f"- `{p}`: changed, and no {by} imported it" for p in python if p not in loaded]
    other = [p for p in code if not p.endswith(".py")]
    if other:
        lines.append(
            f"- Whether any test ran the changed non-Python code is not recorded: {_paths(other)}"
        )
    protection = report.get("protection", {}).get("verifier", "")
    if protection and not protection.startswith("enforced"):
        lines.append(f"- Isolation of the checks: {protection}")
    lines += [f"- Limitation: {x}" for x in report.get("limitations", [])]
    if len(lines) == 2:
        lines.append("Nothing the records show.")
    return [*lines, ""]


def _decisions(report: dict[str, Any]) -> list[str]:
    asks: list[str] = []
    readiness = report["readiness"]
    claims = report.get("claims") or {}
    if report.get("integrity_problems"):
        asks.append(
            "Do not rely on this report: its evidence no longer checks out. Run"
            " `ohx store check`, then `ohx verify`."
        )
    elif readiness == "stale":
        asks.append(
            "Verify again before deciding: the files or the contract changed after this"
            " verification, so it does not describe what you would merge."
        )
    kinds = _kinds(report)
    failed = [
        oid
        for oid, k in kinds.items()
        if k["mandatory"] and k["status"] != "pass" and readiness != "stale"
    ]
    if failed:
        asks.append(
            f"A mandatory check did not pass ({_paths(failed)}). Send it back to the agent with"
            " the output linked above, or, if the expected behaviour itself is wrong, agree a"
            " new contract revision. A report cannot waive a failed check."
        )
    if claims.get("acceptance") == "none defined" and not failed:
        asks.append(
            "Is the requested outcome done? No agreed test checks it. Judge it from the diff,"
            " or agree acceptance tests with `ohx contract new --acceptance`."
        )
    mutation = next((o for o in report["observations"] if o["obligation_id"] == "mutation"), None)
    if mutation and mutation["outcome"] == "fail" and not failed:
        asks.append(
            "Do these changed lines need a test? Changing them did not make any acceptance"
            f" test fail: {_short(mutation['note'], 400)}"
        )
    code = _changed_code(report)
    has_acceptance = claims.get("acceptance") in ("met", "not met")
    loaded = _imported(report, "acceptance" if has_acceptance else None)
    unloaded = [p for p in code if p.endswith(".py") and loaded is not None and p not in loaded]
    if unloaded and not failed:
        by = "acceptance test" if has_acceptance else "test run"
        asks.append(f"Review by hand: {_paths(unloaded)} changed and no {by} imported it.")
    files = (report.get("changes") or {}).get("files", [])

    def of(kind: str) -> str:
        found = [f"`{f['path']}` ({f['change']})" for f in files if f["kind"] == kind]
        return ", ".join(found[:8]) + (f" and {len(found) - 8} more" if len(found) > 8 else "")

    tests = of("test")
    if tests:
        approval = report.get("approval") or {}
        approved = (
            f" Test changes were approved by {approval['by']}."
            if approval.get("by") and "refused" not in approval
            else ""
        )
        asks.append(
            f"Are the changed tests right? {tests}. A test written with the change can"
            f" only confirm what the change does.{approved}"
        )
    config = of("configuration")
    if config:
        asks.append(
            f"Configuration changed: {config}. It decides what the checks and builds"
            " do; confirm the change is intended."
        )
    deps = of("dependencies")
    if deps:
        asks.append(f"Dependencies changed: {deps}. Check what was added or upgraded.")
    still = claims.get("still_failing") or []
    if still:
        asks.append(
            f"{len(still)} test(s) failed before this change and still fail"
            f" ({', '.join(still[:5])}{' ...' if len(still) > 5 else ''}). Is that expected?"
        )
    protection = report.get("protection", {}).get("verifier", "")
    if protection and not protection.startswith("enforced"):
        asks.append(
            "The checks ran without the sandbox, so code under test could have changed what"
            " they saw. Rely on the result only as far as you trust that code."
        )
    lines = ["## Decisions for you", ""]
    if not asks:
        lines.append("None found in the records. This brief does not replace reading the diff.")
    lines += [f"{n}. {ask}" for n, ask in enumerate(asks, 1)]
    return [*lines, ""]


def render_brief(report: dict[str, Any]) -> list[str]:
    return [
        *_requested(report),
        *_changed(report),
        *_verified(report),
        *_unverified(report),
        *_decisions(report),
    ]
