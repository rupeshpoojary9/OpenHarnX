"""Built-in checks and the sandbox: names, obligations and read-deny lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openharnx.app.core import UsageError, ohx_home
from openharnx.sandbox import find_srt

WEAKENING = "weakening"


# Added to every contract at acceptance (T77 item 9); run by OpenHarnX, not a command.
WEAKENING_OBLIGATION: dict[str, Any] = {
    "id": WEAKENING,
    "kind": "check",
    "mandatory": True,
    "builtin": WEAKENING,
    "command": ["ohx", "builtin", WEAKENING],
    "timeout_s": 300,
    "env": {},
}


NO_NEW_FAILURES = "no-new-failures"


LISTED_EDITED = 10


MUTATION = "mutation"


# Added at acceptance to contracts with acceptance tests (T87 item 5). Advisory: it names
# the mutants of the change that the acceptance tests let through, and never blocks.
MUTATION_OBLIGATION: dict[str, Any] = {
    "id": MUTATION,
    "kind": "check",
    "mandatory": False,
    "builtin": MUTATION,
    "command": ["ohx", "builtin", MUTATION],
    "timeout_s": 300,
    "env": {},
}


# Seconds the mutation check may spend unless the contract says otherwise (T97). No mutant
# starts once the acceptance tests' own run time would take the check past it.
MUTATION_BUDGET_S = 120


DENY_READ = ["~/.ssh"]  # plus the keys directory, see _deny_read


def _reserved(obligation_id: str) -> bool:
    return obligation_id in (WEAKENING, MUTATION) or obligation_id.startswith(NO_NEW_FAILURES)


def _no_new_failures(of: str, single: bool) -> dict[str, Any]:
    """Added at acceptance for each advisory regression suite (T87 item 1)."""
    return {
        "id": NO_NEW_FAILURES if single else f"{NO_NEW_FAILURES}-{of}",
        "kind": "check",
        "mandatory": True,
        "builtin": NO_NEW_FAILURES,
        "of": of,
        "command": ["ohx", "builtin", NO_NEW_FAILURES, of],
        "timeout_s": 300,
        "env": {},
    }


def _deny_read() -> list[str]:
    return [*DENY_READ, str(ohx_home() / "keys")]


def _checker_srt(sandbox: str) -> Path | None:
    srt = find_srt() if sandbox in ("auto", "srt") else None
    if sandbox == "srt" and srt is None:
        raise UsageError("sandbox `srt` requested but not found (set OHX_SRT)")
    return srt
