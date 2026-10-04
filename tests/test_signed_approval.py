"""Approving intended test changes with an SSH signature, on any platform (T90e,
contracts/0045).

The GitHub label (T90b) works only on GitHub (owner question 2026-10-04: "what if
people are not using GitHub?"). A maintainer runs `ohx approve-tests`: it signs "test
changes approved for commit X" with their SSH key (namespace `openharnx-approval`,
so an evidence signature cannot stand in for it) and stores the signature as a git
note on that commit (`refs/notes/ohx-approvals`), which any git server carries without
changing the commit. `ohx gate` accepts it when the signature verifies for exactly the
judged commit and its key is listed in `approvers` in the base's `ohx.toml`, never the
pull request's; a new push is a new commit and needs a new approval. `--approval-file`
takes the signature from a file for CI that does not fetch notes. A pull request that
changes the approvers is a weakening finding, like any ohx.toml change.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.signing import NAMESPACE

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="no ssh-keygen")

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


def _run(*args: str, cwd: Path | None = None, data: bytes | None = None) -> str:
    out = subprocess.run(args, cwd=cwd, input=data, capture_output=True, check=True)
    return out.stdout.decode().strip()


def _git(repo: Path, *args: str) -> str:
    return _run("git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args)


def _key(tmp_path: Path, name: str) -> Path:
    key = tmp_path / "keys" / name
    key.parent.mkdir(parents=True, exist_ok=True)
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key))
    return key


def _approver_line(name: str, key: Path) -> str:
    return f"{name} {key.with_suffix('.pub').read_text().strip()}"


def _toml(*approvers: str) -> str:
    listed = f"approvers = {list(approvers)!r}\n" if approvers else ""
    return f"python = {sys.executable!r}\n" + listed.replace("'", '"')


@pytest.fixture
def keys(tmp_path: Path) -> dict[str, Path]:
    return {name: _key(tmp_path, name) for name in ("maintainer", "agent", "newcomer")}


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, approvers: str | None) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(_toml(*([approvers] if approvers else [])))
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
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


REMOVAL = {"calc.py": WITHOUT_OLD, "tests/test_calc.py": SUITE_WITHOUT_OLD}


def _approve(monkeypatch: pytest.MonkeyPatch, key: Path, *extra: str) -> int:
    monkeypatch.setenv("OHX_SIGNING_KEY", str(key))
    return main(["approve-tests", *extra])


def _gate(tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any], str]:
    out = tmp_path / "gate-out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out), *extra])
    report: dict[str, Any] = json.loads((out / "report.json").read_text())
    return code, report, (out / "report.md").read_text()


def test_a_listed_maintainer_signs_and_the_gate_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    head = _change(repo, REMOVAL)
    assert _gate(tmp_path)[0] != EXIT_OK  # blocked before the approval
    assert _approve(monkeypatch, keys["maintainer"]) == EXIT_OK
    note = _git(repo, "notes", "--ref=ohx-approvals", "show", head)
    assert "BEGIN SSH SIGNATURE" in note
    code, report, markdown = _gate(tmp_path)
    assert code == EXIT_OK, markdown
    assert report["approval"]["method"] == "signature"
    assert report["approval"]["by"] == "maintainer"
    assert report["approval"]["head"] == head
    assert report["approval"]["key"].startswith("SHA256:")
    assert "maintainer" in markdown and "SSH signature" in markdown


def test_a_key_not_listed_on_the_base_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    _change(repo, REMOVAL)
    _approve(monkeypatch, keys["agent"])
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "not listed" in report["approval"]["refused"]


def test_approvers_added_by_the_pull_request_do_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, None)
    _change(repo, {**REMOVAL, "ohx.toml": _toml(_approver_line("agent", keys["agent"]))})
    _approve(monkeypatch, keys["agent"])
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "approvers" in report["approval"]["refused"]


def test_changing_the_approvers_in_a_pull_request_is_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    both = (
        _approver_line("maintainer", keys["maintainer"]),
        _approver_line("agent", keys["agent"]),
    )
    _change(repo, {"ohx.toml": _toml(*both)})
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK
    notes = " ".join(o["note"] for o in report["observations"])
    assert "ohx.toml" in notes


def test_a_push_after_the_approval_needs_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    _change(repo, REMOVAL)
    _approve(monkeypatch, keys["maintainer"])
    _change(repo, {"notes.txt": "more\n"})
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "approval" not in report


def test_a_signature_for_another_commit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    first = _change(repo, REMOVAL)
    _approve(monkeypatch, keys["maintainer"])
    head = _change(repo, {"notes.txt": "more\n"})
    signature = _git(repo, "notes", "--ref=ohx-approvals", "show", first)
    _git(repo, "notes", "--ref=ohx-approvals", "add", "-m", signature, head)  # copied over
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "does not verify" in report["approval"]["refused"]


def test_an_evidence_signature_cannot_stand_in_for_an_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    head = _change(repo, REMOVAL)
    message = f"openharnx test changes approved\ncommit {head}\n".encode()
    other = _run(
        "ssh-keygen", "-Y", "sign", "-n", NAMESPACE, "-f", str(keys["maintainer"]), data=message
    )
    _git(repo, "notes", "--ref=ohx-approvals", "add", "-m", other, head)
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "does not verify" in report["approval"]["refused"]


def test_a_signature_file_works_where_notes_are_not_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    _change(repo, REMOVAL)
    signature = tmp_path / "approval.sig"
    assert _approve(monkeypatch, keys["maintainer"], "--out", str(signature)) == EXIT_OK
    assert "BEGIN SSH SIGNATURE" in signature.read_text()
    _git(repo, "notes", "--ref=ohx-approvals", "remove", "--ignore-missing", "HEAD")
    code, report, _ = _gate(tmp_path, "--approval-file", str(signature))
    assert code == EXIT_OK and report["approval"]["by"] == "maintainer"


def test_approved_a_test_that_still_exists_must_still_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    broken = "def add(a, b):\n    return a - b\n"
    _change(repo, {"calc.py": broken, "tests/test_calc.py": SUITE_WITHOUT_OLD})
    _approve(monkeypatch, keys["maintainer"])
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and report["approval"]["by"] == "maintainer"


def test_approve_tests_names_the_commit_and_how_to_share_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keys: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    head = _change(repo, REMOVAL)
    assert _approve(monkeypatch, keys["maintainer"]) == EXIT_OK
    out = capsys.readouterr().out
    assert head[:12] in out and "git push origin refs/notes/ohx-approvals" in out


def test_approve_tests_without_a_key_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path, monkeypatch, None)
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    assert main(["approve-tests"]) != EXIT_OK
    assert "key" in capsys.readouterr().err.lower()


def test_no_note_and_no_label_means_no_approval_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    repo = _repo(tmp_path, monkeypatch, _approver_line("maintainer", keys["maintainer"]))
    _change(repo, REMOVAL)
    code, report, _ = _gate(tmp_path)
    assert code != EXIT_OK and "approval" not in report


def test_baselines_from_before_ohx_toml_was_configuration_judge_as_they_did(
    tmp_path: Path,
) -> None:
    from openharnx.weakening import compare, snapshot

    (tmp_path / "ohx.toml").write_text('python = "a"\n')
    old = {**snapshot(tmp_path, ["ohx.toml"]), "version": 5, "config": {}}  # as recorded then
    (tmp_path / "ohx.toml").write_text('python = "b"\n')
    assert compare(old, snapshot(tmp_path, ["ohx.toml"])) == []
    new = snapshot(tmp_path, ["ohx.toml"])
    (tmp_path / "ohx.toml").write_text('python = "c"\n')
    assert compare(new, snapshot(tmp_path, ["ohx.toml"])) == [
        "ohx.toml: check configuration changed since acceptance"
    ]


def test_the_action_fetches_signed_approvals() -> None:
    action = (Path.cwd() / "action.yml").read_text()  # the locked copy runs outside the repo
    assert "refs/notes/ohx-approvals" in action.split("- name: Run the gate", 1)[1]


def test_an_approver_listed_without_a_key_comment_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys: dict[str, Path]
) -> None:
    kind, body = keys["maintainer"].with_suffix(".pub").read_text().split()[:2]
    repo = _repo(tmp_path, monkeypatch, f"maintainer {kind} {body}")  # as in the docs
    _change(repo, REMOVAL)
    _approve(monkeypatch, keys["maintainer"])
    code, report, _ = _gate(tmp_path)
    assert code == EXIT_OK and report["approval"]["by"] == "maintainer"
