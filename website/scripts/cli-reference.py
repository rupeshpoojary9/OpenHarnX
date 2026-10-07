"""Write the CLI reference data from an installed OpenHarnX's own argument parser.

    /path/to/ohx-venv/bin/python scripts/cli-reference.py > content/generated/cli.json

Run it with the interpreter of the release the site documents, never the working tree,
so the reference lists exactly the commands and options that release accepts.
"""

from __future__ import annotations

import argparse
import json
import sys

from openharnx import __version__
from openharnx.cli import build_parser

HIDDEN = {"claude-stop"}  # run by Claude Code itself, not by people


def _option(action: argparse.Action) -> dict[str, object]:
    return {
        "flags": list(action.option_strings) or [action.dest],
        "positional": not action.option_strings,
        "metavar": action.metavar if isinstance(action.metavar, str) else None,
        "takes_value": action.nargs != 0,
        "choices": list(action.choices) if action.choices else None,
        "default": action.default
        if action.default not in (None, False, argparse.SUPPRESS) and action.nargs != 0
        else None,
        "required": bool(action.required),
        "repeatable": isinstance(action, argparse._AppendAction),
        "help": action.help,
    }


def _walk(parser: argparse.ArgumentParser, path: list[str], helps: dict[str, str]) -> list:
    out = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                name = choice.dest
                if name in HIDDEN:
                    continue
                sub = action.choices[name]
                out.extend(_walk(sub, [*path, name], {**helps, name: choice.help or ""}))
    options = [
        _option(a)
        for a in parser._actions
        if not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))
        and a.dest != "version"
    ]
    has_children = any(isinstance(a, argparse._SubParsersAction) for a in parser._actions)
    if path and not has_children:
        out.insert(0, {
            "command": " ".join(["ohx", *path]),
            "help": helps.get(path[-1], ""),
            "usage": " ".join(parser.format_usage().split())[len("usage: "):],
            "options": options,
        })
    return out


def main() -> int:
    commands = _walk(build_parser(), [], {})
    json.dump({"version": __version__, "commands": commands}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
