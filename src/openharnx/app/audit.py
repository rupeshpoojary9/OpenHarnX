"""`ohx audit`: who did what and touched what, read back from the evidence store (T87 item 3).

Agent runs carry the files they changed as OpenHarnX observed them, from
snapshots taken before and after the run. Any difference between two recorded
states that no recorded actor accounts for is shown as made outside OpenHarnX,
so work by another agent or a person still appears, with its author unknown.
Identities are as declared (git configuration, the agent's own report) until
evidence is signed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openharnx.app import _open
from openharnx.store import Record, Store
from openharnx.workspace import changed_paths

LISTED = 10


def _when(rec: Record) -> str:
    return rec.recorded_at.replace("T", " ")[:19] + "Z"


def _who(person: dict[str, str] | None) -> str:
    if not person:
        return "unknown"
    return f"{person.get('name', 'unknown')} <{person.get('email', 'unknown')}>"


def _paths(paths: list[str]) -> str:
    if not paths:
        return "nothing"
    shown = ", ".join(paths[:LISTED])
    return shown + (f" and {len(paths) - LISTED} more" if len(paths) > LISTED else "")


def _manifest(store: Store, blob: str | None) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        data: dict[str, Any] = json.loads(store.blob_path(blob).read_bytes())
    except (OSError, ValueError):
        return None
    return data


def _agent(rec: Record) -> str:
    agent: dict[str, str] = rec.body.get("agent") or {}
    name = agent.get("adapter", "unknown agent")
    if agent.get("command"):
        name += f" ({agent['command']})"
    details = ", ".join(
        f"{label} {agent.get(key, 'unknown')}"
        for label, key in (("version", "version"), ("model", "model"), ("session", "session"))
    )
    cost = rec.body.get("cost_usd", "unknown")
    cost = f"${cost:.2f}" if isinstance(cost, (int, float)) else str(cost)
    changed = rec.body.get("changed_paths")
    touched = "changed unknown files" if changed is None else f"changed {_paths(changed)}"
    return (
        f"agent    {name}, {details}: {rec.body.get('phase')} {rec.body.get('bug')}"
        f" attempt {rec.body.get('attempt')}; {touched}; cost {cost}; {rec.body.get('protection')}"
    )


def _bug(rec: Record) -> str:
    b = rec.body
    status = b.get("status")
    if status == "investigating":
        return f"bug      {b['id']} reported: {b.get('symptom')}"
    if status == "approved":
        return f"bug      {b['id']} approved by {_who(b.get('approved_by'))}: tests locked"
    if status == "rejected":
        return f"bug      {b['id']} rejected: {b.get('reason', 'no reason recorded')}"
    if status == "proposed":
        return f"bug      {b['id']} proposal ready; its tests fail on the current code"
    return f"bug      {b['id']} {status}"


def audit_trail(cwd: Path) -> list[str]:
    _, _, store = _open(cwd)
    try:
        lines: list[str] = []
        state: dict[str, Any] | None = None  # the last recorded state of the tree
        source = ""

        def outside(now: dict[str, Any] | None, when: str, own: list[str] | None = None) -> None:
            if state is None or now is None:
                return
            mine = own or []
            paths = [
                p
                for p in changed_paths(state, now)
                if not any(p == o or p.startswith(o + "/") for o in mine)
            ]
            if paths:
                lines.append(
                    f"{when}  outside  changed outside OpenHarnX (no recorded actor)"
                    f" since {source}: {_paths(paths)}"
                )

        for rec in store.history():
            when = _when(rec)
            kind = rec.entity_type
            if kind == "project":
                lines.append(f"{when}  project  initialised for {rec.body.get('repository_path')}")
            elif kind == "bug":
                lines.append(f"{when}  {_bug(rec)}")
            elif kind == "contract":
                accepted = _manifest(store, rec.body.get("accepted_manifest_blob"))
                own = rec.body.get("accepted_paths", [])
                outside(accepted, when, own)
                lines.append(
                    f"{when}  contract accepted {rec.body.get('title')!r}"
                    f" by {_who(rec.body.get('accepted_by'))}"
                    + (f"; contract and acceptance tests: {_paths(own)}" if own else "")
                )
                if accepted is not None:
                    state, source = accepted, "the contract was accepted"
            elif kind == "agent_run":
                outside(_manifest(store, rec.body.get("before_manifest_blob")), when)
                lines.append(f"{when}  {_agent(rec)}")
                after = _manifest(store, rec.body.get("after_manifest_blob"))
                if after is not None:
                    state, source = after, "the last agent run"
            elif kind == "candidate":
                outside(rec.body, when)
                lines.append(f"{when}  verify   candidate {rec.body.get('digest', '')[:19]}")
                state, source = rec.body, "the last verification"
            elif kind == "signature":
                signer = rec.body.get("signer")
                lines.append(
                    f"{when}  signed   records 1 to {rec.body.get('seq')} by {_who(signer)},"
                    f" key {rec.body.get('fingerprint')}"
                )
            elif kind == "assurance_report":
                lines.append(f"{when}  verdict  {str(rec.body.get('readiness')).upper()}")
        return lines
    finally:
        store.close()
