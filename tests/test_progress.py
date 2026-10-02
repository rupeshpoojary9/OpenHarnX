"""Acceptance tests for live progress (T78, contracts/0006).

From the owner's first real run: `ohx bug new` showed a blank screen until the
agent finished. OpenHarnX must never be silent: it states the limits up front,
shows each agent action as it happens with the elapsed time, and ends with the
time, the cost (unknown when the agent does not report it, never zero) and the
next step. Also covers proposal 13's first step: the Claude-specific launcher
settings live in one adapter definition. Self-contained.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from openharnx.agent import CLAUDE_CODE, agent_profile, launch
from openharnx.cli import EXIT_OK, main

STREAMING_AGENT = r"""
import json, os, sys, time
from pathlib import Path

def emit(event):
    print(json.dumps(event), flush=True)

phase, out = os.environ["OHX_PHASE"], os.environ.get("OHX_OUT", "")
emit({"type": "system", "subtype": "init"})
emit({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Read", "input": {"file_path": "calc.py"}}]}})
time.sleep(float(os.environ.get("FAKE_PAUSE", "0")))
emit({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}})
emit({"type": "assistant", "message": {"content": [
    {"type": "text", "text": "The add function subtracts instead of adding."}]}})
print("some plain line that is not JSON", flush=True)
if phase == "investigate":
    Path(out, "proposal.md").write_text("Cause: calc.py subtracts.\nRule: add(a, b) is a + b.\n")
    Path(out, "test_proposed.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": f"{out}/proposal.md"}}]}})
else:
    Path("calc.py").write_text("def add(a, b):\n    return a + b\n")
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "calc.py"}}]}})
if not os.environ.get("FAKE_NO_RESULT"):
    emit({"type": "result", "subtype": "success", "total_cost_usd": 0.03, "num_turns": 3})
"""

ELAPSED = re.compile(r"^\s*\[\d+:\d\d\] ")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    agent = tmp_path / "agent.py"
    agent.write_text(STREAMING_AGENT)
    (repo / "ohx.toml").write_text(
        f'python = "{sys.executable}"\n\n[agent]\ncommand = ["{sys.executable}", "{agent}"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    return repo


def _lines(out: str) -> list[str]:
    return out.splitlines()


def _index(lines: list[str], *words: str) -> int:
    for i, line in enumerate(lines):
        if all(w in line for w in words):
            return i
    raise AssertionError(f"no line with {words!r} in:\n" + "\n".join(lines))


def test_investigation_states_limits_and_shows_each_action(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["bug", "new", "add is wrong", "--sandbox", "none"]) == EXIT_OK
    lines = _lines(capsys.readouterr().out)
    banner = _index(lines, "investigating", "read-only", "no sandbox", "time limit")
    read = _index(lines, "read", "calc.py")
    run = _index(lines, "run", "pytest -q")
    note = _index(lines, "note", "subtracts instead of adding")
    write = _index(lines, "write", "proposal.md")
    done = _index(lines, "done in", "$0.03")
    proposal = _index(lines, "Rule: add(a, b) is a + b.")
    next_step = _index(lines, "ohx bug approve BUG-001")
    assert banner < read < run < note < write < done < proposal < next_step
    assert all(ELAPSED.match(lines[i]) for i in (read, run, note, write))
    assert not any("some plain line" in x for x in lines)  # raw noise is not shown


def test_unknown_cost_is_shown_as_unknown_not_zero(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_NO_RESULT", "1")
    main(["bug", "new", "add is wrong", "--sandbox", "none"])
    lines = _lines(capsys.readouterr().out)
    done = lines[_index(lines, "done in")]
    assert "cost unknown" in done
    assert "$0.00" not in done


def test_fix_shows_attempts_budget_verification_and_next_step(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["bug", "new", "add is wrong", "--sandbox", "none"])
    main(["bug", "approve", "BUG-001"])
    capsys.readouterr()
    assert main(["bug", "fix", "BUG-001", "--sandbox", "none"]) == EXIT_OK
    lines = _lines(capsys.readouterr().out)
    attempt = _index(lines, "attempt 1 of 2", "budget $2.00")
    edit = _index(lines, "edit", "calc.py")
    done = _index(lines, "done in", "$0.03")
    verifying = _index(lines, "verifying")
    ready = _index(lines, "READY")
    next_step = _index(lines, "Next:", "commit")
    assert attempt < edit < done < verifying < ready < next_step


def test_progress_arrives_while_the_agent_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = tmp_path / "agent.py"
    agent.write_text(STREAMING_AGENT)
    monkeypatch.setenv("FAKE_PAUSE", "1.5")
    out = tmp_path / "out"
    out.mkdir()
    seen: list[tuple[float, str]] = []
    start = time.monotonic()
    run = launch(
        [sys.executable, str(agent)],
        "prompt",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        phase="investigate",
        writable=[out],
        srt=None,
        ohx_home=tmp_path / "home",
        extra_env={"OHX_OUT": str(out)},
        on_event=lambda line: seen.append((time.monotonic() - start, line)),
    )
    total = time.monotonic() - start
    first_read = next(t for t, line in seen if "calc.py" in line)
    assert first_read < total - 1.0  # shown before the agent finished, not at the end
    assert run.cost_usd == pytest.approx(0.03)
    assert b"some plain line" in run.output  # the full output is still recorded


def test_claude_code_is_one_adapter_definition(tmp_path: Path) -> None:
    """Proposal 13: no Claude-specific constants outside the adapter."""
    assert CLAUDE_CODE.command[0] == "claude"
    assert "stream-json" in CLAUDE_CODE.command  # needed for live progress
    profile = agent_profile([tmp_path], tmp_path / "home", tmp_path / "ohx", CLAUDE_CODE)
    network = profile["network"]
    assert isinstance(network, dict)
    assert network["allowedDomains"] == list(CLAUDE_CODE.model_domains)
    filesystem = profile["filesystem"]
    assert isinstance(filesystem, dict)
    config = str(tmp_path / "home" / ".claude" / "settings.json")
    assert config in filesystem["denyWrite"]
