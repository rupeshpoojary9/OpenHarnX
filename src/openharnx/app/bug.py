"""`ohx bug`: issue -> read-only investigation -> owner approval -> contract ->
agent fix -> verification, with the failure fed back for a limited number of
attempts. The owner makes one decision: whether the proposed rule is right.
"""

from __future__ import annotations

import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any

from openharnx.agent import DEFAULT_COMMAND, AgentRun, launch
from openharnx.app import (
    UsageError,
    _open,
    new_contract,
    now_utc,
    ohx_home,
    verify,
)
from openharnx.sandbox import find_srt
from openharnx.store import Record, Store
from openharnx.verify import run_obligation
from openharnx.workspace import build_manifest

INVESTIGATE = """You are investigating a bug report for this repository.
Do not modify any file in the repository.

Bug report: {symptom}

Write exactly two files into the directory {out}:
1. proposal.md: the cause (file and line), then the rule the code must follow,
   on a line starting "Rule:".
2. test_proposed.py: pytest tests that express the whole rule, including
   boundary cases, not only the reported example. They must fail on the
   current code and pass once it is fixed. Import the code the way the
   project's own tests do.

Stop after writing the two files."""

FIX = """Fix this bug in the repository.

Bug report: {symptom}

Approved investigation:
{proposal}

The approved tests are in {test_path}. OpenHarnX judges your work with a
locked copy of them, so editing them cannot help: change the code, not the
tests. Run the tests to check your work, then stop.
{feedback}"""


def _srt_for(sandbox: str) -> Path | None:
    if sandbox == "none":
        return None
    srt = find_srt()
    if srt is None or not srt.exists():
        raise UsageError(
            "agents run only inside the srt sandbox; install srt (or set OHX_SRT),"
            " or pass --sandbox none to run the agent without isolation"
        )
    return srt


def _agent_command(root: Path, sandbox: str) -> list[str]:
    cfg = root / "ohx.toml"
    command = None
    if cfg.exists():
        command = tomllib.loads(cfg.read_text()).get("agent", {}).get("command")
    if not command:
        command = list(DEFAULT_COMMAND)
        if sandbox == "none":  # without the OS boundary, never skip the agent's own checks
            command[command.index("bypassPermissions")] = "acceptEdits"
    return [str(c) for c in command]


def _bugs(store: Store) -> dict[str, Record]:
    latest: dict[str, Record] = {}
    for rec in store.all("bug"):
        latest[rec.body["id"]] = rec
    return latest


def _get(store: Store, bug_id: str) -> Record:
    bug = _bugs(store).get(bug_id)
    if bug is None:
        raise UsageError(f"no bug {bug_id}")
    return bug


def _update(store: Store, bug: Record, **changes: Any) -> Record:
    return store.append("bug", {**bug.body, **changes}, now=now_utc(), entity_id=bug.entity_id)


def _record_run(store: Store, bug_id: str, phase: str, attempt: int, run: AgentRun) -> None:
    store.append(
        "agent_run",
        {
            "bug": bug_id,
            "phase": phase,
            "attempt": attempt,
            "exit_code": run.exit_code,
            "cost_usd": run.cost_usd if run.cost_usd is not None else "unknown",
            "duration_ms": run.duration_ms,
            "protection": run.protection,
            "output_blob": store.put_blob(run.output),
        },
        now=now_utc(),
    )


def bug_new(cwd: Path, symptom: str, sandbox: str = "srt") -> tuple[Record, str]:
    """Investigate read-only. Returns the bug record and the proposal text."""
    srt = _srt_for(sandbox)
    root, pdir, store = _open(cwd)
    try:
        bug_id = f"BUG-{len(_bugs(store)) + 1:03d}"
        bug = store.append(
            "bug", {"id": bug_id, "symptom": symptom, "status": "investigating"}, now=now_utc()
        )
        run_dir = pdir / "runs" / uuid.uuid4().hex[:12]
        # The agent may write only here, outside the repository and the store.
        out = Path(tempfile.mkdtemp(prefix="ohx-investigation-"))
        before = build_manifest(root)
        run = launch(
            _agent_command(root, sandbox),
            INVESTIGATE.format(symptom=symptom, out=out),
            cwd=root,
            run_dir=run_dir,
            phase="investigate",
            writable=[out],
            srt=srt,
            ohx_home=ohx_home(),
            extra_env={"OHX_OUT": str(out)},
        )
        _record_run(store, bug_id, "investigate", 1, run)

        if build_manifest(root)["digest"] != before["digest"]:
            return _update(
                store,
                bug,
                status="rejected",
                reason="the agent changed the code during investigation",
            ), ""
        proposal_path, test_path = out / "proposal.md", out / "test_proposed.py"
        if not (proposal_path.is_file() and test_path.is_file()):
            return _update(
                store,
                bug,
                status="rejected",
                reason="the agent did not write proposal.md and test_proposed.py",
            ), ""
        proposal = proposal_path.read_text()

        repro = run_obligation(
            {
                "id": "reproduce",
                "command": [
                    "{python}",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "{protected}",
                ],
            },
            candidate=root,
            protected=test_path,
            run_dir=run_dir,
            srt=srt,
            deny_read=["~/.ssh", str(ohx_home() / "keys")],
            python=_python(root),
        )
        common = {
            "proposal_blob": store.put_blob(proposal.encode()),
            "test_blob": store.put_blob(test_path.read_bytes()),
            "reproduction": repro.outcome,
        }
        if repro.outcome == "fail":
            return _update(store, bug, status="proposed", **common), proposal
        reason = (
            "the proposed tests pass on the current code:"
            " the investigation does not reproduce the bug"
            if repro.outcome == "pass"
            else f"the proposed tests could not be run ({repro.outcome})"
        )
        return _update(store, bug, status="rejected", reason=reason, **common), proposal
    finally:
        store.close()


