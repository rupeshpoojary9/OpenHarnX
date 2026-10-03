"""Acceptance tests for the GitLab and Jenkins examples (T79, contracts/0024).

The owner asked (2026-10-03) what teams that do not use GitHub should do. The
gate is a plain command; the examples call it from GitLab CI and Jenkins.
Both carry one identical block of commands between markers, so the block is
tested once and cannot drift between them: `ci/linux/examples_probe.sh` runs
it on Linux under srt. These tests read the examples as text and fail when a
trust rule is broken: the gate installed from the code under review or from an
unpinned version, the sandbox off, the base not made available, no report kept.
"""

from __future__ import annotations

import re
from pathlib import Path

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
ROOT = Path.cwd()
EXAMPLES = {
    "gitlab": ROOT / "docs" / "ci" / "gitlab-ci.yml",
    "jenkins": ROOT / "docs" / "ci" / "Jenkinsfile",
}
START, END = "# ohx-gate commands: start", "# ohx-gate commands: end"


def _block(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    assert START in text and END in text, f"{path.name}: markers missing"
    body = text.split(START, 1)[1].split(END, 1)[0]
    return [line.strip() for line in body.strip().splitlines()]


def test_both_examples_run_the_same_commands() -> None:
    blocks = {name: _block(path) for name, path in EXAMPLES.items()}
    assert blocks["gitlab"] == blocks["jenkins"]
    assert len(blocks["gitlab"]) >= 4


def test_the_gate_is_installed_from_a_pinned_trusted_source() -> None:
    block = "\n".join(_block(EXAMPLES["gitlab"]))
    assert '"openharnx @ $OHX_SOURCE@$OHX_VERSION"' in block
    assert "install ." not in block and "install -e" not in block
    for path in EXAMPLES.values():
        text = path.read_text(encoding="utf-8")
        assert re.search(r"OHX_VERSION\s*[:=]\s*['\"]<commit SHA", text), path.name
        assert not re.search(r"OHX_VERSION\s*[:=]\s*['\"](main|master|latest)", text)


def test_the_gate_runs_sandboxed_without_signing_secrets() -> None:
    block = "\n".join(_block(EXAMPLES["gitlab"]))
    assert "--sandbox srt" in block
    assert "OHX_SIGNING_KEY=none" in block


def test_the_base_is_fetched_when_the_checkout_lacks_it() -> None:
    block = "\n".join(_block(EXAMPLES["gitlab"]))
    assert "git rev-parse --verify -q" in block
    assert "git fetch --no-tags origin" in block
    assert "FETCH_HEAD" in block


def test_the_report_is_kept_and_the_exit_code_is_the_verdict() -> None:
    gitlab = EXAMPLES["gitlab"].read_text(encoding="utf-8")
    jenkins = EXAMPLES["jenkins"].read_text(encoding="utf-8")
    assert "ohx-gate/" in gitlab and "when: always" in gitlab
    assert "archiveArtifacts" in jenkins and "always" in jenkins
    assert "|| true" not in "\n".join(_block(EXAMPLES["gitlab"]))  # a block never passes itself


def test_the_readme_states_runner_requirements_and_untrusted_changes() -> None:
    text = (ROOT / "docs" / "ci" / "README.md").read_text(encoding="utf-8")
    for needed in ("user namespaces", "systempaths=unconfined", "fork", "Windows"):
        assert needed in text, needed
