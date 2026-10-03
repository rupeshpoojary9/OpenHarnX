"""Acceptance tests for signed evidence (T87 item 4, threat T7, contracts/0019).

Before this, the hash chain caught an edit to one record, but anyone who could
write the store could rebuild the whole chain and it would check as valid; and
"approved by" was only what git's configuration said. The owner chose (2026-10-03)
to sign with their own SSH key, so a signature proves the records came from the
holder of that key and can be checked against the keys on their GitHub profile.
Signing in CI (Sigstore) is planned in T79.

Every command that writes evidence ends by signing the head of the hash chain
with `ssh-keygen -Y sign` (namespace `openharnx`); one signature covers every
record before it. `ohx store check` verifies every signature and names the
signer, `--signer` pins the expected key, and the report says whether it is
signed. Self-contained: a throwaway key is generated per test.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from openharnx.cli import EXIT_OK, main
from openharnx.kernel.canonical import digest
from openharnx.store import GENESIS, _event_hash

ACCEPTANCE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="no ssh-keygen")


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


def _key(tmp_path: Path, name: str) -> Path:
    key = tmp_path / "keys" / name
    key.parent.mkdir(exist_ok=True)
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key))
    return key.with_suffix(".pub")


def _fingerprint(pub: Path) -> str:
    out = subprocess.run(["ssh-keygen", "-lf", str(pub)], capture_output=True, text=True)
    return out.stdout.split()[1]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    for args in (["init", "-q"], ["config", "user.name", "Test Owner"]):
        _run("git", *args, cwd=repo)
    _run("git", "config", "user.email", "owner@example.com", cwd=repo)
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-qm", "base", cwd=repo)
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", str(_key(tmp_path, "owner")))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept", "--sandbox", "none"]) == 0
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    return repo


def _check(capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    capsys.readouterr()
    code = main(["store", "check", *extra])
    return code, capsys.readouterr().out


def _rebuild(tmp_path: Path, mutate: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
    """What an attacker with write access can do: rewrite records and recompute the chain."""
    (store,) = (tmp_path / "home" / "projects").glob("*/store.sqlite")
    db = sqlite3.connect(store)
    rows = db.execute(
        "SELECT e.seq, e.event_id, e.idempotency_key, e.entity_type, e.entity_id,"
        " e.revision_id, e.recorded_at, r.body FROM events e"
        " JOIN revisions r ON r.revision_id = e.revision_id ORDER BY e.seq"
    ).fetchall()
    prev = GENESIS
    for seq, eid, key, etype, entid, rid, at, body in rows:
        new_body = mutate(etype, json.loads(body))
        cdig = digest(new_body)
        event = {
            "event_id": eid,
            "idempotency_key": key,
            "entity_type": etype,
            "entity_id": entid,
            "revision_id": rid,
            "content_digest": cdig,
            "recorded_at": at,
        }
        h = _event_hash(prev, event)
        db.execute(
            "UPDATE revisions SET body = ?, content_digest = ? WHERE revision_id = ?",
            (json.dumps(new_body), cdig, rid),
        )
        db.execute(
            "UPDATE events SET content_digest = ?, prev_hash = ?, hash = ? WHERE seq = ?",
            (cdig, prev, h, seq),
        )
        prev = h
    db.commit()
    db.close()


def _retitle(etype: str, body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "title": "Something else"} if etype == "contract" else body


def test_evidence_is_signed_and_names_the_signer(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _check(capsys)
    assert code == EXIT_OK, out
    assert _fingerprint(tmp_path / "keys" / "owner.pub") in out
    assert "Test Owner" in out
    assert "0 unsigned" in out


def test_the_report_says_it_is_signed(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    main(["report", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["signature"]["status"] == "signed"
    assert report["signature"]["fingerprint"] == _fingerprint(tmp_path / "keys" / "owner.pub")


def test_a_rebuilt_chain_breaks_the_signature(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _rebuild(tmp_path, _retitle)
    code, out = _check(capsys)
    assert code != EXIT_OK
    assert "signature" in out
    capsys.readouterr()
    main(["report", "--json"])
    assert json.loads(capsys.readouterr().out)["readiness"] == "invalid"


def test_a_chain_re_signed_with_another_key_fails_the_pinned_signer(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = tmp_path / "keys" / "owner.pub"
    _rebuild(tmp_path, lambda t, b: _retitle(t, b) if t != "signature" else b)
    # The attacker drops the owner's signatures and signs the rebuilt chain with their own key.
    (store,) = (tmp_path / "home" / "projects").glob("*/store.sqlite")
    db = sqlite3.connect(store)
    db.execute("DELETE FROM events WHERE entity_type = 'signature'")
    db.commit()
    db.close()
    _rebuild(tmp_path, lambda t, b: b)
    monkeypatch.setenv("OHX_SIGNING_KEY", str(_key(tmp_path, "attacker")))
    main(["verify", "--sandbox", "none"])
    code, out = _check(capsys)
    assert code == EXIT_OK  # internally consistent, but signed by someone else
    assert _fingerprint(owner) not in out
    code, out = _check(capsys, "--signer", str(owner))
    assert code != EXIT_OK
    assert "not signed by" in out or "signed by an unexpected key" in out


def test_without_a_key_commands_work_and_records_show_as_unsigned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n")
    _run("git", "init", "-q", cwd=repo)
    _run("git", "add", "-A", cwd=repo)
    _run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b", cwd=repo)
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home2"))
    monkeypatch.setenv("OHX_SIGNING_KEY", str(tmp_path / "no-such-key.pub"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert "not signed" in capsys.readouterr().err
    code, out = _check(capsys)
    assert code == EXIT_OK
    assert "1 unsigned" in out
