"""Acceptance tests for the gate workflow's trust properties (T79, RC-18, RC-24, contracts/0023).

A workflow is easy to weaken without anyone noticing: a write permission on
the job that runs pull request code, an action moved from a pinned commit to a
tag, the gate installed from the pull request, or a signing job that checks
out the code it signs. These tests read `.github/workflows/gate.yml` as text
(no YAML dependency) and fail on any of those.

Signing (owner decision 2026-10-03): built now, active only in a public
repository and for same-repository pull requests; GitHub does not sign in
private repositories below Enterprise Cloud, and forks get no identity.
"""

from __future__ import annotations

import re
from pathlib import Path

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
WORKFLOW = Path.cwd() / ".github" / "workflows" / "gate.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    """The text of one job, from its key to the next job or the end."""
    text = _text()
    jobs = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  (?=[a-z][\w-]*:\n)", "\n" + jobs)
    for part in parts:
        if part.strip().startswith(f"{name}:"):
            return part
    raise AssertionError(f"no job {name!r}")


def test_every_action_is_pinned_to_a_commit() -> None:
    uses = re.findall(r"uses:\s*(\S+)", _text())
    assert uses, "no actions found"
    for ref in uses:
        if ref == "./trusted":  # the gate's own action, from the base checkout
            continue
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_the_default_token_is_read_only() -> None:
    top = _text().split("\njobs:\n", 1)[0]
    assert re.search(r"^permissions:\n  contents: read\n", top, re.M)
    assert "write" not in top


def test_the_job_that_runs_pull_request_code_has_no_write_permission() -> None:
    gate = _job("gate")
    assert "permissions:" not in gate  # inherits the read-only default
    assert "write" not in gate.replace("persist-credentials: false", "")


def test_the_gate_is_installed_from_the_base_and_runs_sandboxed() -> None:
    gate = _job("gate")
    assert "ref: ${{ github.event.pull_request.base.sha }}" in gate
    assert "uses: ./trusted" in gate  # the action from the base installs itself
    assert "sandbox: srt" in gate
    assert gate.count("persist-credentials: false") == 2


def test_the_signing_job_never_checks_out_or_runs_pull_request_code() -> None:
    sign = _job("sign")
    assert "actions/checkout" not in sign
    assert "run:" not in sign
    assert "ohx gate" not in sign


def test_signing_runs_only_for_public_same_repository_pull_requests() -> None:
    sign = _job("sign")
    assert "!github.event.repository.private" in sign
    assert "github.event.pull_request.head.repo.full_name == github.repository" in sign
    assert "id-token: write" in sign


def test_the_summary_says_why_a_run_is_unsigned() -> None:
    gate = _job("gate")
    assert "Not signed: GitHub signs CI evidence only in public repositories" in gate
    assert "Not signed: pull requests from forks get no signing identity." in gate
