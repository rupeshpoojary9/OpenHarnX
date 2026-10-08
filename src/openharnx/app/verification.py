"""`ohx verify`: run every obligation, evaluate the gate, write the report."""

from __future__ import annotations

import fcntl
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from openharnx.app.approval import describe as describe_approval
from openharnx.app.checks import (
    LISTED_EDITED,
    MUTATION,
    MUTATION_BUDGET_S,
    NO_NEW_FAILURES,
    WEAKENING,
    _checker_srt,
    _deny_read,
)
from openharnx.app.core import UsageError, _cause, _files, _gate_to_dict, _open, now_utc
from openharnx.app.environments import (
    _checker_environment,
    _checker_python,
    _EnvironmentChanged,
    _interpreter_limitations,
    _interpreter_problem,
    _node_modules_limitations,
    _protected_modules,
)
from openharnx.app.trees import (
    _copy_tree,
    _link_node_modules,
    _modules_view,
    _tree_view,
    _TreeChanged,
)
from openharnx.environment import (
    EnvironmentUnavailable,
)
from openharnx.kernel.gate import GateEvaluation, Obligation, Observation, evaluate_gate
from openharnx.mutation import PROBE_ENV, Mutant, changed_lines
from openharnx.mutation import select as select_mutants
from openharnx.regression import compare as compare_regression
from openharnx.regression import (
    edited_tests,
    junit_env,
    newly_passing,
    order_env,
    order_problems,
    read_go_results,
    read_results,
)
from openharnx.report import NO_REGRESSIONS, READINESS, render_markdown
from openharnx.store import Record, Store
from openharnx.verify import run_obligation
from openharnx.verify.where import foreign_code, loaded_modules, project_files, where_env
from openharnx.weakening import active_checkers, is_test_file
from openharnx.weakening import compare as compare_weakening
from openharnx.weakening import snapshot as weakening_snapshot
from openharnx.workspace import (
    build_manifest,
    changed_paths,
    tree_digest,
)


def _agent_cost(store: Store, contract_revision: str) -> str:
    bugs: dict[str, dict[str, Any]] = {}
    for rec in store.all("bug"):
        bugs[rec.body["id"]] = rec.body
    ids = {b["id"] for b in bugs.values() if b.get("contract_revision") == contract_revision}
    runs = [r.body for r in store.all("agent_run") if r.body["bug"] in ids]
    if not runs:
        return "unknown: no agent run recorded"
    known = [r["cost_usd"] for r in runs if isinstance(r["cost_usd"], (int, float))]
    text = f"${sum(known):.2f} reported across {len(known)} agent run(s)"
    if len(known) < len(runs):
        text += f", plus {len(runs) - len(known)} run(s) with unknown cost"
    return text


def _agent_work(store: Store, contract_revision: str, agent: dict[str, str] | None) -> str:
    """Agent cost as recorded; a hook's session is named even though its cost is unknown."""
    work = _agent_cost(store, contract_revision)
    if agent is None or not work.startswith("unknown"):
        return work
    if agent.get("tool") == "opencode":
        return (
            f"unknown: OpenCode session {agent['session']} ran the agent, and OpenCode does"
            " not give its cost to plugins"
        )
    return (
        f"unknown: Claude Code session {agent['session']} ran the agent, and Claude Code does"
        " not give its cost to hooks; `claude -p --output-format json` reports it as"
        " total_cost_usd"
    )


