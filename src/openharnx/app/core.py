"""What every use case shares: the error type, the clock, the store and init."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openharnx.kernel.canonical import digest
from openharnx.kernel.gate import GateEvaluation
from openharnx.store import Record, Store
from openharnx.workspace import NotARepository, repo_root, root_commit

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


def _files(manifest: dict[str, Any]) -> list[str]:
    return [e["path"] for e in manifest["entries"] if e["type"] == "file"]


def _gate_to_dict(gate: GateEvaluation) -> dict[str, Any]:
    data = asdict(gate)
    data["obligations"] = [{**o, "reasons": list(o["reasons"])} for o in data["obligations"]]
    return data


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
