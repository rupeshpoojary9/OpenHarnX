"""Accepting and writing contracts, and the baselines taken at acceptance."""

from __future__ import annotations

import json
import os
import shutil
import tomllib
import uuid
from pathlib import Path
from typing import Any

from openharnx.app.checks import (
    MUTATION,
    MUTATION_OBLIGATION,
    NO_NEW_FAILURES,
    WEAKENING,
    WEAKENING_OBLIGATION,
    _checker_srt,
    _deny_read,
    _no_new_failures,
    _reserved,
)
from openharnx.app.core import (
    UsageError,
    _cause,
    _files,
    _open,
    _slug,
    _toml_value,
    now_utc,
    project_python,
)
from openharnx.app.environments import (
    _checker_python,
    _fingerprint,
    _lock_environment,
    _protected_modules,
)
from openharnx.app.suites import (
    PYTEST,
    _go_suite,
    _js_suite,
    _pytest_args,
    _suite_fields,
    _suite_timeout,
)
from openharnx.app.trees import _modules_view, _tree_view, _TreeChanged
from openharnx.kernel.contract import validate_contract
from openharnx.regression import baseline as regression_baseline
from openharnx.regression import (
    junit_env,
    read_go_results,
    read_results,
)
from openharnx.store import Record
from openharnx.verify import run_obligation
from openharnx.weakening import JS_SOURCE
from openharnx.weakening import snapshot as weakening_snapshot
from openharnx.workspace import (
    NotARepository,
    build_manifest,
    git_user,
    repo_root,
    tree_digest,
)


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


def _default_suites(root: Path, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """The project's whole suites as regression checks: pytest on tests/, and the
    TypeScript, JavaScript or Go runner `ohx gate` would use (T93; before it, only pytest,
    so a TypeScript contract checked nothing but its acceptance tests)."""
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
