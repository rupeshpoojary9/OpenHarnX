"""Record-derived report rendering. Zero model calls (DOCS-02)."""

from __future__ import annotations

from typing import Any

READINESS = {
    "pass": "ready",
    "fail": "blocked",
    "unknown": "unknown",
    "invalid_manifest": "invalid",
}
# Every mandatory check passed but no acceptance check was agreed (T91): nothing that
# passed before broke, and whether the task is done is not known.
NO_REGRESSIONS = "no-regressions"
PASSING = frozenset({"ready", NO_REGRESSIONS})
LISTED_STILL_FAILING = 10


def verdict(readiness: str) -> str:
    """The verdict as people read it: READY, NO REGRESSIONS, BLOCKED and so on."""
    return readiness.upper().replace("-", " ")


def _claims_lines(report: dict[str, Any]) -> list[str]:
    claims = report.get("claims")
    if not claims:
        return []
    regress = {True: "yes, every test that passed before still passes", False: "no"}.get(
        claims["no_regressions"], "not known"
    )
    if claims.get("regression_checks") == 0:
        regress = (
            "not checked: this contract runs no test that passed before, so a change that"
            " breaks one would not show"
        )
    acceptance = {
        "met": "met",
        "not met": "not met",
        "none defined": "none: no acceptance tests were agreed, so this does not show that"
        " the task is done; add them with `ohx contract new --acceptance`",
    }[claims["acceptance"]]
    lines = ["## What this verdict supports", "", f"- No regressions: {regress}"]
    tests = claims.get("tests")
    if tests:
        line = f"- Tests: {tests['checked']} of {tests['ran']} tests checked this change"
        failed, skipped = tests["failed_both_times"], tests["skipped_both_times"]
        parts = [f"{failed} failed"] if failed else []
        if skipped:
            parts.append(f"{skipped} {'was' if skipped == 1 else 'were'} skipped")
        if parts:
            line += f"; {' and '.join(parts)} both before and after, so they checked nothing"
        lines.append(line)
    lines.append(f"- Acceptance criteria: {acceptance}")
    still = claims["still_failing"]
    if still:
        shown = ", ".join(still[:LISTED_STILL_FAILING])
        more = f" and {len(still) - LISTED_STILL_FAILING} more" if len(still) > 10 else ""
        lines.append(f"- Still failing, as before this change: {len(still)} test(s): {shown}{more}")
    return [*lines, ""]


def _reasons(reasons: list[str]) -> str:
    """Reasons joined for reading; a checker's note (": ...") follows its reason directly."""
    text = ""
    for r in reasons:
        text += r if not text or r.startswith(": ") else f"; {r}"
    return text or "none"


def _ci_line(report: dict[str, Any]) -> list[str]:
    ci = report.get("ci")
    if not ci:
        return []
    return [
        f"- Pull request head `{ci['head_commit'][:12]}` judged against base"
        f" `{ci['base_commit'][:12]}` ({ci['base_ref']}): its tests, policy and checks"
    ]


def _signature_line(report: dict[str, Any]) -> list[str]:
    sig = report.get("signature")
    if not sig:
        return []
    if sig["status"] != "signed":
        return ["- Signature: not signed"]
    signer = sig.get("signer") or {}
    return [f"- Signature: signed by {signer.get('name', 'unknown')}, key {sig['fingerprint']}"]


def _approval_line(report: dict[str, Any]) -> list[str]:
    approval = report.get("approval")
    if not approval:
        return []
    if "refused" in approval:
        return [f"- Test changes: not approved ({approval['refused']})"]
    if approval.get("method") == "signature":
        return [
            f"- Test changes: approved by {approval['by']} with an SSH signature"
            f" (key {approval['key']}), for commit `{approval['head'][:12]}`"
        ]
    return [
        f"- Test changes: approved by @{approval['by']} with the `{approval['label']}` label"
        f" at {approval['at']}, for commit `{approval['head'][:12]}`"
    ]


def render_markdown(report: dict[str, Any]) -> str:
    gate = report["gate"]
    cand = report["candidate"]
    lines = [f"# OpenHarnX report: {verdict(report['readiness'])}", ""]
    if report.get("integrity_problems"):
        lines += [
            f"This report was {report['verified_readiness']}, but its evidence no longer"
            " checks out, so it cannot be trusted. Run `ohx store check`, then `ohx verify`.",
            "",
            *[f"- {problem}" for problem in report["integrity_problems"]],
            "",
        ]
    elif report["readiness"] == "stale":
        lines += [
            f"This report was {report['verified_readiness']} for an earlier state. Run"
            " `ohx verify` again.",
            "",
            *[f"- {reason}" for reason in report["stale_reasons"]],
            *[f"- changed: {path}" for path in report.get("stale_paths", [])],
            "",
        ]
    lines += [
        f"- Contract: {report['contract']['title']} ({report['contract']['revision_id']})",
        f"- Candidate: `{cand['digest']}` (base commit {cand['base_commit']})",
        *_ci_line(report),
        *_approval_line(report),
        f"- Gate: **{gate['result']}**, evidence coverage {gate['coverage_percent']}%",
        f"- Verifier protection: {report['protection']['verifier']}",
        *_signature_line(report),
        "",
        *_claims_lines(report),
        "## Obligations",
        "",
        "| Obligation | Mandatory | Status | Reasons |",
        "|---|---|---|---|",
    ]
    order = {"fail": 0, "unknown": 1, "pass": 2}
    for ob in sorted(gate["obligations"], key=lambda o: order[o["status"]]):
        reasons = _reasons(ob["reasons"])
        mandatory = "yes" if ob["mandatory"] else "no"
        lines.append(f"| {ob['obligation_id']} | {mandatory} | {ob['status']} | {reasons} |")
    if cand["changed_during_verification"]:
        lines += ["", f"Candidate changed during verification: {', '.join(cand['changed_paths'])}"]
    cost = report["cost"]
    lines += [
        "",
        "## Cost",
        "",
        f"- Agent work: {cost['agent_work']}",
        f"- OpenHarnX overhead: {cost['overhead']['model_calls']} model calls,"
        f" verifier time {cost['overhead']['verifier_ms']} ms",
        "",
        "## Changelog entry",
        "",
        report["changelog_entry"],
        "",
        "## Limitations",
        "",
        *[f"- {x}" for x in report["limitations"]],
        "",
        f"This report authorizes nothing. {report['authorizes']}",
        "",
    ]
    return "\n".join(lines)
