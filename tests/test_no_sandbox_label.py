"""Acceptance tests for the label of an unsandboxed run (contracts/0016).

Found while checking T87 item 1 (2026-10-03): with `--sandbox none` every
checker was labelled "the srt sandbox did not start the checker" and the
report said protection was "not enforced: the srt sandbox did not start N of
M checker(s)". No sandbox was requested, so nothing failed to start; the
report must say the checkers ran without isolation. Verdicts were not
affected. Self-contained.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main

ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def test_unsandboxed_run_is_labelled_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept", "--sandbox", "none"]) == 0
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    capsys.readouterr()
    main(["report", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["protection"]["verifier"].startswith("none")
    for o in report["observations"]:
        assert "did not start" not in o["note"]
        assert "did not start" not in o["protection"]
