"""Use cases shared by every interface: init, contract acceptance, verification."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openharnx.app.approval import describe as describe_approval
from openharnx.environment import (
    LOCKFILES,
    EnvironmentUnavailable,
    ensure,
    ensure_npm,
    interpreter_changes,
    interpreter_fingerprint,
)
from openharnx.kernel.canonical import digest
from openharnx.kernel.contract import validate_contract
from openharnx.kernel.gate import GateEvaluation, Obligation, Observation, evaluate_gate
from openharnx.mutation import PROBE_ENV, Mutant, changed_lines
from openharnx.mutation import select as select_mutants
from openharnx.regression import baseline as regression_baseline
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
from openharnx.verify.where import foreign_code, loaded_modules, project_files, where_env
from openharnx.weakening import JS_SOURCE, active_checkers, is_test_file
from openharnx.weakening import compare as compare_weakening
from openharnx.weakening import snapshot as weakening_snapshot
from openharnx.workspace import (
    NotARepository,
    build_manifest,
    changed_paths,
    file_digest,
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
                f"obligation ids {WEAKENING!r}, {MUTATION!r} and {NO_NEW_FAILURES!r}..., and"
                " `builtin`, are reserved"
            )
        obligations.append(dict(WEAKENING_OBLIGATION))
        if any(ob.get("kind") == "acceptance" for ob in obligations):
            obligations.append(dict(MUTATION_OBLIGATION))
        environment = _lock_environment(raw, pdir, base)
        baselines = _regression_baselines(obligations, raw, environment, pdir, base, sandbox, root)
        interpreter = None
        if environment is None:  # a locked environment is checked its own way (T77)
            python, _, _ = _checker_python(raw.get("python", "unknown"), None, pdir, base, root)
            interpreter = _fingerprint(store, python)
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
            **({"interpreter": interpreter} if interpreter else {}),
            **(
                {"mutation_budget_s": raw["mutation_budget_s"]}
                if "mutation_budget_s" in raw
                else {}
            ),
            "weakening_baseline": weakening_snapshot(base, _files(accepted_tree)),
            "accepted_by": git_user(root),
            "accepted_paths": sorted(
                str(p.relative_to(root)) for p in written if p.is_relative_to(root)
            ),
            "accepted_manifest_blob": store.put_blob(
                json.dumps(accepted_tree, sort_keys=True).encode()
            ),
            **({"regression_baseline": baselines} if baselines else {}),
            **(
                {
                    "approval": {
                        k.removeprefix("approved_"): v
                        for k, v in raw.items()
                        if k.startswith("approved_")
                    }
                }
                if raw.get("approved_by")
                else {}
            ),
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
        ob: dict[str, Any] = {
            "id": f"acceptance-{_slug(path.name.split('.')[0])}",
            "kind": "acceptance",
            "mandatory": True,
            "protected": os.path.relpath(path, folder),
        }
        if path.name.endswith("_test.go"):
            # A Go test belongs to its package: the locked copy runs at its own path with
            # the rest of the package (T82).
            if not path.is_relative_to(root):
                raise UsageError(f"{path.name}: Go acceptance tests must be inside the repository")
            rel = path.relative_to(root)
            ob["protected_at"] = str(rel)
            ob["command"] = ["go", "test", "-count=1", f"./{rel.parent.as_posix()}"]
            ob["env"] = {
                "GOTOOLCHAIN": "local",
                "GOFLAGS": "-mod=readonly",
                "GOCACHE": "{tmp}/go-build",
            }
        elif path.name.endswith(JS_SOURCE):
            # TypeScript and JavaScript tests import the code next to them, so the locked
            # copy runs at its own path in a copy of the tree (T82).
            if not path.is_relative_to(root):
                raise UsageError(
                    f"{path.name}: TypeScript and JavaScript acceptance tests must be inside"
                    " the repository, because they run at their own path"
                )
            ob["protected_at"] = str(path.relative_to(root))
            ob["command"] = _js_test_command(root, defaults)
        else:
            ob["id"] = f"acceptance-{path.stem}"
            ob["command"] = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
            ob["command"].append("{protected}")
        obligations.append(ob)
    if "obligations" in defaults:
        obligations += [dict(o) for o in defaults["obligations"]]
    else:
        obligations += _default_suites(root, defaults)

    raw: dict[str, Any] = {"title": title, "mode": mode, "change_summary": summary}
    if "python" in defaults:
        raw["python"] = defaults["python"]
    elif "environment" not in defaults and project_python(root):
        raw["python"] = project_python(root)
    if "environment" in defaults:
        raw["environment"] = defaults["environment"]
    if "mutation_budget_s" in defaults:
        raw["mutation_budget_s"] = defaults["mutation_budget_s"]
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


JS_RUNNERS: dict[str, list[str]] = {
    "vitest": ["node_modules/.bin/vitest", "run", "{protected}"],
    "jest": ["node_modules/.bin/jest", "--ci", "{protected}"],
    "node": ["node", "--test", "{protected}"],
}


def _js_test_command(root: Path, defaults: dict[str, Any]) -> list[str]:
    """`js_runner` from ohx.toml, else Vitest or Jest when installed, else Node's own runner."""
    runner = defaults.get("js_runner")
    if runner is None:
        bins = root / "node_modules" / ".bin"
        runner = next((r for r in ("vitest", "jest") if (bins / r).exists()), "node")
    if runner not in JS_RUNNERS:
        raise UsageError(f"js_runner must be one of {sorted(JS_RUNNERS)}")
    return list(JS_RUNNERS[runner])


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
    if environment and environment["kind"] == "uv":
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
    modules: Path | None = None,
) -> tuple[str, dict[str, str] | None, str]:
    junit = run_dir / "tmp" / f"junit-{ob['id']}.xml"
    if protected is not None and ob.get("protected_at"):
        at = ob["protected_at"]
        try:
            root = _tree_view(
                build_manifest(root), root, protected, at, run_dir / f"tree-{ob['id']}", modules
            )
        except _TreeChanged:
            return "invalid", None, "the tree changed while it was copied"
        protected = root / at
    elif modules is not None:
        try:
            root = _modules_view(build_manifest(root), root, modules, run_dir / f"tree-{ob['id']}")
        except _TreeChanged:
            return "invalid", None, "the tree changed while it was copied"
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
    return r.outcome, read_results(junit, root) or read_go_results(r.output), _cause(r.output)


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
    modules, npm_outcome, _ = _protected_modules(environment, pdir, root)
    env_outcome = env_outcome or npm_outcome
    run_dir = pdir / "runs" / f"accept-{uuid.uuid4().hex[:12]}"
    baselines: dict[str, Any] = {}
    for ob in advisory:
        if env_outcome:
            baselines[ob["id"]] = regression_baseline(env_outcome, None)
        else:
            protected = pdir / ob["protected_store_path"] if "protected_store_path" in ob else None
            outcome, tests, cause = _regression_run(
                ob, root, run_dir, srt, python, protected, modules
            )
            baselines[ob["id"]] = regression_baseline(outcome, tests)
            if outcome not in ("pass", "fail"):
                baselines[ob["id"]]["cause"] = cause  # shown by `ohx init --lock-tests` (T94)
        obligations.append(_no_new_failures(ob["id"], len(advisory) == 1))
    return baselines


