"""Acceptance tests for T77 item 10 (contracts/0011), owner decision 2026-10-01: option A.

Found while fixing item 1: checkers ran with the candidate's own `.venv`, which
is git-ignored and so outside the candidate digest. Replacing the interpreter
or an installed checker there turned BLOCKED into READY.

With `environment = "uv"`, checkers run from an environment OpenHarnX builds
from the accepted `uv.lock` in its own store, which the candidate does not
supply. A changed lockfile is protected material: nothing runs until a
contract revision is accepted. Without it, the report names the blind spot.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
# A plain script, so the environment needs no third-party packages and builds offline.
ACCEPTANCE = "import sys\n\nimport calc\n\nsys.exit(0 if calc.add(2, 3) == 5 else 1)\n"
PYPROJECT = '[project]\nname = "calc"\nversion = "0"\nrequires-python = ">=3.12"\n'
FAKE_PYTHON = "#!/bin/sh\nexit 0\n"
# OpenHarnX does not read the lockfile; uv does. Its content only needs to be stable.
LOCK = 'version = 1\nrequires-python = ">=3.12"\n'
# Stand-in for uv: builds the environment with the standard library, without network.
# uv 0.8 panics inside the macOS sandbox, where these tests run under `ohx verify`.
STAND_IN_UV = f"""#!{sys.executable}
import os, subprocess, sys
args = sys.argv[1:]
assert args[0] == "sync", args
assert {{"--frozen", "--no-install-project", "--no-build"}} <= set(args), args
assert os.path.exists("uv.lock") and "VIRTUAL_ENV" not in os.environ
target = os.environ["UV_PROJECT_ENVIRONMENT"]
subprocess.run([{sys.executable!r}, "-m", "venv", "--without-pip", target], check=True)
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _contract(acceptance: Path, environment: bool) -> str:
    env_line = 'environment = "uv"\n' if environment else ""
    contracts = acceptance.parent.parent / "proj" / "contracts"
    return (
        'title = "Fix add"\nmode = "bugfix"\nchange_summary = "add adds"\n'
        'python = ".venv/bin/python"\n'
        + env_line
        + '\n[[obligations]]\nid = "acceptance"\nkind = "acceptance"\nmandatory = true\n'
        + f"protected = {os.path.relpath(acceptance, contracts)!r}\n"
        + 'command = ["{python}", "{protected}"]\n'
    )


def _make(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: bool = True) -> Path:
    stand_in = tmp_path / "stand-in-uv"
    stand_in.write_text(STAND_IN_UV)
    stand_in.chmod(0o755)
    monkeypatch.setenv("OHX_UV", str(stand_in))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    acceptance = tmp_path / "outside" / "check_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    (repo / "contracts").mkdir(parents=True)
    (repo / "calc.py").write_text(BUGGY)
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "uv.lock").write_text(LOCK)
    (repo / "contracts" / "0001-fix-add.toml").write_text(_contract(acceptance, environment))
    # The candidate's own interpreter, as an agent would leave it: it always succeeds.
    fake = repo / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text(FAKE_PYTHON)
    fake.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
    return repo


def _report(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    main(["report", "--json"])
    report: dict[str, object] = json.loads(capsys.readouterr().out)
    return report


def test_tampered_candidate_interpreter_cannot_pass_buggy_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make(tmp_path, monkeypatch)
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED


def test_fixed_code_is_ready_from_the_protected_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    report = _report(capsys)
    observations = report["observations"]
    assert isinstance(observations, list)
    interpreter = Path(observations[0]["argv"][0])
    assert not interpreter.is_relative_to(repo)
    assert interpreter.is_relative_to(tmp_path / "home")


def test_environment_is_reused_between_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    first = _report(capsys)["observations"]
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    second = _report(capsys)["observations"]
    assert isinstance(first, list) and isinstance(second, list)
    assert first[0]["argv"][0] == second[0]["argv"][0]


def test_changed_lockfile_runs_nothing_and_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "calc.py").write_text(FIXED)
    with open(repo / "uv.lock", "a") as fh:
        fh.write("\n# changed by the agent\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    report = _report(capsys)
    assert report["readiness"] == "unknown"
    observations = report["observations"]
    assert isinstance(observations, list)
    assert all(o["outcome"] == "invalid" for o in observations)
    assert all("uv.lock" in o["note"] for o in observations)


def test_tampered_lockfile_copy_in_the_store_is_an_integrity_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    (copy,) = (tmp_path / "home" / "projects").rglob("protected/*/uv.lock")
    copy.write_text(copy.read_text() + "\n# tampered\n")
    assert main(["report"]) == EXIT_BLOCKED
    assert main(["store", "check"]) == EXIT_BLOCKED


def test_environment_that_cannot_be_built_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "calc.py").write_text(FIXED)
    monkeypatch.setenv("OHX_UV", str(tmp_path / "no-such-uv"))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    report = _report(capsys)
    assert report["readiness"] == "unknown"
    observations = report["observations"]
    assert isinstance(observations, list)
    assert all(o["outcome"] == "unavailable" for o in observations)


def test_accepting_without_a_lockfile_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make(tmp_path, monkeypatch)
    (repo / "uv.lock").unlink()
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) != EXIT_OK


def test_without_a_protected_environment_the_report_names_the_blind_spot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make(tmp_path, monkeypatch, environment=False)
    main(["verify", "--sandbox", "none"])
    limitations = _report(capsys)["limitations"]
    assert isinstance(limitations, list)
    assert any("inside the candidate" in line and ".venv" in line for line in limitations)


def _real_uv_runs_here(tmp_path: Path) -> bool:
    uv = shutil.which("uv")
    if uv is None:
        return False
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "pyproject.toml").write_text(PYPROJECT)
    env = {**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")}
    lock = [uv, "lock", "--offline", "--quiet"]
    return subprocess.run(lock, cwd=probe, env=env, capture_output=True).returncode == 0


def test_real_uv_builds_a_working_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real uv, where it can run; under the macOS sandbox it cannot, and this is skipped."""
    if not _real_uv_runs_here(tmp_path):
        pytest.skip("real uv cannot run here (absent, or inside the macOS sandbox)")
    repo = _make(tmp_path, monkeypatch)
    monkeypatch.delenv("OHX_UV")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    uv = shutil.which("uv")
    assert uv is not None
    # uv inspects a project's .venv even when told which Python to use, and the fixture's
    # is fake, so lock a clean copy of the project. OpenHarnX builds in its own staging copy.
    clean = tmp_path / "clean"
    clean.mkdir()
    shutil.copyfile(repo / "pyproject.toml", clean / "pyproject.toml")
    subprocess.run([uv, "lock", "--offline", "--quiet"], cwd=clean, check=True)
    shutil.copyfile(clean / "uv.lock", repo / "uv.lock")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "real lock")
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    (repo / "calc.py").write_text(FIXED)
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
