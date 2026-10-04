"""A maintainer approves intended test changes on a pull request with a label (T90b,
contracts/0043).

Found by replaying the gate over 29 Copilot pull requests of github/spec-kit
(2026-10-04): 7 of 20 merged ones changed or removed existing tests on purpose (a
flag removed with its tests, a feature rewritten), and the gate had no way to accept
that. Now a maintainer adds the `ohx-approve-tests` label (owner decision 2026-10-04).

The approval counts only when: the label is on the pull request; whoever added it last
can write to the repository; and when it was added, the pull request's latest pushed
commit was the one being judged (from GitHub's own workflow run records, which a commit
date cannot fake). A push after the label needs the label again. Approved, the base's
locked tests no longer bind: the pull request's own tests must pass, a test that passed
on the base and still exists must still pass, and new failures still block. Every
approved finding stays in the report with who approved it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.app import approval
from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n\n\ndef old(a):\n    return a\n"
SUITE = """\
from calc import add, old


def test_add():
    assert add(2, 3) == 5


def test_old():
    assert old(1) == 1
"""
WITHOUT_OLD = "def add(a, b):\n    return a + b\n"
SUITE_WITHOUT_OLD = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"

REPO = "acme/calc"
HEAD_REPO = "acme/calc"
WRITER = "maintainer"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


class FakeGitHub:
    """The GitHub REST API as the approval check reads it."""

    def __init__(self, head: str) -> None:
        self.head = head
        self.events: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.permissions = {WRITER: "write", "owner": "admin", "triager": "read"}
        self.fail = False

    def label(self, action: str, by: str, at: str, name: str = "ohx-approve-tests") -> None:
        self.events.append(
            {
                "id": len(self.events) + 1,
                "event": action,
                "actor": {"login": by},
                "label": {"name": name},
                "created_at": at,
            }
        )

    def run(self, sha: str, at: str, repo: str = HEAD_REPO) -> None:
        self.runs.append(
            {"head_sha": sha, "created_at": at, "head_repository": {"full_name": repo}}
        )

    def get(self, url: str, token: str) -> Any:
        assert token == "tok"
        if self.fail:
            raise approval.ApiError("HTTP 403 for events")
        if "/issues/7/events" in url:
            page = int(re.search(r"[?&]page=(\d+)", url).group(1))  # type: ignore[union-attr]
            return self.events if page == 1 else []
        if "/collaborators/" in url:
            user = url.split("/collaborators/")[1].split("/")[0]
            return {"permission": self.permissions.get(user, "none")}
        if "/actions/runs" in url:
            assert "branch=feature" in url and "event=pull_request" in url
            page = int(re.search(r"[?&]page=(\d+)", url).group(1))  # type: ignore[union-attr]
            ordered = sorted(self.runs, key=lambda r: r["created_at"], reverse=True)
            return {"workflow_runs": ordered if page == 1 else []}
        raise AssertionError(url)


def _event(tmp_path: Path, head: str) -> Path:
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps(
            {
                "action": "labeled",
                "pull_request": {
                    "number": 7,
                    "head": {"sha": head, "ref": "feature", "repo": {"full_name": HEAD_REPO}},
                },
            }
        )
    )
    return path


def _environ(tmp_path: Path, head: str) -> dict[str, str]:
    return {
        "GITHUB_EVENT_PATH": str(_event(tmp_path, head)),
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_API_URL": "https://api.example",
        approval.TOKEN_ENV: "tok",
    }


HEAD = "a" * 40
OLDER = "b" * 40


def _approve(tmp_path: Path, gh: FakeGitHub, head: str = HEAD) -> approval.Result:
    return approval.github_approval("ohx-approve-tests", head, _environ(tmp_path, head), get=gh.get)


def test_a_writer_labelling_the_latest_push_approves(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(OLDER, "2026-10-04T09:00:00Z")
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z")
    result = _approve(tmp_path, gh)
    assert result.approved is not None and result.refused == ""
    assert result.approved.by == WRITER
    assert result.approved.at == "2026-10-04T10:05:00Z"
    assert result.approved.head == HEAD


def test_no_label_is_no_approval(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z", name="documentation")
    result = _approve(tmp_path, gh)
    assert result.approved is None and "ohx-approve-tests" in result.refused


def test_a_removed_label_is_no_approval(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z")
    gh.label("unlabeled", WRITER, "2026-10-04T10:06:00Z")
    assert _approve(tmp_path, gh).approved is None


def test_the_last_labeller_counts(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z")
    gh.label("unlabeled", "triager", "2026-10-04T10:06:00Z")
    gh.label("labeled", "triager", "2026-10-04T10:07:00Z")
    result = _approve(tmp_path, gh)
    assert result.approved is None and "@triager" in result.refused


@pytest.mark.parametrize("who", ["triager", "copilot-swe-agent", "someone"])
def test_only_people_who_can_write_approve(tmp_path: Path, who: str) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", who, "2026-10-04T10:05:00Z")
    result = _approve(tmp_path, gh)
    assert result.approved is None and "write" in result.refused


def test_an_admin_approves(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", "owner", "2026-10-04T10:05:00Z")
    assert _approve(tmp_path, gh).approved is not None


def test_a_push_after_the_label_needs_the_label_again(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(OLDER, "2026-10-04T09:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T09:05:00Z")  # approved the older commit
    gh.run(HEAD, "2026-10-04T10:00:00Z")  # then the agent pushed again
    result = _approve(tmp_path, gh)
    assert result.approved is None
    assert OLDER[:12] in result.refused and "again" in result.refused


def test_runs_from_a_fork_with_the_same_branch_name_do_not_count(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(OLDER, "2026-10-04T09:00:00Z")
    gh.run(HEAD, "2026-10-04T09:30:00Z", repo="mallory/calc")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z")
    assert _approve(tmp_path, gh).approved is None


def test_without_any_run_before_the_label_nothing_is_approved(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.label("labeled", WRITER, "2026-10-04T09:05:00Z")
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    assert _approve(tmp_path, gh).approved is None


def test_the_judged_commit_must_be_the_pull_request_head(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.run(HEAD, "2026-10-04T10:00:00Z")
    gh.label("labeled", WRITER, "2026-10-04T10:05:00Z")
    environ = _environ(tmp_path, HEAD)
    result = approval.github_approval("ohx-approve-tests", OLDER, environ, get=gh.get)
    assert result.approved is None and "head" in result.refused


@pytest.mark.parametrize("missing", ["GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", "OHX_GITHUB_TOKEN"])
def test_missing_context_is_a_reason_not_a_crash(tmp_path: Path, missing: str) -> None:
    environ = _environ(tmp_path, HEAD)
    del environ[missing]
    result = approval.github_approval("ohx-approve-tests", HEAD, environ, get=FakeGitHub(HEAD).get)
    assert result.approved is None and result.refused


def test_an_api_error_is_a_reason_not_a_crash(tmp_path: Path) -> None:
    gh = FakeGitHub(HEAD)
    gh.fail = True
    result = _approve(tmp_path, gh)
    assert result.approved is None and "403" in result.refused


# The gate with an approval: the pull request removes a function and its test on purpose.


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _change(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


def _github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head: str, by: str = WRITER
) -> FakeGitHub:
    gh = FakeGitHub(head)
    gh.run(head, "2026-10-04T10:00:00Z")
    gh.label("labeled", by, "2026-10-04T10:05:00Z")
    for key, value in _environ(tmp_path, head).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(approval, "_get", gh.get)
    return gh


def _gate(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any], str]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out), *extra])
    report: dict[str, Any] = json.loads((out / "report.json").read_text())
    return code, report, (out / "report.md").read_text()


LABEL = ("--approve-tests-label", "ohx-approve-tests")


def test_removing_a_tested_function_on_purpose_is_blocked_without_approval(
    repo: Path, tmp_path: Path
) -> None:
    _change(repo, {"calc.py": WITHOUT_OLD, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "approval" not in report


def test_an_approved_removal_is_ready_and_says_who_approved(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _change(repo, {"calc.py": WITHOUT_OLD, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    _github(tmp_path, monkeypatch, head)
    code, report, markdown = _gate(tmp_path, *LABEL)
    assert code == EXIT_OK, markdown
    assert report["approval"]["by"] == WRITER
    assert report["approval"]["head"] == head
    notes = " ".join(o["note"] for o in report["observations"])
    assert "fewer tests" in notes and f"approved by @{WRITER}" in notes
    assert f"@{WRITER}" in markdown and "ohx-approve-tests" in markdown


def test_approved_a_test_that_still_exists_must_still_pass(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = "def add(a, b):\n    return a - b\n"
    head = _change(repo, {"calc.py": broken, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    _github(tmp_path, monkeypatch, head)
    code, report, _ = _gate(tmp_path, *LABEL)
    assert code != EXIT_OK and report["approval"]["by"] == WRITER


def test_approved_a_new_failing_test_still_blocks(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = SUITE_WITHOUT_OLD + "\n\ndef test_new():\n    assert add(1, 1) == 3\n"
    head = _change(repo, {"calc.py": WITHOUT_OLD, "tests/test_calc.py": failing})
    _github(tmp_path, monkeypatch, head)
    code, _, _ = _gate(tmp_path, *LABEL)
    assert code != EXIT_OK


def test_a_refused_approval_changes_nothing_and_says_why(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _change(repo, {"calc.py": WITHOUT_OLD, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    _github(tmp_path, monkeypatch, head, by="triager")
    code, report, markdown = _gate(tmp_path, *LABEL)
    assert code != EXIT_OK
    assert "write" in report["approval"]["refused"]
    assert "not approved" in markdown.lower()


def test_without_the_option_no_approval_is_looked_up(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _change(repo, {"calc.py": WITHOUT_OLD, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    gh = _github(tmp_path, monkeypatch, head)
    gh.fail = True  # any lookup would show up as a refusal
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "approval" not in report


# The workflow and the Action.

ROOT = Path.cwd()  # the locked copy runs outside the repository


def test_the_workflow_reruns_when_the_label_changes_and_can_read_what_it_needs() -> None:
    text = (ROOT / ".github" / "workflows" / "gate.yml").read_text()
    on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "labeled" in on and "unlabeled" in on and "synchronize" in on
    top = text.split("\njobs:\n", 1)[0]
    for permission in ("contents: read", "actions: read", "pull-requests: read"):
        assert f"\n  {permission}\n" in top
    assert "ohx-approve-tests" in text


def test_the_action_gives_the_token_to_the_gate_only() -> None:
    text = (ROOT / "action.yml").read_text()
    assert "approve-tests-label" in text and "ohx-approve-tests" in text
    run = text.split("- name: Run the gate", 1)[1]
    assert "OHX_GITHUB_TOKEN:" in run and "--approve-tests-label" in run
    assert "OHX_GITHUB_TOKEN" not in text.split("- name: Run the gate", 1)[0]
