"""Acceptance tests for T77 item 8, VERIFY-12 (contracts/0010).

Found by the independent review on `fb39881`: when srt could not start, the
result was recorded as a test failure "under enforcement". The exit code of a
sandbox that never ran the checker was read as the checker's own result, so
an srt that exits 0 without running anything would even read as a pass.

A checker the sandbox did not start is unavailable (unknown, never a pass),
and the report does not claim enforcement.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

FIXED = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"

# Stand-ins for srt. They are called as: srt -s <profile> -c <command>.
BROKEN = {
    "fails to start": "#!/bin/sh\necho 'srt: could not create socket' >&2\nexit 1\n",
    "exits 0 without running": "#!/bin/sh\nexit 0\n",
    "exits 5 without running": "#!/bin/sh\nexit 5\n",
}
RUNS = '#!/bin/sh\nshift 3\nexec /bin/sh -c "$1"\n'


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text(FIXED)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Fix add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept"]) == EXIT_OK
    return repo


def _fake_srt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    path = tmp_path / "fake-srt"
    path.write_text(script)
    path.chmod(0o755)
    monkeypatch.setenv("OHX_SRT", str(path))


def _report(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    main(["report", "--json"])
    report: dict[str, object] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize("script", list(BROKEN.values()), ids=list(BROKEN))
def test_sandbox_that_did_not_start_is_unknown_and_not_enforced(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    script: str,
) -> None:
    _fake_srt(tmp_path, monkeypatch, script)
    assert main(["verify", "--sandbox", "srt"]) == EXIT_BLOCKED
    report = _report(capsys)
    assert report["readiness"] == "unknown"
    observations = report["observations"]
    assert isinstance(observations, list)
    # Commands only: the built-in weakening check (T77 item 9) runs outside the sandbox.
    commands = [o for o in observations if o["obligation_id"] != "weakening"]
    assert {o["outcome"] for o in commands} == {"unavailable"}
    protection = report["protection"]
    assert isinstance(protection, dict)
    assert not protection["verifier"].startswith("enforced")


def test_control_sandbox_that_runs_the_checker_is_ready(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_srt(tmp_path, monkeypatch, RUNS)
    assert main(["verify", "--sandbox", "srt"]) == EXIT_OK
    report = _report(capsys)
    protection = report["protection"]
    assert isinstance(protection, dict)
    assert protection["verifier"].startswith("enforced")
