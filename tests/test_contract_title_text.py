"""Acceptance tests for T77 item 7, UX-10 (contracts/0010).

Found by the independent review on `fb39881`: an emoji in a contract title
produced invalid TOML. Strings were written with `json.dumps`, which escapes
characters outside the Basic Multilingual Plane as surrogate pairs; TOML
forbids surrogate escapes.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from openharnx.cli import EXIT_OK, main

ACCEPTANCE = "def test_ok():\n    assert True\n"

TEXTS = {
    "emoji": "Fix login \U0001f512 flow",
    "accents": "Réparer la façade",
    "cjk": "修复登录",
    "devanagari": "लॉगिन ठीक करें",
    "quotes and backslash": 'Say "hi" \\ bye',
    "control characters": "tab\there, delete\x7fthere",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "README").write_text("x\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    acceptance = tmp_path / "outside" / "test_ok.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    return acceptance


@pytest.mark.parametrize("text", list(TEXTS.values()), ids=list(TEXTS))
def test_title_and_summary_round_trip_and_accept(repo: Path, text: str) -> None:
    args = ["contract", "new", "--title", text, "--summary", text, "--acceptance", str(repo)]
    assert main([*args, "--accept"]) == EXIT_OK
    (path,) = (Path.cwd() / "contracts").glob("*.toml")
    raw = tomllib.loads(path.read_bytes().decode("utf-8"))
    assert raw["title"] == text
    assert raw["change_summary"] == text
