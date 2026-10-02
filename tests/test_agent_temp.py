"""Acceptance tests for the agent's own temp directory (T78 follow-up, contracts/0013).

From the first real `ohx bug` run with Claude Code (2026-10-02): every Bash
call failed inside the srt sandbox with "EPERM: operation not permitted,
mkdir '/private/tmp/claude-501/...'". Claude Code keeps its shell state in a
per-user directory under /tmp, not in TMPDIR, and the sandbox does not let it
write there. The agent could only read files, and in `ohx bug fix` it could
not run the tests it is told to run.

The adapter names the variables that move the agent's temp directory, and the
launcher points them at the run's own writable temp directory, kept short where
/tmp is writable, because Claude Code puts socket paths under it. Self-contained.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from openharnx.agent import CLAUDE_CODE, launch
from openharnx.sandbox import find_srt

# Claude Code warns when its temp directory is longer than about 30 bytes.
MAX_TEMP_LEN = 30

AGENT = r"""
import json, os, sys
from pathlib import Path

names = json.loads(os.environ["FAKE_TEMP_VARS"])
seen = {n: os.environ.get(n) for n in names}
made = {}
for name, value in seen.items():
    if value:
        # What Claude Code does: a per-user directory under its temp directory.
        target = Path(value, f"claude-{os.getuid()}", "shell")
        try:
            target.mkdir(parents=True)
            made[name] = True
        except OSError as exc:
            made[name] = str(exc)
Path(os.environ["OHX_OUT"], "seen.json").write_text(json.dumps({"seen": seen, "made": made}))
"""

# Stand-in for srt, called as: srt -s <profile> -c <command>.
RUNS = '#!/bin/sh\nshift 3\nexec /bin/sh -c "$1"\n'


def _run(tmp_path: Path, srt: Path) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    out = tmp_path / "out"
    out.mkdir()
    run_dir = tmp_path / "run"
    run = launch(
        [sys.executable, str(agent)],
        "prompt",
        cwd=tmp_path,
        run_dir=run_dir,
        phase="investigate",
        writable=[out],
        srt=srt,
        ohx_home=tmp_path / "home",
        extra_env={"OHX_OUT": str(out), "FAKE_TEMP_VARS": json.dumps(CLAUDE_CODE.temp_env)},
    )
    assert run.exit_code == 0, run.output.decode("utf-8", "replace")
    profile = json.loads((run_dir / "agent-investigate.json").read_text())
    return json.loads((out / "seen.json").read_text()), profile


def _tmp_writable() -> bool:
    try:
        Path(tempfile.mkdtemp(dir="/tmp")).rmdir()
    except OSError:
        return False
    return True


def test_claude_code_adapter_names_its_temp_directory_variable() -> None:
    assert "CLAUDE_CODE_TMPDIR" in CLAUDE_CODE.temp_env


def test_agent_temp_directory_is_set_short_and_writable_in_the_profile(
    tmp_path: Path,
) -> None:
    srt = tmp_path / "fake-srt"
    srt.write_text(RUNS)
    srt.chmod(0o755)
    result, profile = _run(tmp_path, srt)
    filesystem = profile["filesystem"]
    assert isinstance(filesystem, dict)
    for name in CLAUDE_CODE.temp_env:
        value = result["seen"][name]
        assert isinstance(value, str) and value, f"{name} not set for the agent"
        if _tmp_writable():  # elsewhere (a sandbox, a locked-down runner) any path will do
            assert len(value) <= MAX_TEMP_LEN, f"{name}={value} is too long for socket paths"
        assert Path(value).is_absolute()
        assert any(value == w or value.startswith(w + "/") for w in filesystem["allowWrite"])
        assert result["made"][name] is True


def _real_srt_runs_here(tmp_path: Path) -> Path | None:
    srt = find_srt()
    if srt is None or not srt.exists() or shutil.which("python3") is None:
        return None
    profile = tmp_path / "probe.json"
    profile.write_text(
        json.dumps(
            {
                "network": {"allowedDomains": [], "deniedDomains": []},
                "filesystem": {"denyRead": [], "allowWrite": [], "denyWrite": []},
            }
        )
    )
    probe = subprocess.run([str(srt), "-s", str(profile), "-c", "true"], capture_output=True)
    return srt if probe.returncode == 0 else None


def test_real_sandbox_lets_the_agent_create_its_temp_directory(tmp_path: Path) -> None:
    """Real srt, where it can run; inside another sandbox it cannot, and this is skipped."""
    srt = _real_srt_runs_here(tmp_path)
    if srt is None:
        pytest.skip("real srt cannot run here (absent, or inside another sandbox)")
    result, _ = _run(tmp_path, srt)
    for name in CLAUDE_CODE.temp_env:
        assert result["made"][name] is True, result
