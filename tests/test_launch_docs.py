"""Acceptance tests for the launch documents (T81, RC-25, contracts/0037).

A public release needs a way to report a vulnerability privately, a published threat
model for the gate and a pinned install. Reports go through GitHub's private
vulnerability reporting, so no address is published. The threat model's evidence must
name tests that exist, like the release criteria, so it cannot drift from the code.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path.cwd()
SECURITY = ROOT / "SECURITY.md"
THREATS = ROOT / "docs" / "threat-model.md"
RELEASING = ROOT / "docs" / "releasing.md"


def _test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_vulnerabilities_are_reported_privately_without_a_published_address() -> None:
    text = SECURITY.read_text(encoding="utf-8")
    assert "Report a vulnerability" in text  # GitHub's private vulnerability reporting
    assert "security/advisories/new" in text
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)  # no email address
    assert "issue" in text.lower()  # and not in a public issue
    assert "docs/threat-model.md" in text


def test_the_threat_model_covers_the_gate() -> None:
    text = THREATS.read_text(encoding="utf-8")
    gate = text.partition("## The gate")[2].partition("\n## ")[0]
    assert gate, "no section for the gate"
    for subject in ("pull request", "runner", "lockfile", "Stop hook", "Linux"):
        assert subject in gate, subject


def test_every_test_the_threat_model_cites_exists() -> None:
    text = THREATS.read_text(encoding="utf-8")
    cited = re.findall(r"`(tests/[\w/]+\.py)(?:::(\w+))?`", text)
    assert len(cited) > 20
    for path, name in cited:
        assert (ROOT / path).is_file(), path
        if name:
            assert name in _test_names(ROOT / path), f"{path}::{name}"


def test_the_readme_shows_a_pinned_install_and_how_releases_are_made() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"uv tool install git\+https://github\.com/\S+@v\d", readme)
    releasing = RELEASING.read_text(encoding="utf-8")
    assert "READY" in releasing and "tag" in releasing
    assert "commit" in releasing  # a tag can move; the release names its commit
