"""Use cases shared by every interface: init, contract acceptance, verification."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import tomllib
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openharnx.environment import LOCKFILE, EnvironmentUnavailable, ensure
from openharnx.kernel.canonical import digest
from openharnx.kernel.contract import validate_contract
from openharnx.kernel.gate import GateEvaluation, Obligation, Observation, evaluate_gate
from openharnx.regression import baseline as regression_baseline
from openharnx.regression import compare as compare_regression
from openharnx.regression import junit_env, read_results
from openharnx.report import READINESS, render_markdown
from openharnx.sandbox import find_srt
from openharnx.signing import (
    KEY_ENV,
    SigningError,
    find_key,
    fingerprint,
    public_key,
    sign,
    signer_of,
)
from openharnx.signing import message as signed_message
from openharnx.store import Record, Store
from openharnx.verify import run_obligation
from openharnx.weakening import compare as compare_weakening
from openharnx.weakening import snapshot as weakening_snapshot
from openharnx.workspace import (
    NotARepository,
    build_manifest,
    changed_paths,
    git_user,
    repo_root,
    root_commit,
    tree_digest,
)

HOME_ENV = "OHX_HOME"


class UsageError(Exception):
    """Bad input or state the user can fix; maps to exit code 2."""


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ohx_home() -> Path:
    return Path(os.environ.get(HOME_ENV, "~/.openharnx")).expanduser()


def _project_dir(root: Path) -> Path:
    return ohx_home() / "projects" / digest(str(root)).removeprefix("sha256:")[:16]


def _open(cwd: Path) -> tuple[Path, Path, Store]:
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    pdir = _project_dir(root)
    if not (pdir / "store.sqlite").exists():
        raise UsageError("no OpenHarnX project here; run `ohx init` first")
    store = Store(pdir)
    project = store.latest("project")
    if project is None or project.body["repository_path"] != str(root):
        store.close()
        raise UsageError("project store does not match this repository")
    return root, pdir, store


def init_project(cwd: Path) -> tuple[Path, Record]:
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    pdir = _project_dir(root)
    store = Store(pdir)
    try:
        record = store.append(
            "project",
            {"repository_path": str(root), "root_commit": root_commit(root), "store_version": 1},
            now=now_utc(),
            idempotency_key=f"project:{root}",
        )
    finally:
        store.close()
    return pdir, record


def accept_contract(
    cwd: Path, contract_file: Path, sandbox: str = "auto", baseline_root: Path | None = None
) -> Record:
    """Lock a contract. Baselines (weakening, regression, environment, tree) come from
    `baseline_root` when given, the trusted base of a pull request in CI, else from the
    repository as it is now."""
    try:
        raw = tomllib.loads(contract_file.read_text(encoding="utf-8"))  # TOML is UTF-8
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise UsageError(f"cannot read contract: {exc}") from exc
    errors = validate_contract(raw)
    if errors:
        raise UsageError("contract is not valid:\n  " + "\n  ".join(errors))

    root, pdir, store = _open(cwd)
    try:
        obligations = []
        written: list[Path] = [contract_file.resolve()]  # the acceptance step's own files
        for ob in raw["obligations"]:
            ob = dict(ob)
            ob.setdefault("timeout_s", 300)
            ob.setdefault("env", {})
            if "protected" in ob:
                src = (contract_file.parent / ob["protected"]).resolve()
                if not src.exists():
                    raise UsageError(f"protected material not found: {src}")
                written.append(src)
                tdig = tree_digest(src)
                dest = pdir / "protected" / tdig.removeprefix("sha256:")[:16] / src.name
                if not dest.exists():
                    if src.is_file():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                    else:
                        ignore = shutil.ignore_patterns("__pycache__")
                        shutil.copytree(src, dest, ignore=ignore)
                ob["protected_digest"] = tdig
                ob["protected_store_path"] = str(dest.relative_to(pdir))
                del ob["protected"]
            obligations.append(ob)
        root = repo_root(cwd)
        base = baseline_root or root
        if any(ob.get("builtin") or _reserved(ob["id"]) for ob in obligations):
            raise UsageError(
                f"obligation ids {WEAKENING!r} and {NO_NEW_FAILURES!r}..., and `builtin`,"
                " are reserved"
            )
        obligations.append(dict(WEAKENING_OBLIGATION))
        environment = _lock_environment(raw, pdir, base)
        baselines = _regression_baselines(obligations, raw, environment, pdir, base, sandbox, root)
        accepted_tree = build_manifest(base)
        body = {
            "title": raw["title"],
            "python": raw.get("python", "unknown"),
            "mode": raw["mode"],
            "change_summary": raw["change_summary"],
            "governance_level": "lite",
            "policy_version": "lite-1",
            "documentation_obligations": ["assurance_report", "changelog_entry"],
            "obligations": obligations,
            **({"environment": environment} if environment else {}),
            "weakening_baseline": weakening_snapshot(base, _files(accepted_tree)),
            "accepted_by": git_user(root),
            "accepted_paths": sorted(
                str(p.relative_to(root)) for p in written if p.is_relative_to(root)
            ),
            "accepted_manifest_blob": store.put_blob(
                json.dumps(accepted_tree, sort_keys=True).encode()
            ),
            **({"regression_baseline": baselines} if baselines else {}),
            "status": "accepted",
        }
        previous = store.latest("contract")
        return store.append(
            "contract",
            body,
            now=now_utc(),
            entity_id=previous.entity_id if previous else None,
        )
    finally:
        store.close()


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # A JSON string is a TOML basic string once characters are kept literal: JSON's
        # surrogate-pair escapes for emoji are invalid TOML (UX-10), and DEL must be escaped.
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007F")
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"unsupported TOML value: {value!r}")


def _slug(title: str) -> str:
    words = "".join(c.lower() if c.isalnum() else " " for c in title).split()
    return "-".join(words)[:48] or "contract"


def new_contract(
    cwd: Path,
    *,
    title: str,
    summary: str,
    mode: str,
    acceptance: list[Path],
    accept: bool = False,
    sandbox: str = "auto",
) -> Path:
    """Write a numbered contract from project defaults; optionally accept it."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    defaults: dict[str, Any] = {}
    if (root / "ohx.toml").exists():
        try:
            defaults = tomllib.loads((root / "ohx.toml").read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise UsageError(f"ohx.toml is not valid TOML: {exc}") from exc

    folder = root / "contracts"
    obligations: list[dict[str, Any]] = []
    for path in acceptance:
        path = (cwd / path).resolve()
        if not path.exists():
            raise UsageError(f"acceptance tests not found: {path}")
        obligations.append(
            {
                "id": f"acceptance-{path.stem}",
                "kind": "acceptance",
                "mandatory": True,
                "protected": os.path.relpath(path, folder),
                "command": [
                    "{python}",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "{protected}",
                ],
            }
        )
    if "obligations" in defaults:
        obligations += [dict(o) for o in defaults["obligations"]]
    elif (root / "tests").is_dir():
        obligations.append(
            {
                "id": "tests",
                "kind": "regression",
                "mandatory": False,
                "command": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
            }
        )

    raw: dict[str, Any] = {"title": title, "mode": mode, "change_summary": summary}
    if "python" in defaults:
        raw["python"] = defaults["python"]
    if "environment" in defaults:
        raw["environment"] = defaults["environment"]
    raw["obligations"] = obligations
    errors = validate_contract(raw)
    if errors:
        raise UsageError("contract would not be valid:\n  " + "\n  ".join(errors))

    lines = [f"{k} = {_toml_value(v)}" for k, v in raw.items() if k != "obligations"]
    for ob in obligations:
        lines += ["", "[[obligations]]", *(f"{k} = {_toml_value(v)}" for k, v in ob.items())]
    folder.mkdir(exist_ok=True)
    number = 1 + max(
        (int(p.name[:4]) for p in folder.glob("[0-9][0-9][0-9][0-9]-*.toml")), default=0
    )
    path = folder / f"{number:04d}-{_slug(title)}.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if accept:
        accept_contract(cwd, path, sandbox=sandbox)
    return path


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
DENY_READ = ["~/.ssh"]  # plus the keys directory, see _deny_read


def _reserved(obligation_id: str) -> bool:
    return obligation_id == WEAKENING or obligation_id.startswith(NO_NEW_FAILURES)


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


def _checker_python(
    body_python: str,
    environment: dict[str, Any] | None,
    pdir: Path,
    root: Path,
    python_root: Path | None = None,
) -> tuple[str, str, str]:
    """The checkers' interpreter, and an outcome and note when its environment is unusable.

    A relative `python` resolves against `python_root` (default `root`): in CI the base
    is a bare copy without the candidate's virtual environment."""
    where = python_root or root
    python = str(where / body_python) if body_python != "unknown" else sys.executable
    if environment:
        try:
            python = str(_checker_environment(environment, pdir, root))
        except _EnvironmentChanged as exc:
            return python, "invalid", str(exc)
        except EnvironmentUnavailable as exc:
            return python, "unavailable", f"checker environment unavailable: {exc}"
    return python, "", ""


def _regression_run(
    ob: dict[str, Any],
    root: Path,
    run_dir: Path,
    srt: Path | None,
    python: str,
    protected: Path | None = None,
) -> tuple[str, dict[str, str] | None]:
    junit = run_dir / "tmp" / f"junit-{ob['id']}.xml"
    r = run_obligation(
        ob,
        candidate=root,
        protected=protected,
        run_dir=run_dir,
        srt=srt,
        deny_read=_deny_read(),
        python=python,
        extra_env=junit_env(junit),
    )
    return r.outcome, read_results(junit)


def _regression_baselines(
    obligations: list[dict[str, Any]],
    raw: dict[str, Any],
    environment: dict[str, Any] | None,
    pdir: Path,
    root: Path,
    sandbox: str,
    python_root: Path | None = None,
) -> dict[str, Any]:
    """Run each advisory regression suite once at acceptance and add its built-in check."""
    advisory = [o for o in obligations if o.get("kind") == "regression" and not o["mandatory"]]
    if not advisory:
        return {}
    srt = _checker_srt(sandbox)
    python, env_outcome, _ = _checker_python(
        raw.get("python", "unknown"), environment, pdir, root, python_root
    )
    run_dir = pdir / "runs" / f"accept-{uuid.uuid4().hex[:12]}"
    baselines: dict[str, Any] = {}
    for ob in advisory:
        if env_outcome:
            baselines[ob["id"]] = regression_baseline(env_outcome, None)
        else:
            protected = pdir / ob["protected_store_path"] if "protected_store_path" in ob else None
            ran = _regression_run(ob, root, run_dir, srt, python, protected)
            baselines[ob["id"]] = regression_baseline(*ran)
        obligations.append(_no_new_failures(ob["id"], len(advisory) == 1))
    return baselines


def _files(manifest: dict[str, Any]) -> list[str]:
    return [e["path"] for e in manifest["entries"] if e["type"] == "file"]


class _EnvironmentChanged(Exception):
    """The candidate's lockfile, or its accepted copy, differs from what was accepted."""


def _lock_environment(raw: dict[str, Any], pdir: Path, root: Path) -> dict[str, Any] | None:
    """At acceptance, lock `uv.lock` like a protected test (T77 item 10)."""
    if raw.get("environment") is None:
        return None
    lockfile = root / LOCKFILE
    if not lockfile.is_file():
        raise UsageError(f'environment = "uv" needs {LOCKFILE} in the repository root')
    tdig = tree_digest(lockfile)
    dest = pdir / "protected" / tdig.removeprefix("sha256:")[:16] / LOCKFILE
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lockfile, dest)
    return {
        "kind": raw["environment"],
        "lock_digest": tdig,
        "lock_store_path": str(dest.relative_to(pdir)),
    }