class _TreeChanged(Exception):
    """A file changed while the tree was being copied for a locked run."""


# `protected_at = "."`: the locked material is a folder of test files at their own paths,
# laid over the tree in place of the candidate's TypeScript and JavaScript test files (T82).
OVERLAY = "."


def _copy_tree(manifest: dict[str, Any], root: Path, dest: Path, skip: str | None = None) -> None:
    """Copy the tree as `manifest` records it, checking each file against its digest."""
    for e in manifest["entries"]:
        rel = e["path"]
        if skip == OVERLAY:
            if is_test_file(rel) and rel.endswith((*JS_SOURCE, ".go")):
                continue
        elif skip is not None and (rel == skip or rel.startswith(skip + "/")):
            continue
        if e["type"] not in ("file", "symlink"):
            continue
        src, dst = root / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if e["type"] == "symlink":
            os.symlink(os.readlink(src), dst)
            continue
        shutil.copy2(src, dst)
        if file_digest(dst) != e["digest"]:
            raise _TreeChanged(f"{rel} changed while the tree was being copied")


def _link_node_modules(modules: Path, dest: Path) -> None:
    """Git ignores node_modules, so a copy of the tree lacks it. Link the protected one
    (`environment = "npm"`), else the candidate's own (named in the limitations)."""
    if modules.is_dir() and not (dest / "node_modules").exists():
        (dest / "node_modules").symlink_to(modules.resolve())


