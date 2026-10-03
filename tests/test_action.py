"""Acceptance tests for the reusable GitHub Action (T79, contracts/0025).

The repository's own workflow installed the gate from the base checkout, which
only works for OpenHarnX itself. Other GitHub projects use `action.yml`
(`uses: <owner>/OpenHarnX@<commit SHA>`). The action installs the gate from its
own source, so pinning the action pins the gate, and never installs the
project's code. Inputs reach the shell only through environment variables
(no script injection). OpenHarnX's own workflow uses the action from the base
checkout, so every pull request here also exercises it.
"""

from __future__ import annotations

import re
from pathlib import Path

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
ROOT = Path.cwd()
ACTION = ROOT / "action.yml"


def _text() -> str:
    return ACTION.read_text(encoding="utf-8")


def _runs() -> list[str]:
    """Every `run:` script in the action."""
    return re.findall(r"run: \|\n((?:        .*\n|\n)+)", _text())


def test_the_action_is_composite_and_installs_the_gate_from_its_own_source() -> None:
    text = _text()
    assert "using: composite" in text
    assert "ACTION_PATH: ${{ github.action_path }}" in text
    assert 'install -q uv "$ACTION_PATH"' in text
    for script in _runs():
        assert not re.search(r"pip\"? install[^\n]*(\s\.\s|\s\.$|-e)", script), script


def test_inputs_reach_scripts_only_through_the_environment() -> None:
    scripts = _runs()
    assert scripts
    for script in scripts:
        assert "${{" not in script, script


def test_the_gate_runs_sandboxed_with_a_pinned_sandbox() -> None:
    text = _text()
    assert re.search(r"sandbox:\n(?:\s+.*\n)*?\s+default: srt\n", text)
    assert "@anthropic-ai/sandbox-runtime@0.0.77" in text
    assert "OHX_SIGNING_KEY: none" in text


def test_the_base_is_fetched_and_the_exit_code_is_the_verdict() -> None:
    text = _text()
    assert "git fetch --no-tags origin" in text and "FETCH_HEAD" in text
    assert 'exit "$code"' in text
    assert "readiness=" in text and "report=" in text


def test_the_repository_workflow_uses_the_action_from_the_base() -> None:
    workflow = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
    assert "uses: ./trusted" in workflow
    assert "ref: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "pip" not in workflow  # the action installs the gate


def test_the_usage_example_pins_a_commit_and_a_read_only_token() -> None:
    text = (ROOT / "docs" / "ci" / "README.md").read_text(encoding="utf-8")
    assert "uses: rupeshpoojary9/OpenHarnX@<commit SHA" in text
    assert "contents: read" in text
