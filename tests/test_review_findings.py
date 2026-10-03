"""Acceptance tests for four findings of an external review (2026-10-03, contracts/0030).

1. The GitHub Action read the report with `python3 -c` from the candidate folder, so a
   pull request's `json.py` ran with the workflow step's access, outside the sandbox.
   The same trap was in the protected environment's set-up (`sysconfig.py`).
2. A gate in which no test was collected (exit 5 on both sides) was READY: two empty
   per-test result sets compared as equal.
3. `ohx store check --signer` checked only the signatures that remained: removing them,
   editing a record and rebuilding the chain passed.
4. An agent that timed out was killed, but its children kept running and kept the
   output pipe open, so the launcher stayed blocked.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from openharnx.agent import launch
from openharnx.cli import EXIT_OK, main
from openharnx.environment import ensure
from openharnx.kernel.canonical import digest
from openharnx.regression import baseline, compare
from openharnx.store import GENESIS, _event_hash

ROOT = Path.cwd()  # the checker runs in the candidate


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


# --- 1. orchestration never imports from the candidate ------------------------------------

SHADOW = "import os\nopen(os.environ['SHADOW_MARKER'], 'a').write('{name} ran\\n')\n"


def _gate_step() -> str:
    """The `Run the gate` script from action.yml, as GitHub runs it."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    step = text.split("- name: Run the gate", 1)[1]
    script = step.split("run: |\n", 1)[1]
    lines = []
    for line in script.splitlines():
        if line.strip() and not line.startswith("        "):
            break
        lines.append(line[8:])
    return "\n".join(lines) + "\n"


def test_the_action_never_imports_the_candidates_modules(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for name in ("json", "sys", "os"):
        (candidate / f"{name}.py").write_text(SHADOW.format(name=name))
    _git(candidate, "init", "-q")
    _git(candidate, "add", "-A")
    _git(candidate, "commit", "-qm", "base")
    runner = tmp_path / "runner"
    fake = runner / "ohx" / "bin" / "ohx"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = --out ] && out=$2; shift; done\n'
        'mkdir -p "$out"; echo \'{"readiness": "blocked"}\' > "$out/report.json"; exit 10\n'
    )
    fake.chmod(0o755)
    marker, outputs = tmp_path / "marker", tmp_path / "outputs"
    outputs.write_text("")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(runner),
        "GITHUB_OUTPUT": str(outputs),
        "OHX_BASE": _git(candidate, "rev-parse", "HEAD"),
        "OHX_SANDBOX": "srt",
        "OHX_OUT": str(tmp_path / "out"),
        "SHADOW_MARKER": str(marker),
    }
    proc = subprocess.run(
        ["bash", "-e", "-c", _gate_step()], cwd=candidate, env=env, capture_output=True, text=True
    )
    assert proc.returncode == 10, proc.stderr
    assert not marker.exists(), marker.read_text()
    assert "readiness=blocked" in outputs.read_text()


STAND_IN_UV = f"""#!{sys.executable}
import os, subprocess
target = os.environ["UV_PROJECT_ENVIRONMENT"]
subprocess.run([{sys.executable!r}, "-m", "venv", "--without-pip", target], check=True)
"""


def test_building_the_protected_environment_never_imports_the_candidates_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uv = tmp_path / "stand-in-uv"
    uv.write_text(STAND_IN_UV)
    uv.chmod(0o755)
    monkeypatch.setenv("OHX_UV", str(uv))
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "uv.lock").write_text("version = 1\n")
    (candidate / "sysconfig.py").write_text(SHADOW.format(name="sysconfig"))
    marker = tmp_path / "marker"
    monkeypatch.setenv("SHADOW_MARKER", str(marker))
    monkeypatch.chdir(candidate)  # where `ohx verify` and `ohx gate` run
    env = ensure(tmp_path / "envs", candidate / "uv.lock", candidate)
    assert env.python.exists()
    assert not marker.exists(), marker.read_text()


# --- 2. no tests is never evidence -------------------------------------------------------


@pytest.mark.parametrize("outcome", ["invalid", "pass", "fail"])
def test_empty_per_test_results_are_never_a_pass(outcome: str) -> None:
    result, note = compare(baseline(outcome, {}), outcome, {})
    assert result != "pass", note


def test_a_suite_that_did_not_run_properly_is_not_compared_test_by_test() -> None:
    before = baseline("pass", {"t::a": "pass"})
    assert compare(before, "invalid", {"t::a": "pass"})[0] == "fail"
    assert compare(before, "crash", {"t::a": "pass"})[0] == "fail"
    assert compare(baseline("invalid", {"t::a": "pass"}), "pass", {"t::a": "pass"})[0] != "pass"


