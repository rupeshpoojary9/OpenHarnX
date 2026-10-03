"""Acceptance tests for the public gate's release criteria (T86, contracts/0020).

From the research verification of 2026-10-01: the gate may ship before the
full M1 scope, but only against its own written boundary (supported
environment, trust boundary, verdict meaning, controls, stale and corrupt
evidence, approved checker changes, untrusted pull requests, and what is not
supported). A criteria document can drift from the code, so these tests keep
it honest: every criterion marked met names tests that exist, every one not
met names the task that owns it, and the release line follows from the rows.
The README must not claim more, or less, than the criteria say.
"""

from __future__ import annotations

import re
from pathlib import Path

# The checker runs in the candidate; the locked copy of this file lives elsewhere.
ROOT = Path.cwd()
CRITERIA = ROOT / "docs" / "gate-release-criteria.md"
README = ROOT / "README.md"
EVIDENCE = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")


def _rows() -> list[dict[str, str]]:
    rows = []
    for line in CRITERIA.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 6, f"expected 6 columns: {line}"
        rows.append(
            dict(
                zip(
                    ["id", "criterion", "release", "status", "evidence", "owner"],
                    cells,
                    strict=True,
                )
            )
        )
    return rows


def test_criteria_cover_every_area_the_verification_asked_for() -> None:
    text = CRITERIA.read_text(encoding="utf-8")
    for heading in (
        "Supported environment",
        "Trust boundary",
        "What READY means",
        "Positive and negative controls",
        "Stale and corrupt evidence",
        "Approved checker changes",
        "Untrusted pull requests",
        "Not supported",
    ):
        assert f"## {heading}" in text, heading
    ids = [r["id"] for r in _rows()]
    assert len(ids) >= 15
    assert len(ids) == len(set(ids))


def test_each_row_has_a_known_status_and_release_flag() -> None:
    for r in _rows():
        assert r["status"] in ("met", "not met"), r
        assert r["release"] in ("required", "later"), r


def test_met_criteria_cite_tests_that_exist() -> None:
    for r in _rows():
        if r["status"] != "met":
            continue
        cited = EVIDENCE.findall(r["evidence"])
        assert cited, f"{r['id']} is met but cites no test"
        for path, name in cited:
            source = ROOT / path
            assert source.is_file(), f"{r['id']}: {path} does not exist"
            assert re.search(rf"^def {name}\b", source.read_text(), re.M), f"{r['id']}: {name}"


def test_criteria_not_met_name_the_task_that_owns_them() -> None:
    for r in _rows():
        if r["status"] == "not met":
            assert re.fullmatch(r"T\d+(, T\d+)*", r["owner"]), r


def test_the_release_line_follows_from_the_rows() -> None:
    blocking = [r["id"] for r in _rows() if r["release"] == "required" and r["status"] != "met"]
    text = CRITERIA.read_text(encoding="utf-8")
    expected = "**Releasable now: no**" if blocking else "**Releasable now: yes**"
    assert expected in text
    for rid in blocking:
        assert rid in text.split(expected, 1)[1].split("\n\n", 1)[0], f"{rid} not listed"


def test_readme_states_what_works_and_what_is_not_supported() -> None:
    text = README.read_text(encoding="utf-8")
    assert "Nothing product-facing works yet" not in text
    assert "docs/gate-release-criteria.md" in text
    assert "Not supported" in text