def _python(root: Path) -> str | None:
    cfg = root / "ohx.toml"
    if cfg.exists():
        python = tomllib.loads(cfg.read_text()).get("python")
        if isinstance(python, str) and python:
            return python if Path(python).is_absolute() else str(root / python)
    return None


def bug_approve(cwd: Path, bug_id: str) -> Path:
    """The owner's decision: the proposed rule and tests become a locked contract."""
    root, _, store = _open(cwd)
    try:
        bug = _get(store, bug_id)
        if bug.body["status"] != "proposed":
            raise UsageError(
                f"{bug_id} is {bug.body['status']}"
                + (f": {bug.body['reason']}" if bug.body.get("reason") else "")
                + "; only a proposal that reproduces the bug can be approved"
            )
        tests = root / "tests"
        tests.mkdir(exist_ok=True)
        test_file = tests / f"test_{bug_id.lower().replace('-', '_')}.py"
        test_file.write_bytes(store.blob_path(bug.body["test_blob"]).read_bytes())
    finally:
        store.close()

    contract = new_contract(
        cwd,
        title=f"{bug_id}: {bug.body['symptom']}",
        summary=f"Fix: {bug.body['symptom']}",
        mode="bugfix",
        acceptance=[test_file],
        accept=True,
    )
    _, _, store = _open(cwd)
    try:
        accepted = store.latest("contract")
        assert accepted is not None
        _update(
            store,
            _get(store, bug_id),
            status="approved",
            contract_revision=accepted.revision_id,
            test_file=str(test_file.relative_to(root)),
        )
    finally:
        store.close()
    return contract


def _feedback(report: dict[str, Any], store: Store) -> str:
    lines = ["", "A previous attempt was checked by OpenHarnX and still fails:"]
    failing = [o for o in report["gate"]["obligations"] if o["status"] != "pass" and o["mandatory"]]
    for ob in failing:
        lines.append(f"- {ob['obligation_id']}: {', '.join(ob['reasons'])}")
        for o in report["observations"]:
            if o["obligation_id"] == ob["obligation_id"]:
                output = store.blob_path(o["output_blob"]).read_text(errors="replace")
                lines += ["  Output (last lines):", *("  " + x for x in output.splitlines()[-30:])]
    return "\n".join(lines)


def bug_fix(
    cwd: Path, bug_id: str, sandbox: str = "srt", attempts: int = 2, budget_usd: float = 2.0
) -> dict[str, Any]:
    """Assign the approved contract to the agent; verify after each attempt."""
    srt = _srt_for(sandbox)
    root, pdir, store = _open(cwd)
    try:
        bug = _get(store, bug_id)
        if bug.body["status"] not in ("approved", "fix_failed"):
            raise UsageError(f"{bug_id} is {bug.body['status']}; approve it first")
        proposal = store.blob_path(bug.body["proposal_blob"]).read_text()
        command = _agent_command(root, sandbox)
    finally:
        store.close()

    feedback = ""
    report: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        _, _, store = _open(cwd)
        try:
            spent = sum(
                r.body["cost_usd"]
                for r in store.all("agent_run")
                if r.body["bug"] == bug_id and isinstance(r.body["cost_usd"], (int, float))
            )
            if spent >= budget_usd:
                break
            run_dir = pdir / "runs" / uuid.uuid4().hex[:12]
            run = launch(
                command,
                FIX.format(
                    symptom=bug.body["symptom"],
                    proposal=proposal,
                    test_path=bug.body["test_file"],
                    feedback=feedback,
                ),
                cwd=root,
                run_dir=run_dir,
                phase="fix",
                writable=[root],
                srt=srt,
                ohx_home=ohx_home(),
                extra_env={},
            )
            _record_run(store, bug_id, "fix", attempt, run)
        finally:
            store.close()

        record, _ = verify(cwd, sandbox="srt" if srt else "none")
        report = dict(record.body)
        if report["readiness"] == "ready":
            break
        _, _, store = _open(cwd)
        try:
            feedback = _feedback(report, store)
        finally:
            store.close()

    _, _, store = _open(cwd)
    try:
        status = "fixed" if report.get("readiness") == "ready" else "fix_failed"
        _update(store, _get(store, bug_id), status=status)
    finally:
        store.close()
    return report
