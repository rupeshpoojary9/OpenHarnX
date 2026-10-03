"""Acceptance tests for the tools the action puts within the gate's reach (T79, contracts/0026).

Found by the first real run of the action on GitHub (2026-10-03, run
37119728025): the action installed uv into its own environment but did not put
that environment on PATH, so the gate could not build the protected checker
environment, every check was unavailable and the verdict blocked (unknown,
never a pass). The old workflow had added the environment to PATH in a step of
its own. The gate's step must reach uv, through PATH or OHX_UV.
"""

from __future__ import annotations

import re
from pathlib import Path

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
ACTION = Path.cwd() / "action.yml"


def _gate_step() -> str:
    text = ACTION.read_text(encoding="utf-8")
    return text.split("id: gate", 1)[1]


def test_the_gate_step_reaches_the_installed_uv() -> None:
    step = _gate_step()
    on_path = re.search(r'export PATH="\$RUNNER_TEMP/ohx/bin:\$PATH"', step)
    explicit = "OHX_UV:" in step or "OHX_UV=" in step
    assert on_path or explicit


def test_uv_is_installed_into_the_same_environment() -> None:
    text = ACTION.read_text(encoding="utf-8")
    assert '"$RUNNER_TEMP/ohx/bin/pip" install -q uv' in text
