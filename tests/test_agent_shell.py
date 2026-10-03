"""Acceptance tests for shell temp files in the agent sandbox (contracts/0014).

From the first real `ohx bug` run on another repository (2026-10-03): every
heredoc the agent ran failed inside the srt sandbox with "can't create temp
file for here document: operation not permitted". zsh, the macOS default
shell, puts heredoc files under TMPPREFIX (default /tmp/zsh), not TMPDIR, and
the agent profile does not allow writing there.

The launcher points the shell's temp prefix into the run's own writable temp
directory. Self-contained.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.agent import launch
from openharnx.sandbox import find_srt

AGENT = r"""
import json, os, shutil, subprocess
from pathlib import Path

result = {"tmpprefix": os.environ.get("TMPPREFIX")}
zsh = shutil.which("zsh")
if zsh:
    run = subprocess.run([zsh, "-c", "cat <<EOF\nheredoc ok\nEOF"], capture_output=True, text=True)
    result["heredoc"] = run.stdout.strip()
    result["error"] = run.stderr.strip()
Path(os.environ["OHX_OUT"], "seen.json").write_text(json.dumps(result))
"""

# Stand-in for srt, called as: srt -s <profile> -c <command>.
RUNS = '#!/bin/sh\nshift 3\nexec /bin/sh -c "$1"\n'


def _run(tmp_path: Path, srt: Path) -> tuple[dict[str, str], dict[str, object]]:
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
        extra_env={"OHX_OUT": str(out)},
    )
    assert run.exit_code == 0, run.output.decode("utf-8", "replace")
    profile = json.loads((run_dir / "agent-investigate.json").read_text())
    return json.loads((out / "seen.json").read_text()), profile


def test_shell_temp_prefix_is_inside_a_writable_directory(tmp_path: Path) -> None:
    srt = tmp_path / "fake-srt"
    srt.write_text(RUNS)
    srt.chmod(0o755)
    result, profile = _run(tmp_path, srt)
    filesystem = profile["filesystem"]
    assert isinstance(filesystem, dict)
    prefix = result["tmpprefix"]
    assert prefix, "TMPPREFIX not set for the agent"
    assert any(prefix.startswith(w + "/") for w in filesystem["allowWrite"]), prefix


def _real_srt_runs_here(tmp_path: Path) -> Path | None:
    srt = find_srt()
    if srt is None or not srt.exists() or shutil.which("zsh") is None:
        return None
    profile = tmp_path / "probe.json"
    empty: dict[str, list[str]] = {"denyRead": [], "allowWrite": [], "denyWrite": []}
    profile.write_text(
        json.dumps({"network": {"allowedDomains": [], "deniedDomains": []}, "filesystem": empty})
    )
    probe = subprocess.run([str(srt), "-s", str(profile), "-c", "true"], capture_output=True)
    return srt if probe.returncode == 0 else None


def test_real_sandbox_runs_a_zsh_heredoc(tmp_path: Path) -> None:
    """Real srt and zsh, where they can run; otherwise skipped."""
    srt = _real_srt_runs_here(tmp_path)
    if srt is None:
        pytest.skip("real srt or zsh cannot run here (absent, or inside another sandbox)")
    result, _ = _run(tmp_path, srt)
    assert result["heredoc"] == "heredoc ok", result
