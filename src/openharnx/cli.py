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
    init_project,
    latest_report,
    verify,
)
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
    report = latest_report(Path.cwd()).body
    print(json.dumps(report, indent=2) if args.json else render_markdown(report))
    return EXIT_OK if report["readiness"] == "ready" else EXIT_BLOCKED


def _cmd_store_check(_: argparse.Namespace) -> int:
    problems = check_store(Path.cwd())
    for p in problems:
        print(p)
    print("store ok" if not problems else f"{len(problems)} problem(s)")
    return EXIT_OK if not problems else EXIT_BLOCKED


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

    ver = sub.add_parser("verify", help="verify the current candidate against the contract")
    ver.add_argument("--sandbox", choices=["auto", "srt", "none"], default="auto")
    ver.add_argument("--json", action="store_true")
    ver.set_defaults(func=_cmd_verify)

    rep = sub.add_parser("report", help="show the latest report")
    rep.add_argument("--json", action="store_true")
    rep.set_defaults(func=_cmd_report)

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