def verify(
    cwd: Path, sandbox: str = "auto", agent: dict[str, str] | None = None
) -> tuple[Record, Path]:
    """Capture the candidate, run every obligation, evaluate the gate, write the report.

    `agent` names the agent session that asked for the verification (the Stop hook, T98)."""
    root, pdir, store = _open(cwd)
    try:
        contract = store.latest("contract")
        if contract is None:
            raise UsageError("no accepted contract; run `ohx contract accept <file>`")

        srt = _checker_srt(sandbox)
        protection = (
            "enforced: checkers ran in the srt sandbox"
            if srt
            else "none: checkers ran without isolation, so tampering is detected, not prevented"
        )

        now = now_utc()
        before = build_manifest(root)
        candidate = store.append(
            "candidate", before, now=now, idempotency_key=f"candidate:{before['digest']}"
        )
        run_id = uuid.uuid4().hex[:12]
        run_dir = pdir / "runs" / run_id
        deny_read = _deny_read()
        environment = contract.body.get("environment")
        python, env_outcome, env_note = _checker_python(
            contract.body.get("python", "unknown"), environment, pdir, root
        )
        modules, npm_outcome, npm_note = _protected_modules(environment, pdir, root)
        if npm_note:
            env_outcome, env_note = npm_outcome, npm_note
        recorded = contract.body.get("interpreter")
        interpreter_problem = (
            _interpreter_problem(store, recorded, python) if recorded and not environment else ""
        )
        baselines: dict[str, Any] = contract.body.get("regression_baseline", {})
        approval: dict[str, str] | None = contract.body.get("approval")
        regression_runs: dict[str, tuple[str, dict[str, str] | None]] = {}
        order_runs: dict[str, list[str]] = {}
        wrong_code: dict[str, str] = {}  # obligation id: why it ran other code (T90c)
        project_modules = project_files(_files(before))
        acceptance_tests: dict[str, dict[str, str] | None] = {}  # per-test results (T96)
        imported: dict[str, list[str]] = {}  # changed-or-not project files each run loaded

        observations: list[Observation] = []
        raw_obs: list[dict[str, Any]] = []
        not_started = 0
        for ob in contract.body["obligations"]:
            protected = None
            note = ""
            ob_protection = protection
            if interpreter_problem:  # nothing runs with an interpreter changed since acceptance
                raw_obs.append(
                    {
                        "obligation_id": ob["id"],
                        "subject_digest": before["digest"],
                        "contract_revision": contract.revision_id,
                        "outcome": "invalid",
                        "note": interpreter_problem,
                        "exit_code": None,
                        "duration_ms": 0,
                        "argv": ob["command"],
                        "output_blob": store.put_blob(interpreter_problem.encode()),
                        "producer": "openharnx.verify",
                        "protection": ob_protection,
                    }
                )
                continue
            if "protected_store_path" in ob:
                protected = pdir / ob["protected_store_path"]
                if tree_digest(protected) != ob["protected_digest"]:
                    note = "protected material changed since contract acceptance"
            if ob.get("builtin") == WEAKENING:
                start = time.monotonic()
                current = weakening_snapshot(root, _files(before))
                active = active_checkers(contract.body["obligations"], root)
                baseline = contract.body["weakening_baseline"]
                findings = compare_weakening(baseline, current, active)
                outcome = "fail" if findings else "pass"
                note = "; ".join(findings)
                ignored = [f for f in compare_weakening(baseline, current) if f not in findings]
                if ignored:
                    note = "; ".join(
                        [
                            *([note] if note else []),
                            "not counted, since this contract runs no checker that reads"
                            f" them ({', '.join(sorted(active or ()))}): {'; '.join(ignored)}",
                        ]
                    )
                if findings and approval:
                    outcome, note = "pass", f"{_approved(approval)}: {note}"
                out = "\n".join(findings).encode()
                ms = int((time.monotonic() - start) * 1000)
                exit_code, argv = None, ob["command"]
            elif ob.get("builtin") == NO_NEW_FAILURES:
                ran = regression_runs.get(ob["of"])
                if ob["of"] in wrong_code:
                    outcome = "invalid"
                    note = f"the {ob['of']!r} suite cannot be compared: {wrong_code[ob['of']]}"
                elif ran is None:
                    outcome, note = "unavailable", f"the {ob['of']!r} suite did not run"
                else:
                    outcome, note = compare_regression(
                        baselines[ob["of"]], *ran, removed_ok=approval is not None
                    )
                    if approval and "approved" in note:
                        note = f"{_approved(approval)}: {note}"
                    if outcome == "pass":
                        outcome, note = _edited_failing(contract.body, ob["of"], pdir, root, note)
                    if outcome == "pass" and order_runs.get(ob["of"]):
                        outcome, note = (
                            "fail",
                            (
                                f"{'; '.join(order_runs[ob['of']][:LISTED_EDITED])}. A test that"
                                " passes only after other tests ran suggests the code keeps state"
                                " between calls (a counter or a toggle) instead of fixing the"
                                " behaviour"
                            ),
                        )
                out, ms, exit_code, argv = note.encode(), 0, None, ob["command"]
            elif env_note:
                outcome, exit_code, out, ms, argv = env_outcome, None, b"", 0, ob["command"]
                note = env_note
            elif ob.get("builtin") == MUTATION:
                outcome, note, out, ms = _mutation_check(
                    contract.body, raw_obs, before, root, pdir, run_dir, srt, python, imported
                )
                exit_code, argv = None, ob["command"]
            elif note:
                outcome, exit_code, out, ms, argv = "invalid", None, b"", 0, ob["command"]
            else:
                junit = run_dir / "tmp" / f"junit-{ob['id']}.xml"
                where = root
                if protected is not None and ob.get("protected_at"):
                    at = ob["protected_at"]
                    try:
                        where = _tree_view(
                            before, root, protected, at, run_dir / f"tree-{ob['id']}", modules
                        )
                    except _TreeChanged as exc:
                        where, note = root, str(exc)
                    protected = where / at
                elif modules is not None:  # every check sees the protected node_modules
                    try:
                        where = _modules_view(before, root, modules, run_dir / "tree")
                    except _TreeChanged as exc:
                        where, note = root, str(exc)
                if note:
                    outcome, exit_code, out, ms, argv = "invalid", None, b"", 0, ob["command"]
                    raw_obs.append(
                        {
                            "obligation_id": ob["id"],
                            "subject_digest": before["digest"],
                            "contract_revision": contract.revision_id,
                            "outcome": outcome,
                            "note": note,
                            "exit_code": exit_code,
                            "duration_ms": ms,
                            "argv": argv,
                            "output_blob": store.put_blob(out),
                            "producer": "openharnx.verify",
                            "protection": ob_protection,
                        }
                    )
                    continue
                per_test = ob["id"] in baselines or ob.get("kind") == "acceptance"
                extra = junit_env(junit) if per_test else None
                where_dir = None
                if project_modules and any("pytest" in str(a) for a in ob["command"]):
                    where_dir = run_dir / "tmp" / f"where-{ob['id']}"
                    extra = _with_where(ob, extra, where_dir, project_modules)
                r = run_obligation(
                    ob,
                    candidate=where,
                    protected=protected,
                    run_dir=run_dir,
                    srt=srt,
                    deny_read=deny_read,
                    python=python,
                    extra_env=extra,
                )
                foreign = foreign_code(where_dir, project_modules, root, where) if where_dir else []
                if where_dir and any(where_dir.glob("where-*.json")):
                    imported[ob["id"]] = sorted(
                        {
                            project_modules[n]
                            for n in loaded_modules(where_dir)
                            if n in project_modules
                        }
                    )
                if ob.get("kind") == "acceptance":
                    acceptance_tests[ob["id"]] = read_results(junit, where) or read_go_results(
                        r.output
                    )
                if foreign:
                    wrong_code[ob["id"]] = (
                        f"the check ran other code than the candidate's: "
                        f"{'; '.join(foreign[:LISTED_EDITED])}. The checker environment holds"
                        " another copy of the project (an editable or stale install); build it"
                        " without the project, or from this candidate"
                    )
                if ob["id"] in baselines and not foreign:
                    regression_runs[ob["id"]] = (
                        r.outcome,
                        read_results(junit, where) or read_go_results(r.output),
                    )
                    order_runs[ob["id"]] = _order_check(
                        ob,
                        baselines[ob["id"]],
                        regression_runs[ob["id"]][1],
                        where,
                        protected,
                        run_dir,
                        srt,
                        deny_read,
                        python,
                    )
                outcome, exit_code, out, ms, argv = (
                    r.outcome,
                    r.exit_code,
                    r.output,
                    r.duration_ms,
                    r.argv,
                )
                if r.sandbox_started is False:
                    not_started += 1
                    note = "the srt sandbox did not start the checker"
                    ob_protection = "not enforced: the srt sandbox did not start this checker"
                if foreign:
                    outcome, note = "invalid", wrong_code[ob["id"]]
                elif outcome in ("crash", "timeout") and not note:
                    note = _cause(r.output)
            raw_obs.append(
                {
                    "obligation_id": ob["id"],
                    "subject_digest": before["digest"],
                    "contract_revision": contract.revision_id,
                    "outcome": outcome,
                    "note": note,
                    "exit_code": exit_code,
                    "duration_ms": ms,
                    "argv": argv,
                    "output_blob": store.put_blob(out),
                    "producer": "openharnx.verify",
                    "protection": ob_protection,
                }
            )
        if not_started:
            protection = (
                f"not enforced: the srt sandbox did not start {not_started} of"
                f" {len(raw_obs)} checker(s)"
            )

        after = build_manifest(root)
        mutated = after["digest"] != before["digest"]
        evidence: dict[str, dict[str, str]] = {}
        for o in raw_obs:
            if mutated:
                o["outcome"], o["note"] = "invalid", "candidate changed during verification"
            seen = store.append("observation", o, now=now_utc())
            evidence[o["obligation_id"]] = _evidence_file(
                store, o["obligation_id"], o["output_blob"], seen.revision_id, run_dir
            )
            observations.append(
                Observation(o["obligation_id"], o["subject_digest"], o["outcome"], o["note"])
            )

        obligations = [Obligation(ob["id"], ob["mandatory"]) for ob in contract.body["obligations"]]
        gate = evaluate_gate(obligations, observations, before["digest"])
        gate_rec = store.append("gate_evaluation", _gate_to_dict(gate), now=now_utc())

        readiness, claims = _claims(
            contract.body, gate, baselines, regression_runs, READINESS[gate.result]
        )
        report: dict[str, Any] = {
            "readiness": readiness,
            "claims": claims,
            "contract": {
                "revision_id": contract.revision_id,
                "title": contract.body["title"],
                "governance_level": contract.body["governance_level"],
                "policy_version": contract.body["policy_version"],
                "mode": contract.body["mode"],
                "summary": contract.body["change_summary"],
                "accepted_by": contract.body.get("accepted_by"),
            },
            "candidate": {
                "revision_id": candidate.revision_id,
                "digest": before["digest"],
                "base_commit": before["base_commit"],
                "ignored_present": before["ignored_present"],
                "changed_during_verification": mutated,
                "changed_paths": changed_paths(before, after) if mutated else [],
            },
            "gate": {**_gate_to_dict(gate), "revision_id": gate_rec.revision_id},
            "observations": raw_obs,
            "evidence": evidence,
            **({"agent": agent} if agent else {}),
            # Which suite each no-new-failures comparison covers: its id is plain
            # `no-new-failures` when there is one suite, so readers must not parse it.
            "compares": {
                ob["id"]: ob["of"]
                for ob in contract.body["obligations"]
                if ob.get("builtin") == NO_NEW_FAILURES
            },
            "obligation_kinds": {
                ob["id"]: "builtin" if ob.get("builtin") else ob.get("kind", "check")
                for ob in contract.body["obligations"]
            },
            "changes": _changes(store, contract.body, before),
            "acceptance_tests": acceptance_tests,
            "imported": imported,
            "protection": {"verifier": protection, "agent": "unknown: no agent run recorded"},
            "cost": {
                "agent_work": _agent_work(store, contract.revision_id, agent),
                "overhead": {
                    "model_calls": 0,
                    "verifier_ms": sum(o["duration_ms"] for o in raw_obs),
                },
            },
            "changelog_entry": f"- {contract.body['change_summary']}",
            "limitations": [
                *(
                    [
                        f"{before['ignored_present']} ignored file(s) present and not in the"
                        " candidate identity"
                    ]
                    if before["ignored_present"]
                    else []
                ),
                *_interpreter_limitations(environment, python, root, recorded),
                *_node_modules_limitations(contract.body, root),
                *_regression_limitations(contract.body),
                *_unlocked_limitations(contract.body),
            ],
            "authorizes": "It is evidence of readiness, not permission to merge, deploy or"
            " publish.",
        }
        rec = store.append("assurance_report", report, now=now_utc())
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "report.json").write_text(json.dumps(report, indent=2))
        (run_dir / "report.md").write_text(render_markdown(report))
        return rec, run_dir
    finally:
        store.close()