def _checker_environment(environment: dict[str, Any], pdir: Path, root: Path) -> Path:
    """The protected environment's interpreter; nothing from the candidate's `.venv`."""
    copy = pdir / environment["lock_store_path"]
    if not copy.is_file() or tree_digest(copy) != environment["lock_digest"]:
        raise _EnvironmentChanged(f"the accepted copy of {LOCKFILE} changed in the store")
    lockfile = root / LOCKFILE
    if not lockfile.is_file() or tree_digest(lockfile) != environment["lock_digest"]:
        raise _EnvironmentChanged(
            f"{LOCKFILE} changed since contract acceptance; accept a contract revision"
        )
    return ensure(pdir / "envs", copy, root).python


def _gate_to_dict(gate: GateEvaluation) -> dict[str, Any]:
    data = asdict(gate)
    data["obligations"] = [{**o, "reasons": list(o["reasons"])} for o in data["obligations"]]
    return data


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


def verify(cwd: Path, sandbox: str = "auto") -> tuple[Record, Path]:
    """Capture the candidate, run every obligation, evaluate the gate, write the report."""
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
        baselines: dict[str, Any] = contract.body.get("regression_baseline", {})
        regression_runs: dict[str, tuple[str, dict[str, str] | None]] = {}

        observations: list[Observation] = []
        raw_obs: list[dict[str, Any]] = []
        not_started = 0
        for ob in contract.body["obligations"]:
            protected = None
            note = ""
            ob_protection = protection
            if "protected_store_path" in ob:
                protected = pdir / ob["protected_store_path"]
                if tree_digest(protected) != ob["protected_digest"]:
                    note = "protected material changed since contract acceptance"
            if ob.get("builtin") == WEAKENING:
                start = time.monotonic()
                current = weakening_snapshot(root, _files(before))
                findings = compare_weakening(contract.body["weakening_baseline"], current)
                outcome = "fail" if findings else "pass"
                note = "; ".join(findings)
                out = "\n".join(findings).encode()
                ms = int((time.monotonic() - start) * 1000)
                exit_code, argv = None, ob["command"]
            elif ob.get("builtin") == NO_NEW_FAILURES:
                ran = regression_runs.get(ob["of"])
                if ran is None:
                    outcome, note = "unavailable", f"the {ob['of']!r} suite did not run"
                else:
                    outcome, note = compare_regression(baselines[ob["of"]], *ran)
                out, ms, exit_code, argv = note.encode(), 0, None, ob["command"]
            elif env_note:
                outcome, exit_code, out, ms, argv = env_outcome, None, b"", 0, ob["command"]
                note = env_note
            elif note:
                outcome, exit_code, out, ms, argv = "invalid", None, b"", 0, ob["command"]
            else:
                junit = run_dir / "tmp" / f"junit-{ob['id']}.xml"
                r = run_obligation(
                    ob,
                    candidate=root,
                    protected=protected,
                    run_dir=run_dir,
                    srt=srt,
                    deny_read=deny_read,
                    python=python,
                    extra_env=junit_env(junit) if ob["id"] in baselines else None,
                )
                if ob["id"] in baselines:
                    regression_runs[ob["id"]] = (r.outcome, read_results(junit))
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
        for o in raw_obs:
            if mutated:
                o["outcome"], o["note"] = "invalid", "candidate changed during verification"
            store.append("observation", o, now=now_utc())
            observations.append(
                Observation(o["obligation_id"], o["subject_digest"], o["outcome"], o["note"])
            )

        obligations = [Obligation(ob["id"], ob["mandatory"]) for ob in contract.body["obligations"]]
        gate = evaluate_gate(obligations, observations, before["digest"])
        gate_rec = store.append("gate_evaluation", _gate_to_dict(gate), now=now_utc())

        report = {
            "readiness": READINESS[gate.result],
            "contract": {
                "revision_id": contract.revision_id,
                "title": contract.body["title"],
                "governance_level": contract.body["governance_level"],
                "policy_version": contract.body["policy_version"],
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
            "protection": {"verifier": protection, "agent": "unknown: no agent run recorded"},
            "cost": {
                "agent_work": _agent_cost(store, contract.revision_id),
                "overhead": {
                    "model_calls": 0,
                    "verifier_ms": sum(o["duration_ms"] for o in raw_obs),
                },
            },
            "changelog_entry": f"- {contract.body['change_summary']}",
            "limitations": [
                f"{before['ignored_present']} ignored file(s) present and not in the candidate"
                " identity",
                *_interpreter_limitations(environment, python, root),
                *_regression_limitations(contract.body),
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


def _interpreter_limitations(
    environment: dict[str, Any] | None, python: str, root: Path
) -> list[str]:
    """Name the blind spot when checkers ran with an interpreter from the candidate."""
    if environment or not Path(python).is_relative_to(root):
        return []
    return [
        f"Checkers ran with an interpreter inside the candidate ({python}), usually a .venv"
        " that is git-ignored and outside the candidate identity, so changes to it are not"
        ' detected; set environment = "uv" in ohx.toml'
    ]


def current_report(cwd: Path) -> dict[str, Any]:
    """The latest report, re-checked against the repository and contract as they are now.

    A stored report is evidence about one candidate under one contract revision.
    If either has changed, it is shown as stale, never as ready. If the store, an
    evidence file or a protected copy fails its integrity check, it is invalid.
    """
    root, pdir, store = _open(cwd)
    try:
        rec = store.latest("assurance_report")
        if rec is None:
            raise UsageError("no report yet; run `ohx verify`")
        report = dict(rec.body)
        reasons: list[str] = []
        now_manifest = build_manifest(root)
        if now_manifest["digest"] != report["candidate"]["digest"]:
            reasons.append("subject_changed: the repository differs from the verified candidate")
            then = store.get(report["candidate"]["revision_id"])
            if then is not None:
                report["stale_paths"] = changed_paths(then.body, now_manifest)
        contract = store.latest("contract")
        if contract is None or contract.revision_id != report["contract"]["revision_id"]:
            reasons.append("manifest_revised: a newer contract revision has been accepted")
        # A signature that no longer matches is as untrustworthy as a broken chain.
        problems = _integrity_problems(pdir, store) + _signature_problems(store, [])[0]
        report["signature"] = _signature_status(store, rec.revision_id)
    finally:
        store.close()
    if problems:
        # Evidence that cannot be re-checked outranks staleness (GATE-09, STATE-15, GATE-10).
        report["verified_readiness"] = report["readiness"]
        report["readiness"] = "invalid"
        report["integrity_problems"] = problems
    elif reasons:
        report["verified_readiness"] = report["readiness"]
        report["readiness"] = "stale"
        report["stale_reasons"] = reasons
    return report


def _integrity_problems(pdir: Path, store: Store) -> list[str]:
    """Store records and evidence files, plus every accepted protected copy."""
    problems = store.check()
    seen: set[str] = set()
    for contract in store.all("contract"):
        environment = contract.body.get("environment")
        if environment and environment["lock_store_path"] not in seen:
            rel = environment["lock_store_path"]
            seen.add(rel)
            copy = pdir / rel
            if not copy.is_file():
                problems.append(f"protected copy {rel} is missing")
            elif tree_digest(copy) != environment["lock_digest"]:
                problems.append(f"protected copy {rel} changed since contract acceptance")
        for ob in contract.body["obligations"]:
            rel = ob.get("protected_store_path")
            if rel is None or rel in seen:
                continue
            seen.add(rel)
            path = pdir / rel
            if not path.exists():
                problems.append(f"protected copy {rel} is missing")
            elif tree_digest(path) != ob["protected_digest"]:
                problems.append(f"protected copy {rel} changed since contract acceptance")
    return problems


def check_store(cwd: Path, signers: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Problems, and a summary of who signed what; `signers` pins the expected keys."""
    _, pdir, store = _open(cwd)
    try:
        pins = [_pin(s) for s in signers or []]
        problems = _integrity_problems(pdir, store) + _signature_problems(store, pins)[0]
        return sorted(set(problems), key=problems.index), _signature_summary(store)
    finally:
        store.close()


SIGNATURE = "signature"


def _project_id(store: Store) -> str:
    project = store.latest("project")
    return project.entity_id if project else "unknown"


def _pin(value: str) -> str:
    if value.startswith("SHA256:"):
        return value
    try:
        return fingerprint(Path(value).expanduser().read_text().strip())
    except (OSError, SigningError) as exc:
        raise UsageError(f"--signer {value}: not a fingerprint or a readable public key") from exc


def _valid_signatures(store: Store) -> tuple[list[Record], list[str]]:
    """Signatures that verify against the chain as it is now, and problems with the rest."""
    valid, problems = [], []
    project = _project_id(store)
    for rec in store.all(SIGNATURE):
        b = rec.body
        seq, chain_hash = b.get("seq"), b.get("hash")
        if not isinstance(seq, int) or not isinstance(chain_hash, str):
            problems.append(f"signature over record {seq}: malformed")
            continue
        if store.hash_at(seq) != chain_hash:
            problems.append(f"signature over record {seq}: the chain no longer matches it")
            continue
        try:
            sig = store.blob_path(b["signature_blob"]).read_bytes()
        except (KeyError, OSError):
            problems.append(f"signature over record {seq}: the signature file is missing")
            continue
        made_by = signer_of(signed_message(project, seq, chain_hash), sig)
        if made_by is None:
            problems.append(f"signature over record {seq}: does not verify")
        elif made_by != b.get("fingerprint"):
            problems.append(f"signature over record {seq}: made by {made_by}, not the recorded key")
        else:
            valid.append(rec)
    return valid, problems


def _signature_problems(store: Store, pins: list[str]) -> tuple[list[str], list[Record]]:
    valid, problems = _valid_signatures(store)
    if pins:
        for rec in valid:
            if rec.body["fingerprint"] not in pins:
                problems.append(
                    f"signature over record {rec.body['seq']}: signed by an unexpected key"
                    f" {rec.body['fingerprint']}, not by {', '.join(pins)}"
                )
    return problems, valid


def _signature_summary(store: Store) -> list[str]:
    valid, _ = _valid_signatures(store)
    lines, covered = [], 0
    by_key: dict[str, tuple[str, int]] = {}
    for rec in valid:
        b = rec.body
        signer = b.get("signer") or {}
        who = f"{signer.get('name', 'unknown')} <{signer.get('email', 'unknown')}>"
        by_key[b["fingerprint"]] = (who, max(b["seq"], by_key.get(b["fingerprint"], ("", 0))[1]))
        covered = max(covered, b["seq"])
    for fp, (who, upto) in by_key.items():
        lines.append(f"signed by {who}, key {fp}, through record {upto}")
    unsigned = store.count_after(covered, SIGNATURE)
    lines.append(f"{unsigned} unsigned record(s) after the last signature")
    return lines


def _signature_status(store: Store, revision_id: str) -> dict[str, Any]:
    """Whether a valid signature covers this record."""
    seq = store.seq_of(revision_id) or 0
    valid, _ = _valid_signatures(store)
    covering = [r for r in valid if r.body["seq"] >= seq]
    if not covering:
        return {"status": "unsigned"}
    b = covering[0].body
    return {
        "status": "signed",
        "fingerprint": b["fingerprint"],
        "signer": b.get("signer"),
        "through": b["seq"],
    }


def sign_evidence(cwd: Path) -> str:
    """Sign the head of the evidence chain; returns a line for the user, or nothing."""
    if os.environ.get(KEY_ENV) == "none":
        return ""
    try:
        root, _, store = _open(cwd)
    except UsageError:
        return ""
    try:
        head = store.head()
        if head is None or head[2] == SIGNATURE:
            return ""
        seq, chain_hash, _ = head
        key = find_key(root)
        if key is None:
            return f"evidence not signed: no SSH key found; set {KEY_ENV}"
        try:
            pub = public_key(key)
            fp = fingerprint(pub)
            sig = sign(signed_message(_project_id(store), seq, chain_hash), key)
        except SigningError as exc:
            return f"evidence not signed: {exc}"
        store.append(
            SIGNATURE,
            {
                "seq": seq,
                "hash": chain_hash,
                "public_key": pub,
                "fingerprint": fp,
                "signer": git_user(root),
                "signature_blob": store.put_blob(sig),
            },
            now=now_utc(),
        )
        return f"signed the evidence through record {seq} with {fp}"
    finally:
        store.close()
