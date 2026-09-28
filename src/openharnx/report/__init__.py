"""Record-derived report rendering. Zero model calls (DOCS-02)."""

from __future__ import annotations

from typing import Any

READINESS = {
    "pass": "ready",
    "fail": "blocked",
    "unknown": "unknown",
    "invalid_manifest": "invalid",
}


def render_markdown(report: dict[str, Any]) -> str:
    gate = report["gate"]
    cand = report["candidate"]
    lines = [f"# OpenHarnX report: {report['readiness'].upper()}", ""]
    if report["readiness"] == "stale":
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
        f"- Gate: **{gate['result']}**, evidence coverage {gate['coverage_percent']}%",
        f"- Verifier protection: {report['protection']['verifier']}",
        "",
        "## Obligations",
        "",
        "| Obligation | Mandatory | Status | Reasons |",
        "|---|---|---|---|",
    ]
    order = {"fail": 0, "unknown": 1, "pass": 2}
    for ob in sorted(gate["obligations"], key=lambda o: order[o["status"]]):
        reasons = "; ".join(ob["reasons"]) or "none"
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
