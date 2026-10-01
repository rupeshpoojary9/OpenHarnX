"""Semantic validation of a work contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MODES = frozenset({"bugfix", "task"})
KINDS = frozenset({"acceptance", "regression", "check"})
ENVIRONMENTS = frozenset({"uv"})


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_contract(raw: Mapping[str, Any]) -> list[str]:
    """Return named errors; an empty list means the contract is acceptable."""
    errors: list[str] = []
    if not _nonempty_str(raw.get("title")):
        errors.append("title: required")
    if raw.get("mode") not in MODES:
        errors.append(f"mode: must be one of {sorted(MODES)}")
    # The changelog entry is generated from this, so Lite requires it for a bug fix.
    if not _nonempty_str(raw.get("change_summary")):
        errors.append("change_summary: required")

    python = raw.get("python")
    if python is not None and not _nonempty_str(python):
        errors.append("python: must be a path")
    environment = raw.get("environment")
    if environment is not None and environment not in ENVIRONMENTS:
        errors.append(f"environment: must be one of {sorted(ENVIRONMENTS)}")

    obligations = raw.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        errors.append("obligations: at least one is required")
        return errors

    seen: set[str] = set()
    mandatory_acceptance = False
    for i, ob in enumerate(obligations):
        where = f"obligations[{i}]"
        if not isinstance(ob, Mapping):
            errors.append(f"{where}: must be a table")
            continue
        oid = ob.get("id")
        if not isinstance(oid, str) or not oid.strip():
            errors.append(f"{where}.id: required")
        elif oid in seen:
            errors.append(f"{where}.id: duplicate {oid!r}")
        else:
            seen.add(oid)
        kind = ob.get("kind")
        if kind not in KINDS:
            errors.append(f"{where}.kind: must be one of {sorted(KINDS)}")
        mandatory = ob.get("mandatory")
        if not isinstance(mandatory, bool):
            errors.append(f"{where}.mandatory: must be true or false")
        command = ob.get("command")
        if not (isinstance(command, list) and command and all(_nonempty_str(c) for c in command)):
            errors.append(f"{where}.command: must be a non-empty list of strings")
        timeout = ob.get("timeout_s", 300)
        if not (isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0):
            errors.append(f"{where}.timeout_s: must be a positive integer")
        env = ob.get("env", {})
        if not (
            isinstance(env, Mapping)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        ):
            errors.append(f"{where}.env: must map strings to strings")
        protected = ob.get("protected")
        if protected is not None and not _nonempty_str(protected):
            errors.append(f"{where}.protected: must be a path")
        if kind == "acceptance" and mandatory is True:
            mandatory_acceptance = True

    if not mandatory_acceptance:
        errors.append("obligations: at least one mandatory acceptance obligation is required")
    return errors
