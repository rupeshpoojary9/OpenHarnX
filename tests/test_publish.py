"""Publishing to PyPI through trusted publishing (T101, contracts/0065).

0.1.0 installed only from GitHub. Publishing to PyPI makes the install
`uv tool install openharnx`, and the PyPI page is where many people meet the project.

The upload is the most sensitive thing the repository does, so the workflow is held to
the same rules as the gate's: it runs only when a release is published, every action is
pinned to a commit, the default token is read-only, and only the upload job may ask for
a PyPI identity. That job runs in the `pypi` environment, which waits for the owner's
approval and accepts only `v*` tags, and it never checks out or runs the repository's
code: it uploads what the build job made. The build refuses a version that does not
match the tag. No token or password is stored; PyPI trusts this workflow by name.

The README is also PyPI's project page, where relative links do not resolve, so every
link in it is absolute. The package metadata names the repository, the documentation,
the issues and the releases.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path.cwd()
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
REPO = "https://github.com/rupeshpoojary9/OpenHarnX"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    jobs = _text().split("\njobs:\n", 1)[1]
    for part in re.split(r"\n  (?=[a-z][\w-]*:\n)", "\n" + jobs):
        if part.strip().startswith(f"{name}:"):
            return part
    raise AssertionError(f"no job {name!r}")


def _on() -> str:
    return _text().split("\non:\n", 1)[1].split("\n\n", 1)[0]


def test_it_runs_only_when_a_release_is_published() -> None:
    on = _on()
    assert "release:" in on and "published" in on
    for other in ("push:", "pull_request", "workflow_dispatch", "schedule:"):
        assert other not in on, other


def test_every_action_is_pinned_to_a_commit() -> None:
    uses = re.findall(r"uses:\s*(\S+)", _text())
    assert uses
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action), action


def test_the_default_token_is_read_only() -> None:
    top = _text().split("\njobs:\n", 1)[0]
    assert re.search(r"^permissions:\n  contents: read\s*$", top, re.M)


def test_only_the_upload_job_asks_for_a_pypi_identity_in_the_approved_environment() -> None:
    assert "id-token: write" not in _job("build")
    upload = _job("upload")
    assert "id-token: write" in upload
    assert re.search(r"environment:\s*\n\s+name: pypi", upload)
    assert _text().count("id-token: write") == 1


def test_the_upload_job_never_checks_out_or_runs_the_code() -> None:
    upload = _job("upload")
    assert "actions/checkout" not in upload
    assert "run:" not in upload
    assert "actions/download-artifact" in upload
    assert "pypa/gh-action-pypi-publish" in upload


def test_the_build_refuses_a_version_that_does_not_match_the_tag() -> None:
    build = _job("build")
    assert "GITHUB_REF_NAME" in build and "pyproject.toml" in build
    assert "uv build" in build
    assert "persist-credentials: false" in build


def test_the_package_metadata_points_to_the_project() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    urls = project["urls"]
    for key in ("Homepage", "Documentation", "Issues", "Releases"):
        assert urls[key].startswith(REPO), key
    assert {"coding-agents", "verification", "pytest"} <= set(project["keywords"])
    classifiers = set(project["classifiers"])
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Development Status :: 3 - Alpha" in classifiers
    assert not [c for c in classifiers if c.startswith("License ::")]  # the SPDX field says it
    assert "coding agent" in project["description"]


def test_every_link_in_the_readme_works_on_pypi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)\s]+)\)|(?:href|src|srcset)=\"([^\"]+)\"", readme)
    relative = [a or b for a, b in links if not (a or b).startswith(("https://", "http://"))]
    in_page = [link for link in relative if link.startswith("#")]
    assert relative == in_page, sorted(set(relative) - set(in_page))
    assert not in_page  # PyPI drops heading anchors too


def test_the_readme_installs_from_pypi_and_still_names_the_sandbox() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv tool install openharnx" in readme
    assert "@anthropic-ai/sandbox-runtime@0.0.77" in readme


def test_releasing_says_how_a_release_reaches_pypi() -> None:
    text = (ROOT / "docs" / "releasing.md").read_text(encoding="utf-8")
    assert "publish.yml" in text and "pypi" in text and "approv" in text


def test_the_logo_follows_githubs_theme_not_the_computers() -> None:
    """Found 2026-10-07: a `<picture>` with `prefers-color-scheme` follows the computer's
    theme, so with GitHub set to light and macOS to dark the white logo showed on a white
    page. GitHub hides a link ending in `#gh-dark-mode-only` or `#gh-light-mode-only`
    by its own theme setting."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    head = readme.split("# OpenHarnX", 1)[0]
    assert "<picture>" not in head and "prefers-color-scheme" not in head
    light = re.search(r'href="[^"]+#gh-light-mode-only"><img src="([^"]+)"', head)
    dark = re.search(r'href="[^"]+#gh-dark-mode-only"><img src="([^"]+)"', head)
    assert light and light.group(1).endswith("openharnx-logo-light.png")
    assert dark and dark.group(1).endswith("openharnx-logo-dark.png")
