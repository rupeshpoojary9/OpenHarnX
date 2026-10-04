"""Command-line entry point for `ohx`.

Exit codes (Architecture §15):
  0   success or ready
  10  valid result that is blocked, unknown or failing a required check
  2   usage or input error
  1   internal failure
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from openharnx import __version__
from openharnx.app import (
    UsageError,
    accept_contract,
    check_store,
    current_report,
    init_project,
    new_contract,
    sign_evidence,
    verify,
)
from openharnx.app.audit import audit_trail
from openharnx.app.bug import bug_approve, bug_fix, bug_new, bug_show, describe_proposed
from openharnx.app.gate import gate, lock_tests
from openharnx.app.hook import install as hook_install
from openharnx.app.hook import main_stop as hook_main_stop
from openharnx.app.signed_approval import NOTES_REF
from openharnx.app.signed_approval import approve as approve_tests
from openharnx.app.trace import trace_approve, trace_check, trace_init
from openharnx.doctor import run_checks
from openharnx.report import PASSING, render_markdown
from openharnx.signing import SigningError

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_BLOCKED = 10


def _cmd_doctor(_: argparse.Namespace) -> int:
    results = run_checks()
    for r in results:
        status = "ok" if r.ok else ("FAIL" if r.required else "warn")
        print(f"{status:4}  {r.name}: {r.detail}")
    failed = [r for r in results if r.required and not r.ok]
    if failed:
        print(f"\n{len(failed)} required check(s) failed.", file=sys.stderr)
        return EXIT_BLOCKED
    return EXIT_OK


def _cmd_init(args: argparse.Namespace) -> int:
    pdir, record = init_project(Path.cwd())
    print(f"project {record.entity_id}")
    print(f"store   {pdir}")
    if args.lock_tests:
        accepted, raw = lock_tests(Path.cwd(), sandbox=args.sandbox)
        print(f"locked  the existing tests as {accepted.revision_id}:")
        for ob in accepted.body["obligations"]:
            mandatory = "mandatory" if ob["mandatory"] else "advisory"
            print(f"  {ob['id']:<28} {mandatory}")
        print("run `ohx verify` after any change; lock again to accept a deliberate test change")
    return EXIT_OK


def _cmd_contract_accept(args: argparse.Namespace) -> int:
    record = accept_contract(Path.cwd(), Path(args.file), sandbox=args.sandbox)
    body = record.body
    print(f"accepted {body['title']!r} as {record.revision_id}")
    for ob in body["obligations"]:
        flag = "mandatory" if ob["mandatory"] else "advisory"
        print(f"  {ob['id']:24} {ob['kind']:11} {flag}")
    for suite, base in body.get("regression_baseline", {}).items():
        tests = base["tests"]
        if tests is None:
            print(
                f"  baseline for {suite}: suite ended with {base['outcome']}, no per-test results"
            )
        else:
            failing = sum(1 for o in tests.values() if o == "fail")
            print(
                f"  baseline for {suite}: {len(tests)} tests, {failing} failing before this change"
            )
    return EXIT_OK


def _cmd_contract_new(args: argparse.Namespace) -> int:
    path = new_contract(
        Path.cwd(),
        title=args.title,
        summary=args.summary,
        mode=args.mode,
        acceptance=[Path(p) for p in args.acceptance],
        accept=args.accept,
        sandbox=args.sandbox,
    )
    print(f"wrote {path}")
    if args.accept:
        print("accepted")
    return EXIT_OK


def _cmd_verify(args: argparse.Namespace) -> int:
    record, run_dir = verify(Path.cwd(), sandbox=args.sandbox)
    report = record.body
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
        print(f"Saved to {run_dir}")
    return EXIT_OK if report["readiness"] in PASSING else EXIT_BLOCKED


def _cmd_hook_install(_: argparse.Namespace) -> int:
    path = hook_install(Path.cwd())
    print(f"installed the Claude Code Stop hook in {path}")
    print("when the agent says it is done, OpenHarnX verifies; BLOCKED goes back to the agent")
    return EXIT_OK


def _cmd_hook_claude_stop(args: argparse.Namespace) -> int:
    # Exit code 2 would tell Claude Code to block with stderr as the reason, so this hook
    # always exits 0 and answers in JSON, problems included.
    try:
        answer = hook_main_stop(args.sandbox)
    except Exception as exc:  # any failure must reach the owner, not block the agent
        answer = {"systemMessage": f"OpenHarnX could not verify: {exc}"}
    if answer:
        print(json.dumps(answer))
    return EXIT_OK


def _cmd_report(args: argparse.Namespace) -> int:
    report = current_report(Path.cwd())
    print(json.dumps(report, indent=2) if args.json else render_markdown(report))
    return EXIT_OK if report["readiness"] in PASSING else EXIT_BLOCKED


def _cmd_store_check(args: argparse.Namespace) -> int:
    problems, signatures = check_store(Path.cwd(), args.signer)
    for line in signatures:
        print(line)
    for p in problems:
        print(p)
    print("store ok" if not problems else f"{len(problems)} problem(s)")
    return EXIT_OK if not problems else EXIT_BLOCKED


ORDER = [
    "untracked",
    "stale",
    "invalid",
    "not built",
    "open",
    "dropped (not approved)",
    "verified",
    "linked",
    "dropped (approved)",
]


def _cmd_trace_init(args: argparse.Namespace) -> int:
    path, added, removed = trace_init(Path.cwd(), args.sources, args.out)
    print(f"wrote {path}: {added} new unit(s), {removed} removed")
    return EXIT_OK


def _cmd_trace_check(args: argparse.Namespace) -> int:
    report = trace_check(Path.cwd(), args.trace, run=args.run)
    rank = {s: i for i, s in enumerate(ORDER)}
    for r in sorted(report.results, key=lambda r: rank.get(r.state, 0)):
        if r.state in ("verified", "linked", "dropped (approved)") and not args.all:
            continue
        text = r.text if len(r.text) <= 70 else r.text[:67] + "..."
        print(f"{r.id:14} {r.state.upper():24} {text}")
        if r.reason:
            print(f"{'':14} {'':24} {r.reason}")
    summary = ", ".join(f"{n} {s}" for s in ORDER if (n := report.counts.get(s, 0)))
    print(("trace ok: " if report.ok else "trace BLOCKED: ") + (summary or "no units"))
    return EXIT_OK if report.ok else EXIT_BLOCKED


def _cmd_trace_approve(args: argparse.Namespace) -> int:
    if not args.yes:
        print("This records your approval of every unit marked context or excluded.")
        print("Review them with `ohx trace check --all`, then rerun with --yes.")
        return EXIT_BLOCKED
    drops, _ = trace_approve(Path.cwd(), args.trace)
    for d in drops:
        print(f"{d.id:14} {d.status:9} {d.note or '':20} {d.text[:60]}")
    print(f"approved {len(drops)} dropped unit(s)")
    return EXIT_OK


def _cmd_gate(args: argparse.Namespace) -> int:
    report = gate(
        Path.cwd(),
        args.base,
        sandbox=args.sandbox,
        out=Path(args.out),
        contract=args.contract,
        home=Path(args.home) if args.home else None,
        approve_label=args.approve_tests_label or None,
        approval_file=Path(args.approval_file) if args.approval_file else None,
    )
    print(render_markdown(report))
    print(f"Saved to {Path(args.out).resolve()}")
    return EXIT_OK if report["readiness"] in PASSING else EXIT_BLOCKED


def _cmd_approve_tests(args: argparse.Namespace) -> int:
    try:
        commit, where = approve_tests(Path.cwd(), args.rev, Path(args.out) if args.out else None)
    except SigningError as exc:
        print(f"ohx: cannot approve: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"approved the test changes of commit {commit[:12]}; signature in {where}")
    if not args.out:
        print(f"share it with: git push origin {NOTES_REF}")
    return EXIT_OK


def _cmd_audit(args: argparse.Namespace) -> int:
    for line in audit_trail(Path.cwd()):
        print(line)
    return EXIT_OK


def _say(line: str) -> None:
    print(line, flush=True)


def _cmd_bug_new(args: argparse.Namespace) -> int:
    bug, proposal = bug_new(Path.cwd(), args.symptom, sandbox=args.sandbox, progress=_say)
    body = bug.body
    print(f"{body['id']}: {body['symptom']}")
    if proposal:
        print("\n" + proposal.strip() + "\n")
    if "reproduction_tests" in body:
        print("Proposed tests, locked as the oracle if you approve:")
        for line in describe_proposed(body["reproduction_tests"]):
            print(line)
        print(f"Read them in full: ohx bug show {body['id']}\n")
    if body["status"] == "proposed":
        print("The investigation reproduces the bug: its tests fail on the current code.")
        print(f"If the rule and the tests are right: ohx bug approve {body['id']}")
        return EXIT_OK
    print(f"Investigation rejected: {body.get('reason', body['status'])}")
    return EXIT_BLOCKED


def _cmd_bug_show(args: argparse.Namespace) -> int:
    body, proposal, tests = bug_show(Path.cwd(), args.bug)
    print(f"{body['id']}: {body['symptom']} ({body['status']})")
    if proposal:
        print("\n" + proposal.strip())
    if tests:
        print(f"\nProposed tests ({body.get('test_file', 'not yet written to the repository')}):\n")
        print(tests.rstrip())
    return EXIT_OK


def _cmd_bug_approve(args: argparse.Namespace) -> int:
    path = bug_approve(Path.cwd(), args.bug)
    print(f"approved {args.bug}; contract {path.name} accepted, tests locked")
    print(f"Next: ohx bug fix {args.bug}")
    return EXIT_OK


def _cmd_bug_fix(args: argparse.Namespace) -> int:
    report = bug_fix(
        Path.cwd(),
        args.bug,
        sandbox=args.sandbox,
        attempts=args.attempts,
        budget_usd=args.budget,
        progress=_say,
    )
    if not report:
        print(f"{args.bug}: budget of ${args.budget:.2f} already spent; no attempt made")
        return EXIT_BLOCKED
    print(render_markdown(report))
    if report["readiness"] == "ready":
        print("Next: review the change (git diff), then commit it.")
        return EXIT_OK
    print(f"Next: read the failures above; rerun `ohx bug fix {args.bug}` or revise the contract.")
    return EXIT_BLOCKED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohx",
        description="OpenHarnX: verifies work done by coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"ohx {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    doctor = sub.add_parser("doctor", help="check the local environment OpenHarnX needs")
    doctor.set_defaults(func=_cmd_doctor)

    init = sub.add_parser("init", help="create the OpenHarnX store for this repository")
    init.add_argument(
        "--lock-tests",
        action="store_true",
        help="make the existing test suite the contract (no contract file to write)",
    )
    init.add_argument(
        "--sandbox",
        choices=["auto", "srt", "none"],
        default="auto",
        help="where the suite's baseline runs (with --lock-tests)",
    )
    init.set_defaults(func=_cmd_init)

    hook = sub.add_parser("hook", help="agent hooks (Claude Code)")
    hsub = hook.add_subparsers(dest="hook_command", metavar="<action>")
    hinstall = hsub.add_parser("install", help="add the Stop hook to .claude/settings.local.json")
    hinstall.set_defaults(func=_cmd_hook_install)
    hstop = hsub.add_parser("claude-stop", help="run by Claude Code when the agent stops")
    hstop.add_argument("--sandbox", choices=["auto", "srt", "none"], default="auto")
    hstop.set_defaults(func=_cmd_hook_claude_stop)

    contract = sub.add_parser("contract", help="work contracts")
    csub = contract.add_subparsers(dest="contract_command", metavar="<action>")
    accept = csub.add_parser("accept", help="validate and accept a contract TOML file")
    accept.add_argument("file")
    accept.add_argument(
        "--sandbox",
        choices=["auto", "srt", "none"],
        default="auto",
        help="where the regression baseline runs",
    )
    accept.set_defaults(func=_cmd_contract_accept)
    new = csub.add_parser("new", help="write a contract from project defaults")
    new.add_argument("--title", required=True)
    new.add_argument("--summary", required=True, help="one line; becomes the changelog entry")
    new.add_argument("--mode", choices=["bugfix", "task"], default="bugfix")
    new.add_argument(
        "--acceptance",
        action="append",
        required=True,
        help="test file or folder that proves the change; locked away at acceptance",
    )
    new.add_argument("--accept", action="store_true", help="accept it straight away")
    new.add_argument(
        "--sandbox",
        choices=["auto", "srt", "none"],
        default="auto",
        help="where the regression baseline runs when accepting",
    )
    new.set_defaults(func=_cmd_contract_new)

    ver = sub.add_parser("verify", help="verify the current candidate against the contract")
    ver.add_argument("--sandbox", choices=["auto", "srt", "none"], default="auto")
    ver.add_argument("--json", action="store_true")
    ver.set_defaults(func=_cmd_verify)

    apt = sub.add_parser(
        "approve-tests", help="sign an approval of a commit's intended test changes (any platform)"
    )
    apt.add_argument("rev", nargs="?", default="HEAD", help="the commit to approve (default HEAD)")
    apt.add_argument("--out", help="write the signature to this file instead of a git note")
    apt.set_defaults(func=_cmd_approve_tests)
    gat = sub.add_parser("gate", help="CI: judge the checked-out change against its base commit")
    gat.add_argument("--base", required=True, help="base commit or ref (the trusted side)")
    gat.add_argument("--sandbox", choices=["auto", "srt", "none"], default="auto")
    gat.add_argument("--out", default="ohx-gate", help="folder for report.json and report.md")
    gat.add_argument("--contract", help="a contract file in the base commit, instead of its tests")
    gat.add_argument("--home", help="keep the evidence store here (default: a throwaway one)")
    gat.add_argument(
        "--approve-tests-label",
        help="GitHub label with which a maintainer approves the pull request's test changes",
    )
    gat.add_argument(
        "--approval-file", help="a signature from `ohx approve-tests --out`, instead of git notes"
    )
    gat.set_defaults(func=_cmd_gate)

    aud = sub.add_parser("audit", help="who did what and touched what, from the evidence store")
    aud.set_defaults(func=_cmd_audit)

    rep = sub.add_parser("report", help="show the latest report")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=_cmd_report)

    bug = sub.add_parser("bug", help="issue to verified fix, driven through an agent")
    bsub = bug.add_subparsers(dest="bug_command", metavar="<action>")
    bnew = bsub.add_parser("new", help="report a bug; the agent investigates read-only")
    bnew.add_argument("symptom", help="what is wrong, as a user would report it")
    bnew.add_argument("--sandbox", choices=["srt", "none"], default="srt")
    bnew.set_defaults(func=_cmd_bug_new)
    bshow = bsub.add_parser("show", help="print the proposal and the proposed tests in full")
    bshow.add_argument("bug")
    bshow.set_defaults(func=_cmd_bug_show)
    bapp = bsub.add_parser("approve", help="accept the proposed rule and tests as the contract")
    bapp.add_argument("bug")
    bapp.set_defaults(func=_cmd_bug_approve)
    bfix = bsub.add_parser("fix", help="assign the contract to the agent and verify")
    bfix.add_argument("bug")
    bfix.add_argument("--sandbox", choices=["srt", "none"], default="srt")
    bfix.add_argument("--attempts", type=int, default=2)
    bfix.add_argument("--budget", type=float, default=2.0, help="USD cap across this bug's runs")
    bfix.set_defaults(func=_cmd_bug_fix)

    trace = sub.add_parser("trace", help="trace requirements back to their sources")
    tsub = trace.add_subparsers(dest="trace_command", metavar="<action>")
    tinit = tsub.add_parser("init", help="split sources into numbered units (merges markings)")
    tinit.add_argument("sources", nargs="+", help="BRD, decisions or other requirement files")
    tinit.add_argument("--out", default="trace.toml")
    tinit.set_defaults(func=_cmd_trace_init)
    tcheck = tsub.add_parser("check", help="report every unit; blocks on any gap")
    tcheck.add_argument("--trace", default="trace.toml")
    tcheck.add_argument("--run", action="store_true", help="run the linked tests")
    tcheck.add_argument("--all", action="store_true", help="also list covered units")
    tcheck.set_defaults(func=_cmd_trace_check)
    tapprove = tsub.add_parser("approve", help="approve the units marked context or excluded")
    tapprove.add_argument("--trace", default="trace.toml")
    tapprove.add_argument("--yes", action="store_true")
    tapprove.set_defaults(func=_cmd_trace_approve)

    store = sub.add_parser("store", help="evidence store maintenance")
    ssub = store.add_subparsers(dest="store_command", metavar="<action>")
    chk = ssub.add_parser("check", help="verify the hash chain and record digests")
    chk.add_argument(
        "--signer",
        action="append",
        help="expected signing key: a public key file or a SHA256 fingerprint; repeatable",
    )
    chk.set_defaults(func=_cmd_store_check)
    return parser


# Commands that write evidence; each ends by signing the chain head (T87 item 4).
WRITERS = {"init", "contract", "verify", "bug", "trace", "hook"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        code: int = args.func(args)
        if args.command in WRITERS:
            note = sign_evidence(Path.cwd())
            if note:
                print(note, file=sys.stderr)
    except UsageError as exc:
        print(f"ohx: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # last-resort guard so crashes are distinguishable
        print(f"ohx: internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    return code


if __name__ == "__main__":
    raise SystemExit(main())