def _evidence_file(
    store: Store, obligation_id: str, blob: str, record: str, run_dir: Path
) -> dict[str, str]:
    """A readable copy of a check's recorded output next to the report, which the review
    brief links to (T96); the blob digest and observation record say which it is."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", obligation_id)
    rel = f"evidence/{name}.txt"
    target = run_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.blob_path(blob), target)
    return {"file": rel, "output": blob, "record": record}


# What a changed file is, for the reviewer (T96). Dependencies and the files that decide
# what the checks do are put to the reviewer as decisions.
DEPENDENCY_FILES = frozenset(
    {"uv.lock", "poetry.lock", "pipfile", "pipfile.lock", "package.json", "package-lock.json",
     "pnpm-lock.yaml", "yarn.lock", "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile",
     "gemfile.lock"}
)  # fmt: skip


CONFIGURATION_FILES = frozenset(
    {"ohx.toml", "pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini",
     "conftest.py", "noxfile.py", "mypy.ini", "ruff.toml", ".ruff.toml", "makefile",
     ".pre-commit-config.yaml", "action.yml", ".importlinter", ".coveragerc"}
)  # fmt: skip


CONFIGURATION_PREFIXES = (".github/", ".gitlab-ci", "contracts/", ".circleci/", "jenkinsfile")


CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
                 ".kt", ".rb", ".c", ".h", ".cc", ".cpp", ".cs", ".swift", ".sh")  # fmt: skip


CONFIG_NAME = re.compile(
    r"^(jest|vitest|vite|webpack|babel|eslint|prettier|tsconfig|karma|playwright)[.\w-]*$"
    r"|^\.(eslintrc|prettierrc|babelrc)"
)


def change_kind(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    lowered = path.lower()
    if name in DEPENDENCY_FILES or re.match(r"requirements.*\.(txt|in)$", name):
        return "dependencies"
    if (
        name in CONFIGURATION_FILES
        or lowered.startswith(CONFIGURATION_PREFIXES)
        or CONFIG_NAME.match(name)
    ):
        return "configuration"
    if is_test_file(path) or any(
        part in ("tests", "test", "__tests__", "spec") for part in path.split("/")[:-1]
    ):
        return "test"
    if name.endswith(CODE_SUFFIXES):
        return "code"
    if name.endswith((".md", ".rst", ".txt", ".adoc")):
        return "docs"
    return "other"


def _changes(store: Store, body: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Files that differ from the files accepted with the contract: the task's change, as
    observed by content digest (T96). In CI the accepted files are the base commit's."""
    blob = body.get("accepted_manifest_blob")
    try:
        accepted = json.loads(store.blob_path(blob).read_bytes()) if blob else None
    except (OSError, ValueError):
        accepted = None
    if accepted is None:
        return {"known": False, "files": []}
    then = {e["path"]: e for e in accepted["entries"]}
    now = {e["path"]: e for e in manifest["entries"]}
    files = []
    for path in changed_paths(accepted, manifest):
        if path not in then or then[path].get("type") == "deleted":
            change = "added"
        elif path not in now or now[path].get("type") == "deleted":
            change = "deleted"
        else:
            change = "modified"
        files.append({"path": path, "change": change, "kind": change_kind(path)})
    return {"known": True, "base_commit": accepted.get("base_commit", "unknown"), "files": files}