def _modules_view(manifest: dict[str, Any], root: Path, modules: Path, dest: Path) -> Path:
    """A copy of the tree with the protected node_modules, for checks that run on the tree."""
    if not dest.exists():
        _copy_tree(manifest, root, dest)
        _link_node_modules(modules, dest)
    return dest


def _tree_view(
    manifest: dict[str, Any],
    root: Path,
    protected: Path,
    at: str,
    dest: Path,
    modules: Path | None = None,
) -> Path:
    """A copy of the tree as `manifest` records it, with `at` replaced by the locked copy.

    Locked tests then run where they would run in the repository, so tests that find
    files relative to their own location work (RC-31). Each copied file is checked
    against its digest: the copy is the judged candidate, or the run is invalid.
    """
    _copy_tree(manifest, root, dest, skip=at)
    _link_node_modules(modules or root / "node_modules", dest)
    if at == OVERLAY:
        shutil.copytree(
            protected, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
        )
    elif protected.is_dir():
        shutil.copytree(protected, dest / at, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        (dest / at).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(protected, dest / at)
    return dest


def _files(manifest: dict[str, Any]) -> list[str]:
    return [e["path"] for e in manifest["entries"] if e["type"] == "file"]


class _EnvironmentChanged(Exception):
    """The candidate's lockfile, or its accepted copy, differs from what was accepted."""


def _lock_environment(raw: dict[str, Any], pdir: Path, root: Path) -> dict[str, Any] | None:
    """At acceptance, lock `uv.lock` (T77 item 10) or `package-lock.json` with its
    `package.json` (T82) like a protected test."""
    if raw.get("environment") is None:
        return None
    kind = raw["environment"]
    name = LOCKFILES[kind]
    lockfile = root / name
    if not lockfile.is_file():
        raise UsageError(f'environment = "{kind}" needs {name} in the repository root')
    tdig = tree_digest(lockfile)
    extra: dict[str, Any] = {}
    folder = tdig.removeprefix("sha256:")[:16]
    if kind == "npm":
        package = root / "package.json"
        if not package.is_file():
            raise UsageError('environment = "npm" needs package.json in the repository root')
        extra["package_digest"] = pdig = tree_digest(package)
        folder = digest({"lock": tdig, "package": pdig}).removeprefix("sha256:")[:16]
    dest = pdir / "protected" / folder / name
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lockfile, dest)
        if kind == "npm":
            shutil.copy2(root / "package.json", dest.parent / "package.json")
    return {
        "kind": kind,
        "lock_digest": tdig,
        "lock_store_path": str(dest.relative_to(pdir)),
        **extra,
    }


_PACKAGE = re.compile(r"(?m)^\[\[package\]\]\s*$")
_OWN_SOURCE = re.compile(r'(?m)^source = \{ (?:editable|virtual) = "\." \}\s*$')
_VERSION_LINE = re.compile(r'(?m)^version = "[^"\n]*"\s*$')


def _without_own_version(text: str) -> str:
    """`uv.lock` with the version line of the project's own entry (source editable or
    virtual ".") blanked. The protected environment is built with --no-install-project,
    so that line never reaches it; every other line still counts."""
    parts = _PACKAGE.split(text)
    for i, block in enumerate(parts[1:], 1):
        if _OWN_SOURCE.search(block):
            parts[i] = _VERSION_LINE.sub('version = ""', block, count=1)
    return "[[package]]".join(parts)


