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
    verify,
)
from openharnx.app.trace import trace_approve, trace_check, trace_init
from openharnx.doctor import run_checks
from openharnx.report import render_markdown

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


def _cmd_init(_: argparse.Namespace) -> int:
    pdir, record = init_project(Path.cwd())
    print(f"project {record.entity_id}")
    print(f"store   {pdir}")
    return EXIT_OK


def _cmd_contract_accept(args: argparse.Namespace) -> int:
    record = accept_contract(Path.cwd(), Path(args.file))
    body = record.body
    print(f"accepted {body['title']!r} as {record.revision_id}")
    for ob in body["obligations"]:
        flag = "mandatory" if ob["mandatory"] else "advisory"
        print(f"  {ob['id']:24} {ob['kind']:11} {flag}")
    return EXIT_OK


def _cmd_contract_new(args: argparse.Namespace) -> int:
    path = new_contract(
        Path.cwd(),
        title=args.title,
        summary=args.summary,
        mode=args.mode,
        acceptance=[Path(p) for p in args.acceptance],
        accept=args.accept,
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
    return EXIT_OK if report["readiness"] == "ready" else EXIT_BLOCKED


def _cmd_report(args: argparse.Namespace) -> int:
    report = current_report(Path.cwd())
    print(json.dumps(report, indent=2) if args.json else render_markdown(report))
    return EXIT_OK if report["readiness"] == "ready" else EXIT_BLOCKED


def _cmd_store_check(_: argparse.Namespace) -> int:
    problems = check_store(Path.cwd())
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohx",
        description="OpenHarnX: plans, staffs, controls and verifies work done by coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"ohx {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    doctor = sub.add_parser("doctor", help="check the local environment OpenHarnX needs")
    doctor.set_defaults(func=_cmd_doctor)

    init = sub.add_parser("init", help="create the OpenHarnX store for this repository")
    init.set_defaults(func=_cmd_init)

    contract = sub.add_parser("contract", help="work contracts")
    csub = contract.add_subparsers(dest="contract_command", metavar="<action>")
    accept = csub.add_parser("accept", help="validate and accept a contract TOML file")
    accept.add_argument("file")
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
    new.set_defaults(func=_cmd_contract_new)

    ver = sub.add_parser("verify", help="verify the current candidate against the contract")
    ver.add_argument("--sandbox", choices=["auto", "srt", "none"], default="auto")
    ver.add_argument("--json", action="store_true")
    ver.set_defaults(func=_cmd_verify)

    rep = sub.add_parser("report", help="show the latest report")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=_cmd_report)

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
    chk.set_defaults(func=_cmd_store_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        code: int = args.func(args)
    except UsageError as exc:
        print(f"ohx: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # last-resort guard so crashes are distinguishable
        print(f"ohx: internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    return code


if __name__ == "__main__":
    raise SystemExit(main())