def _with_where(
    ob: dict[str, Any], extra: dict[str, str] | None, folder: Path, modules: dict[str, str]
) -> dict[str, str]:
    """Add the plugin that records where the project's modules ran from (T90c), keeping
    the obligation's own PYTEST_ADDOPTS and PYTHONPATH."""
    env = ob.get("env", {})
    where = where_env(folder, sorted(modules), env.get("PYTHONPATH", ""))
    theirs = (extra or {}).get("PYTEST_ADDOPTS") or env.get("PYTEST_ADDOPTS", "")
    addopts = f"{where['PYTEST_ADDOPTS']} {theirs}".strip()
    return {**(extra or {}), **where, "PYTEST_ADDOPTS": addopts}


def _claims(
    body: dict[str, Any],
    gate: GateEvaluation,
    baselines: dict[str, Any],
    runs: dict[str, tuple[str, dict[str, str] | None]],
    readiness: str,
) -> tuple[str, dict[str, Any]]:
    """What the evidence supports (T91): READY needs a mandatory acceptance check;
    without one, every mandatory check passing is NO REGRESSIONS."""
    status = {o["obligation_id"]: o["status"] for o in _gate_to_dict(gate)["obligations"]}
    mandatory = [ob for ob in body["obligations"] if ob["mandatory"]]
    accepted = [status.get(ob["id"]) for ob in mandatory if ob.get("kind") == "acceptance"]
    # Only checks that run tests that passed before can support the claim (T93): the
    # weakening check passing says nothing about whether those tests still pass.
    checks = [
        status.get(ob["id"])
        for ob in mandatory
        if ob.get("kind") == "regression" or ob.get("builtin") == NO_NEW_FAILURES
    ]
    no_regressions = (
        None
        if not checks
        else False
        if "fail" in checks
        else True
        if all(s == "pass" for s in checks)
        else None
    )
    if not accepted:
        acceptance = "none defined"
    else:
        acceptance = "met" if all(s == "pass" for s in accepted) else "not met"
    still: set[str] = set()
    counted: dict[str, int] | None = None
    for suite, (_, tests) in runs.items():
        before = (baselines.get(suite) or {}).get("tests") or {}
        now = tests or {}
        still |= {t for t, o in now.items() if o == "fail" and before.get(t) == "fail"}
        # Which tests checked the change (T90d): only one that passes after it does.
        # Counted per suite: the locked copy and the change's own copy run the same
        # tests, sometimes under different ids, so they are never added up.
        both = {o: sum(1 for t, s in now.items() if s == o and before.get(t) == o)
                for o in ("fail", "skip")}  # fmt: skip
        suite_counts = {
            "ran": len(now),
            "checked": sum(1 for s in now.values() if s == "pass"),
            "failed_both_times": both["fail"],
            "skipped_both_times": both["skip"],
        }
        if now and (counted is None or suite_counts["ran"] > counted["ran"]):
            counted = suite_counts
    if readiness == "ready" and not accepted:
        readiness = NO_REGRESSIONS
    claims = {
        "no_regressions": no_regressions,
        "regression_checks": len(checks),
        "acceptance": acceptance,
        "still_failing": sorted(still),
        "tests": counted,
    }
    return readiness, claims


