"""Acceptance tests for the CI trust boundary (T79, RC-18 and RC-19, contracts/0027).

RC-18: pull request code runs only on throwaway GitHub-hosted runners, with no
privileged trigger, no shared caches and a time limit on every job.
RC-19: the verdict is published as the job's exit code, its summary and an
artifact. No job may post comments or statuses with a write token, and the
code under review must not be able to reach the files the runner reads back
between steps (`GITHUB_ENV`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`): a line
in `GITHUB_ENV` would set variables for every later step, a line in
`GITHUB_OUTPUT` could forge the verdict.

Owner decisions 2026-10-03: no pull request comment for now; approval for
outside contributors' workflows is set to "all outside collaborators" when the
repository goes public (a repository setting, outside this file's reach).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
WORKFLOW = Path.cwd() / ".github" / "workflows" / "gate.yml"
RUNNER_FILES = ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_PATH")
MARKER = "INJECTED_BY_CANDIDATE"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _jobs() -> list[str]:
    jobs = _text().split("\njobs:\n", 1)[1]
    return [p for p in re.split(r"\n  (?=[a-z][\w-]*:\n)", "\n" + jobs) if p.strip()]


def test_only_the_unprivileged_pull_request_trigger_is_used() -> None:
    on = _text().split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.fullmatch(r"\s*pull_request:\s*", on), on
    assert "pull_request_target" not in _text()
    assert "workflow_run" not in _text()


def test_every_job_runs_on_a_github_hosted_runner_with_a_time_limit() -> None:
    jobs = _jobs()
    assert len(jobs) >= 2
    for job in jobs:
        runs_on = re.findall(r"runs-on:\s*(\S+)", job)
        assert runs_on and all(re.fullmatch(r"ubuntu-\d\d\.\d\d", r) for r in runs_on), job
        assert re.search(r"timeout-minutes:\s*\d+", job), job
    assert "self-hosted" not in _text()


def test_no_shared_caches() -> None:
    text = _text()
    assert "actions/cache" not in text
    assert not re.search(r"^\s+cache:", text, re.M)


def test_no_job_can_post_comments_statuses_or_push() -> None:
    text = _text()
    for scope in ("pull-requests", "issues", "statuses", "checks", "contents", "actions"):
        assert f"{scope}: write" not in text, scope
    assert "write-all" not in text


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _candidate(tmp_path: Path, test: str) -> Path:
    """A repository whose pull request adds `test` next to a passing base suite."""
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    (repo / "tests" / "test_reach.py").write_text(test)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return repo


def _runner_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stand-ins for the files the runner gives a step, outside every run folder."""
    folder = tmp_path / "_runner_file_commands"
    folder.mkdir()
    files = {}
    for name in RUNNER_FILES:
        path = folder / name.lower()
        path.write_text("")
        monkeypatch.setenv(name, str(path))
        files[name] = path
    return files


def _gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path, sandbox: str) -> int:
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.chdir(repo)
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", sandbox, "--out", str(out)])
    assert json.loads((out / "report.json").read_text())["readiness"]
    return code


def test_the_code_under_review_sees_none_of_the_runner_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "not-a-real-token")
    test = (
        "import os\n\nPREFIXES = ('GITHUB_', 'ACTIONS_', 'RUNNER_')\n\n\n"
        "def test_no_runner_variables():\n"
        "    assert sorted(k for k in os.environ if k.startswith(PREFIXES)) == []\n"
    )
    repo = _candidate(tmp_path, test)
    _runner_files(tmp_path, monkeypatch)
    assert _gate(tmp_path, monkeypatch, repo, "none") == EXIT_OK


def _writer(tmp_path: Path) -> str:
    """A test that tries to append to each runner file and passes either way."""
    folder = tmp_path / "_runner_file_commands"
    paths = [str(folder / name.lower()) for name in RUNNER_FILES]
    return (
        f"PATHS = {paths!r}\n\n\ndef test_try_to_write_the_runner_files():\n"
        "    for path in PATHS:\n"
        "        try:\n"
        "            with open(path, 'a') as handle:\n"
        f"                handle.write('{MARKER}=1\\n')\n"
        "        except OSError:\n"
        "            pass\n"
    )


def test_control_without_the_sandbox_the_runner_files_are_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _candidate(tmp_path, _writer(tmp_path))
    files = _runner_files(tmp_path, monkeypatch)
    _gate(tmp_path, monkeypatch, repo, "none")
    assert MARKER in files["GITHUB_ENV"].read_text()  # the attack is real


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_the_code_under_review_cannot_write_the_runner_files_under_srt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _candidate(tmp_path, _writer(tmp_path))
    files = _runner_files(tmp_path, monkeypatch)
    assert _gate(tmp_path, monkeypatch, repo, "srt") == EXIT_OK  # the writer ran
    for name, path in files.items():
        assert MARKER not in path.read_text(), name