def _same_lock(kind: str, candidate: Path, accepted: Path) -> bool:
    """Whether the candidate's lockfile is the accepted one; for uv, a bump of the
    project's own version is the same lockfile (T100)."""
    if tree_digest(candidate) == tree_digest(accepted):
        return True
    if kind != "uv":
        return False
    try:
        mine = candidate.read_text(encoding="utf-8")
        theirs = accepted.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _without_own_version(mine) == _without_own_version(theirs)


def _checker_environment(environment: dict[str, Any], pdir: Path, root: Path) -> Path:
    """The protected environment: the interpreter built from `uv.lock`, or the node_modules
    built from `package-lock.json`; nothing from the candidate's `.venv` or node_modules."""
    name = LOCKFILES[environment["kind"]]
    copy = pdir / environment["lock_store_path"]
    if not copy.is_file() or tree_digest(copy) != environment["lock_digest"]:
        raise _EnvironmentChanged(f"the accepted copy of {name} changed in the store")
    lockfile = root / name
    if not lockfile.is_file() or not _same_lock(environment["kind"], lockfile, copy):
        raise _EnvironmentChanged(
            f"{name} changed since contract acceptance; accept a contract revision"
        )
    if environment["kind"] == "npm":
        package = copy.parent / "package.json"
        if not package.is_file() or tree_digest(package) != environment.get("package_digest"):
            raise _EnvironmentChanged("the accepted copy of package.json changed in the store")
        return ensure_npm(pdir / "envs", copy, package)
    return ensure(pdir / "envs", copy, root).python


def _protected_modules(
    environment: dict[str, Any] | None, pdir: Path, root: Path
) -> tuple[Path | None, str, str]:
    """node_modules from the accepted lockfile, and an outcome and note when unusable."""
    if not environment or environment["kind"] != "npm":
        return None, "", ""
    try:
        return _checker_environment(environment, pdir, root), "", ""
    except _EnvironmentChanged as exc:
        return None, "invalid", str(exc)
    except EnvironmentUnavailable as exc:
        return None, "unavailable", f"checker environment unavailable: {exc}"


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


def _cause(output: bytes) -> str:
    """Why a checker crashed, in one line from its own output (T94): its last line that
    names an error, else its last line."""
    lines = [x.strip() for x in output.decode(errors="replace").splitlines() if x.strip()]
    if not lines:
        return ""
    named = [x for x in lines if x.startswith("ohx:") or "Error" in x or "error:" in x]
    return (named or lines)[-1][:300]


def project_python(root: Path) -> str | None:
    """The project's own interpreter when ohx.toml names none (T94): its .venv or venv,
    else the active virtual environment. None leaves OpenHarnX's own interpreter."""
    for folder in (".venv", "venv"):
        if (root / folder / "bin" / "python").exists():
            return str(root / folder / "bin" / "python")
    active = os.environ.get("VIRTUAL_ENV")
    if active and (Path(active) / "bin" / "python").exists():
        return str(Path(active) / "bin" / "python")
    return None