def test_a_gate_where_no_test_is_collected_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests" / "test_calc.py").write_text("from calc import add\n")  # no tests
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "pr")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    _git(repo, "commit", "-qam", "break add")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    out = tmp_path / "out"
    code = main(["gate", "--base", "main", "--sandbox", "none", "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert code != EXIT_OK and report["readiness"] != "ready"


# --- 3. a pinned signer must cover the store ----------------------------------------------

needs_ssh = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="no ssh-keygen")


def _signed_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acceptance = tmp_path / "outside" / "test_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    key = tmp_path / "keys" / "owner"
    key.parent.mkdir()
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "owner", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", str(key) + ".pub")
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    new = ["contract", "new", "--title", "Add", "--summary", "add adds"]
    assert main([*new, "--acceptance", str(acceptance), "--accept", "--sandbox", "none"]) == 0
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    return key.with_suffix(".pub")


def _strip_signatures_and_rewrite(tmp_path: Path) -> None:
    """Delete every signature, change who accepted the contract, rebuild the chain."""
    (store,) = (tmp_path / "home" / "projects").glob("*/store.sqlite")
    db = sqlite3.connect(store)
    db.execute(
        "DELETE FROM revisions WHERE revision_id IN"
        " (SELECT revision_id FROM events WHERE entity_type = 'signature')"
    )
    db.execute("DELETE FROM events WHERE entity_type = 'signature'")
    rows = db.execute(
        "SELECT e.seq, e.event_id, e.idempotency_key, e.entity_type, e.entity_id,"
        " e.revision_id, e.recorded_at, r.body FROM events e"
        " JOIN revisions r ON r.revision_id = e.revision_id ORDER BY e.seq"
    ).fetchall()
    prev = GENESIS
    for seq, eid, key, etype, entid, rid, at, body in rows:
        new_body: dict[str, Any] = json.loads(body)
        if etype == "contract":
            new_body["accepted_by"] = {"name": "Someone Else", "email": "x@example.com"}
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


@needs_ssh
def test_a_pinned_signer_fails_when_signatures_were_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pub = _signed_store(tmp_path, monkeypatch)
    capsys.readouterr()
    assert main(["store", "check", "--signer", str(pub)]) == EXIT_OK  # control
    _strip_signatures_and_rewrite(tmp_path)
    capsys.readouterr()
    assert main(["store", "check", "--signer", str(pub)]) != EXIT_OK
    assert "not signed" in capsys.readouterr().out


@needs_ssh
def test_a_pinned_signer_fails_when_records_follow_the_last_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pub = _signed_store(tmp_path, monkeypatch)
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK  # evidence the owner did not sign
    capsys.readouterr()
    assert main(["store", "check", "--signer", str(pub)]) != EXIT_OK
    assert re.search(r"\d+ record\(s\) .*not signed", capsys.readouterr().out)


# --- 4. a timed-out agent leaves nothing running -----------------------------------------


def _launch(tmp_path: Path, script: str) -> tuple[float, int | None]:
    start = time.monotonic()
    run = launch(
        ["sh", "-c", script],
        "prompt",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        phase="fix",
        writable=[],
        srt=None,
        ohx_home=tmp_path / "home",
        extra_env={},
        timeout_s=1,
    )
    return time.monotonic() - start, run.exit_code


def test_a_timed_out_agent_and_its_children_are_stopped(tmp_path: Path) -> None:
    beat = tmp_path / "beat"
    # The child holds the output pipe but never writes to it, so only being stopped ends it.
    loop = f"for i in $(seq 200); do date +%s >> {beat}; sleep 0.05; done"
    took, code = _launch(tmp_path, f"({loop}) &\nsleep 30\n")
    assert code is None  # timed out
    assert took < 2.5, took  # stopped at once, not when the pipes were given up on
    time.sleep(0.3)
    size = beat.stat().st_size
    time.sleep(0.5)
    assert beat.stat().st_size == size, "a child of the agent is still running"


def test_a_child_that_leaves_the_group_cannot_block_the_launcher(tmp_path: Path) -> None:
    pid_file = tmp_path / "escaped"
    escape = (
        f"{sys.executable} -c 'import os, time; os.setsid();"
        f' open("{pid_file}", "w").write(str(os.getpid())); time.sleep(8)\' &\n'
    )
    took, code = _launch(tmp_path, escape + "sleep 30\n")
    try:
        assert code is None
        assert took < 5, took  # the pipes are let go after the drain time
    finally:
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)


def test_an_agent_that_finishes_keeps_its_exit_code_and_all_its_output(tmp_path: Path) -> None:
    script = "sleep 0.5\nfor i in $(seq 500); do echo line-$i; done\necho to-stderr >&2\nexit 3\n"
    start = time.monotonic()
    run = launch(
        ["sh", "-c", script],
        "prompt",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        phase="fix",
        writable=[],
        srt=None,
        ohx_home=tmp_path / "home",
        extra_env={},
        timeout_s=30,
    )
    assert run.exit_code == 3  # not a timeout
    assert time.monotonic() - start < 5
    lines = run.output.decode().split()
    assert [x for x in lines if x.startswith("line-")] == [f"line-{i}" for i in range(1, 501)]
    assert "to-stderr" in lines
