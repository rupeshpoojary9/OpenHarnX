"""Command-line entry point for `ohx`.

Exit codes (Architecture §15):
  0   success or ready
  10  valid result that is blocked, unknown or failing a required check
  2   usage or input error
  1   internal failure
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from openharnx import __version__
from openharnx.doctor import run_checks

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohx",
        description="OpenHarnX: plans, staffs, controls and verifies work done by coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"ohx {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    doctor = sub.add_parser("doctor", help="check the local environment OpenHarnX needs")
    doctor.set_defaults(func=_cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        code: int = args.func(args)
    except Exception as exc:  # last-resort guard so crashes are distinguishable
        print(f"ohx: internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    return code


if __name__ == "__main__":
    raise SystemExit(main())
