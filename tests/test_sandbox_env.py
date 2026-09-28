"""Acceptance tests for the sandbox environment (contracts/0004).

Found in the first real agent run: `env -i` inside the sandbox removed the
proxy settings srt provides, so the agent could not reach its model API. The
allowlist must be applied to srt's own environment instead, so the child sees
exactly the allowlist plus srt's proxy settings, and never the caller's secrets.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from openharnx.sandbox import verifier_profile, wrap, write_profile


def test_wrap_applies_the_allowlist_outside_without_wiping_inside(tmp_path: Path) -> None:
    child = {"PATH": "/usr/bin:/bin", "HOME": "/h", "TMPDIR": str(tmp_path / "t")}
    cmd, env = wrap(Path("/bin/srt"), tmp_path / "p.json", ["python", "-V"], child)
    inner = cmd[-1]
    assert "env -i" not in inner
    assert f"TMPDIR={tmp_path / 't'}" in inner
    assert set(env) == set(child)  # nothing from the caller beyond the allowlist
    assert env["TMPDIR"] == "/tmp"  # srt's own socket path stays short
    assert env["PATH"] == child["PATH"] and env["HOME"] == child["HOME"]


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_child_gets_proxy_and_allowlist_but_not_caller_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OHX_FAKE_SECRET", "s3cr3t-canary")
    tmp = tmp_path / "t"
    tmp.mkdir()
    profile = write_profile(tmp_path / "p.json", verifier_profile(tmp, []))
    # srt is a Node program, so the PATH it runs with must reach node, as it does in
    # real use where the verifier and agent pass the caller's PATH.
    child = {"PATH": os.environ["PATH"], "HOME": str(Path.home()), "TMPDIR": str(tmp)}
    cmd, env = wrap(Path(os.environ["OHX_SRT"]), profile, ["env"], child)
    out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60).stdout
    assert "HTTPS_PROXY=" in out
    assert f"TMPDIR={tmp}" in out
    assert "s3cr3t-canary" not in out