def _default_suites(root: Path, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """The project's whole suites as regression checks: pytest on tests/, and the
    TypeScript, JavaScript or Go runner `ohx gate` would use (T93; before it, only pytest,
    so a TypeScript contract checked nothing but its acceptance tests)."""
    from openharnx.app.gate import (  # gate imports app
        PYTEST,
        _go_suite,
        _js_suite,
        _pytest_args,
        _suite_fields,
        _suite_timeout,
    )

    suites: list[dict[str, Any]] = []
    if (root / "tests").is_dir():
        pytest = [*PYTEST, *_pytest_args(defaults)]
        # The locked copy, as `ohx init --lock-tests` and `ohx gate` run it (T95): an
        # acceptance contract must not unlock the tests the change has to keep passing.
        suites.append(
            {
                "id": "locked-tests",
                "kind": "regression",
                "mandatory": False,
                "protected": os.path.relpath(root / "tests", root / "contracts"),
                "protected_at": "tests",
                "command": [*pytest, "{protected}"],
            }
        )
        command = [*pytest, "tests"]
        suites.append({"id": "tests", "kind": "regression", "mandatory": False, "command": command})
    for lang, suite in (("js", _js_suite(root, defaults)), ("go", _go_suite(root))):
        if suite is not None:
            taken = {o["id"] for o in suites}
            oid = "tests" if "tests" not in taken else f"{lang}-tests"
            suites.append(
                {"id": oid, "kind": "regression", "mandatory": False, **_suite_fields(suite)}
            )
    limit = _suite_timeout(defaults)
    return [{**s, "timeout_s": s.get("timeout_s", limit)} for s in suites]


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


def _node_modules_limitations(body: dict[str, Any], root: Path) -> list[str]:
    """Name the blind spot when JavaScript checkers resolve packages from the candidate."""
    uses_node = any(
        "node_modules" in " ".join(ob.get("command", [])) or ob.get("command", [""])[0] == "node"
        for ob in body["obligations"]
    )
    if not uses_node or not (root / "node_modules").is_dir():
        return []
    if (body.get("environment") or {}).get("kind") == "npm":
        return []  # checks used the node_modules built from the accepted lockfile
    return [
        "JavaScript checkers resolved packages from node_modules in the candidate, which is"
        " git-ignored and outside the candidate identity, so changes to it are not detected"
    ]


def _interpreter_limitations(
    environment: dict[str, Any] | None,
    python: str,
    root: Path,
    recorded: dict[str, Any] | None = None,
) -> list[str]:
    """Name the interpreter the checkers ran with whenever no locked environment holds it,
    wherever it is, and what its fingerprint covers (T99)."""
    if environment:
        return []
    where = (
        " (inside the candidate, usually a .venv that is git-ignored)"
        if Path(python).is_relative_to(root)
        else ""
    )
    if recorded:
        covered = (
            f"its environment ({recorded['files']} files in"
            f" {', '.join(recorded.get('dirs', [])) or 'unrecorded folders'}) was"
            " fingerprinted at acceptance and matched before the checks ran, so later"
            " changes there are caught; changes made before acceptance, compiled"
            " __pycache__ files, and code loaded from other folders are not"
        )
    else:
        covered = (
            "this contract holds no fingerprint of its environment (accepted before T99, or"
            " the interpreter could not be asked), so changes to it are not detected"
        )
    return [
        f"Checkers ran with {python}{where}, outside the candidate identity and in no"
        f' locked environment: {covered}; environment = "uv" in ohx.toml locks it'
    ]


def _fingerprint(store: Store, python: str) -> dict[str, Any] | None:
    """The checker interpreter's fingerprint for the contract, with its file list kept as a
    blob so a later change can name removed files; None when it cannot be taken (T99)."""
    try:
        taken = interpreter_fingerprint(python, time.time_ns())
    except (EnvironmentUnavailable, OSError, ValueError, subprocess.TimeoutExpired):
        return None
    entries = taken.pop("_entries")
    assert isinstance(entries, dict)
    taken["paths_blob"] = store.put_blob(json.dumps(sorted(entries)).encode())
    return taken


def _interpreter_problem(store: Store, recorded: dict[str, Any], python: str) -> str:
    """Why the checkers must not run with this interpreter; empty when it is as accepted."""
    if recorded.get("python") != python:
        return (
            f"the checker interpreter is {python}, not {recorded.get('python')} as when the"
            " contract was accepted; accept the contract again (`ohx contract accept <file>`)"
        )
    try:
        now = interpreter_fingerprint(python, time.time_ns())
    except (EnvironmentUnavailable, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"the checker interpreter {python} could not be checked: {exc}"
    try:
        paths: set[str] | None = set(
            json.loads(store.blob_path(recorded["paths_blob"]).read_bytes())
        )
    except (OSError, ValueError, KeyError):
        paths = None
    return interpreter_changes(recorded, paths, now)


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
        # A pinned key must cover the whole store: removing signatures and rebuilding the
        # chain leaves nothing to check, which is not the same as nothing wrong.
        pinned = [r.body["seq"] for r in valid if r.body["fingerprint"] in pins]
        expected = ", ".join(pins)
        if not pinned:
            problems.append(f"not signed by {expected}: no valid signature from that key")
        elif unsigned := store.count_after(max(pinned), SIGNATURE):
            problems.append(
                f"{unsigned} record(s) after record {max(pinned)} are not signed by {expected}"
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
