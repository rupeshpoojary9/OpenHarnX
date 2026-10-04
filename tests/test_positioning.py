"""OpenHarnX describes itself as a verifier (owner decision 2026-10-04, contracts/0038).

Agent creation, staffing and planning moved to a separate project. Every place the
product names itself says what it does now: it verifies work done by coding agents.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import openharnx
from openharnx.cli import build_parser

ROOT = Path.cwd()


def _descriptions() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    intro = readme.partition("# OpenHarnX")[2].partition("## ")[0]
    return {
        "pyproject": pyproject["project"]["description"],
        "readme": intro,
        "package": openharnx.__doc__ or "",
        "cli": build_parser().description or "",
    }


def test_every_description_says_it_verifies_coding_agent_work() -> None:
    for where, text in _descriptions().items():
        assert "verif" in text.lower(), where
        assert "coding agent" in text.lower(), where


def test_no_description_claims_staffing_or_planning() -> None:
    for where, text in _descriptions().items():
        for word in ("staff", "plans,", "delivery system", "team configurations"):
            assert word not in text.lower(), (where, word)