def _approved(approval: dict[str, str]) -> str:
    return describe_approval(approval)


def _order_check(
    ob: dict[str, Any],
    base: dict[str, Any],
    tests: dict[str, str] | None,
    where: Path,
    protected: Path | None,
    run_dir: Path,
    srt: Path | None,
    deny_read: list[str],
    python: str,
) -> list[str]:
    """Tests that newly pass must also pass on their own and in reverse order, so that two
    contradicting tests cannot both pass through state kept between calls (impossible-tasks
    replay, 2026-10-04). Pytest suites only; one extra run, only when a test newly passes."""
    newly = newly_passing(base, tests)
    if not newly or not any("pytest" in str(a) for a in ob["command"]):
        return []
    junit = run_dir / "tmp" / f"junit-order-{ob['id']}.xml"
    env = order_env(
        run_dir / "tmp" / f"order-{ob['id']}", newly, junit, ob.get("env", {}).get("PYTHONPATH", "")
    )
    r = run_obligation(
        ob,
        candidate=where,
        protected=protected,
        run_dir=run_dir,
        srt=srt,
        deny_read=deny_read,
        python=python,
        extra_env=env,
    )
    return order_problems(newly, read_results(junit, where), r.outcome)


def _edited_failing(
    body: dict[str, Any], of: str, pdir: Path, root: Path, note: str
) -> tuple[str, str]:
    """A locked suite's tests that were failing when locked must not be edited or removed:
    the locked copy still fails "as before", so no regression shows (replay, 2026-10-04)."""
    suite = next((o for o in body["obligations"] if o["id"] == of), None)
    if suite is None or "protected_store_path" not in suite or not suite.get("protected_at"):
        return "pass", note
    before = (body.get("regression_baseline", {}).get(of) or {}).get("tests") or {}
    failing = [t for t, o in before.items() if o == "fail"]
    found = edited_tests(
        pdir / suite["protected_store_path"], root / suite["protected_at"], failing
    )
    if not found:
        return "pass", note
    shown = "; ".join(found[:LISTED_EDITED])
    return "fail", (
        f"{shown}. Fix the code so the locked test passes; if the test itself was wrong,"
        " lock the tests again (ohx init --lock-tests) or accept a contract revision"
    )


