"""Acceptance tests for T77 items 3, 5 and 6 (contracts/0009).

Found by the independent review on `fb39881`. `ohx report` trusted the
store without re-checking it, and `ohx store check` did not look at evidence
files or protected copies:

- GATE-09: an edited saved verdict made `ohx report` return READY.
- STATE-15: deleting a referenced evidence file still gave `store ok` and READY.
- GATE-10: changing the protected acceptance copy left the report READY.

A report whose evidence cannot be re-checked is never ready, and
`ohx store check` names the problem.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
DEFAULTS = f"python = {sys.executable!r}\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text(BUGGY)
    (repo / "ohx.toml").write_text(DEFAULTS)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    home = tmp_path / "home"
    monkeypatch.setenv("OHX_HOME", str(home))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept"]) == EXIT_OK
    return home


def _pdir(home: Path) -> Path:
    (pdir,) = (home / "projects").iterdir()
    return pdir


def _ready(repo: Path) -> None:
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


def _report(capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    capsys.readouterr()
    code = main(["report", "--json"])
    report: dict[str, object] = json.loads(capsys.readouterr().out)
    return code, report


def test_control_untouched_evidence_is_ready_and_store_ok(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ready(Path.cwd())
    code, report = _report(capsys)
    assert code == EXIT_OK and report["readiness"] == "ready"
    assert main(["store", "check"]) == EXIT_OK


def test_edited_saved_verdict_is_not_ready(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """GATE-09: a BLOCKED report edited in the store to say ready."""
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    db = sqlite3.connect(_pdir(home) / "store.sqlite")
    with db:
        (rid, body) = db.execute(
            "SELECT r.revision_id, r.body FROM revisions r JOIN events e"
            " ON e.revision_id = r.revision_id WHERE e.entity_type = 'assurance_report'"
            " ORDER BY e.seq DESC LIMIT 1"
        ).fetchone()
        report = json.loads(body)
        report["readiness"] = "ready"
        report["gate"]["result"] = "pass"
        db.execute("UPDATE revisions SET body = ? WHERE revision_id = ?", (json.dumps(report), rid))
    db.close()
    code, shown = _report(capsys)
    assert code == EXIT_BLOCKED and shown["readiness"] != "ready"
    assert main(["store", "check"]) == EXIT_BLOCKED


def test_deleted_evidence_file_is_not_ready(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """STATE-15: a checker output referenced by an observation is deleted."""
    _ready(Path.cwd())
    _, report = _report(capsys)
    observations = report["observations"]
    assert isinstance(observations, list)
    blob = observations[0]["output_blob"]
    hexpart = blob.removeprefix("sha256:")
    (_pdir(home) / "blobs" / "sha256" / hexpart[:2] / hexpart[2:]).unlink()
    code, shown = _report(capsys)
    assert code == EXIT_BLOCKED and shown["readiness"] != "ready"
    assert main(["store", "check"]) == EXIT_BLOCKED


def test_changed_evidence_file_is_not_ready(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """STATE-15 variant: a referenced checker output is rewritten."""
    _ready(Path.cwd())
    _, report = _report(capsys)
    observations = report["observations"]
    assert isinstance(observations, list)
    hexpart = observations[0]["output_blob"].removeprefix("sha256:")
    (_pdir(home) / "blobs" / "sha256" / hexpart[:2] / hexpart[2:]).write_bytes(b"1 passed\n")
    code, shown = _report(capsys)
    assert code == EXIT_BLOCKED and shown["readiness"] != "ready"
    assert main(["store", "check"]) == EXIT_BLOCKED


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_changed_protected_copy_is_not_ready(
    home: Path, capsys: pytest.CaptureFixture[str], change: str
) -> None:
    """GATE-10: the locked acceptance copy in the store is changed after verification."""
    _ready(Path.cwd())
    (copy,) = (_pdir(home) / "protected").rglob("test_calc.py")
    if change == "edit":
        copy.write_text("def test_add():\n    pass\n")
    else:
        copy.unlink()
    code, shown = _report(capsys)
    assert code == EXIT_BLOCKED and shown["readiness"] != "ready"
    assert main(["store", "check"]) == EXIT_BLOCKED