def _mutation_check(
    body: dict[str, Any],
    raw_obs: list[dict[str, Any]],
    manifest: dict[str, Any],
    root: Path,
    pdir: Path,
    run_dir: Path,
    srt: Path | None,
    python: str,
    imported: dict[str, list[str]] | None = None,
) -> tuple[str, str, bytes, int]:
    """Run the acceptance tests against mutants of the change's own lines (T87 item 5).

    Mutants run one at a time in a copy of the tree at a fixed place in the store, so a
    protected checker environment can be built once for that copy and import from it.
    Only changed files the acceptance tests imported are mutated, when every acceptance
    run recorded its imports, and no mutant starts past the time budget (T97)."""
    start = time.monotonic()

    def done(outcome: str, note: str, out: bytes = b"") -> tuple[str, str, bytes, int]:
        return outcome, note, out, int((time.monotonic() - start) * 1000)

    acceptance = [ob for ob in body["obligations"] if ob.get("kind") == "acceptance"]
    outcomes = {o["obligation_id"]: o["outcome"] for o in raw_obs}
    if not acceptance or any(outcomes.get(ob["id"]) != "pass" for ob in acceptance):
        return done("unavailable", "acceptance tests did not pass, so mutants were not run")
    base = manifest.get("base_commit")
    if not base:
        return done("unavailable", "no base commit to compare the change with")
    try:
        changed = changed_lines(root, base, _files(manifest))
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return done("unavailable", f"the changed lines are unknown: {exc}")
    skipped: list[str] = []
    if imported is not None and all(ob["id"] in imported for ob in acceptance):
        reached = {p for ob in acceptance for p in imported[ob["id"]]}
        skipped = sorted(p for p in changed if p.endswith(".py") and p not in reached)
        changed = {p: lines for p, lines in changed.items() if p not in skipped}
    unreached = (
        f"changed files no acceptance test imported were not mutated: {', '.join(skipped)}"
        if skipped
        else ""
    )
    try:
        chosen = select_mutants(root, changed)
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return done("unavailable", f"the changed lines are unknown: {exc}")
    if not chosen:
        return done("unavailable", unreached or "no changed source lines to mutate (Python only)")
    budget = float(body.get("mutation_budget_s", MUTATION_BUDGET_S))
    accepted_ids = {ob["id"] for ob in acceptance}
    one_run = sum(o["duration_ms"] for o in raw_obs if o["obligation_id"] in accepted_ids) / 1000
    over = (
        f"the time budget of {budget:g} s would run out (the acceptance tests take"
        f" {one_run:.0f} s a run); raise mutation_budget_s in ohx.toml to run more"
    )

    work = pdir / "mutation"
    work.mkdir(parents=True, exist_ok=True)
    with open(work / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one copy per project; verifications take turns
        tree = work / "tree"
        shutil.rmtree(tree, ignore_errors=True)
        try:
            _copy_tree(manifest, root, tree)
        except _TreeChanged as exc:
            return done("invalid", str(exc))
        _link_node_modules(root / "node_modules", tree)
        for ob in acceptance:  # locked tests that run at their own path
            if ob.get("protected_at") and "protected_store_path" in ob:
                (tree / ob["protected_at"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pdir / ob["protected_store_path"], tree / ob["protected_at"])
        environment = body.get("environment")
        if environment:
            try:
                python = str(_checker_environment(environment, pdir, tree))
            except (_EnvironmentChanged, EnvironmentUnavailable) as exc:
                return done("unavailable", f"no checker environment for the copy: {exc}")
        results: list[tuple[Mutant, str]] = []
        for k, mutant in enumerate(chosen):
            if time.monotonic() - start + one_run > budget:
                results += [(m, "over budget") for m in chosen[k:]]
                break
            target = tree / mutant.path
            original = target.read_bytes()
            target.write_text(mutant.source, encoding="utf-8")
            try:
                status = _run_mutant(
                    acceptance, tree, pdir, run_dir / "mutants" / str(k), srt, python
                )
            finally:
                target.write_bytes(original)
            results.append((mutant, status))

    def named(status: str) -> list[str]:
        return [f"{m.path}:{m.line} `{m.before}` -> `{m.after}`" for m, s in results if s == status]

    killed, survived = named("killed"), named("survived")
    exercised = len(killed) + len(survived)
    extra = [f"{n} {label}" for label in ("not exercised", "not run") if (n := len(named(label)))]
    if late := len(named("over budget")):
        extra.append(f"{late} not run: {over}")
    if unreached:
        extra.append(unreached)
    ran = [(m, s) for m, s in results if s != "over budget"]
    out = "\n".join(f"{s}: {m.path}:{m.line} `{m.before}` -> `{m.after}`" for m, s in ran)
    tail = f"; {'; '.join(extra)}" if extra else ""
    if survived:
        note = (
            f"{len(survived)} of {exercised} mutants of changed lines survived: "
            + "; ".join(survived)
            + tail
        )
        return done("fail", note, out.encode())
    if killed:
        return done(
            "pass",
            f"{len(killed)} of {exercised} mutants of changed lines killed{tail}",
            out.encode(),
        )
    if not ran:
        return done(
            "unavailable", f"no mutant ran: {over}" + (f"; {unreached}" if unreached else "")
        )
    return done(
        "unavailable",
        "no mutant was exercised: the acceptance tests did not import the changed files"
        f" from the copy{tail}",
        out.encode(),
    )


def _run_mutant(
    acceptance: list[dict[str, Any]],
    tree: Path,
    pdir: Path,
    mdir: Path,
    srt: Path | None,
    python: str,
) -> str:
    """killed, survived, not exercised (the mutated file was never imported) or not run."""
    probe = mdir / "tmp" / "imported"
    for ob in acceptance:
        protected = pdir / ob["protected_store_path"] if "protected_store_path" in ob else None
        if protected is not None and ob.get("protected_at"):
            protected = tree / ob["protected_at"]
        r = run_obligation(
            ob,
            candidate=tree,
            protected=protected,
            run_dir=mdir,
            srt=srt,
            deny_read=_deny_read(),
            python=python,
            extra_env={PROBE_ENV: str(probe)},
        )
        if r.outcome == "unavailable" or r.sandbox_started is False:
            return "not run"
        if r.outcome != "pass":
            return "killed"
    return "survived" if probe.exists() else "not exercised"


def _unlocked_limitations(body: dict[str, Any]) -> list[str]:
    """Name suites that run from the working tree with no locked copy (T95)."""
    suites = [o for o in body["obligations"] if o.get("kind") == "regression"]
    others = [o for o in suites if not any("pytest" in str(a) for a in o.get("command", []))]
    if not others or any("protected_store_path" in o for o in others):
        return []
    return [
        "The TypeScript, JavaScript or Go tests ran from the working tree and are not locked"
        " in this contract, so an edited test is not caught; `ohx init --lock-tests` or"
        " `ohx gate` locks them"
    ]


def _regression_limitations(body: dict[str, Any]) -> list[str]:
    baselines = body.get("regression_baseline", {})
    unchecked = [
        o["id"]
        for o in body["obligations"]
        if o.get("kind") == "regression" and not o["mandatory"] and o["id"] not in baselines
    ]
    if not unchecked:
        return []
    return [
        f"Advisory regression suite(s) {', '.join(unchecked)} not compared with a baseline:"
        " this contract was accepted before baselines existed"
    ]
