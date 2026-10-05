"""`ohx history`: what the gate would have said about each change already merged (T92,
contracts/0049).

The spec-kit replay (T90) was a script; this makes it a command. It walks the first-
parent history of a branch and judges each commit against its parent with the gate, so
a merge commit is judged with everything its pull request brought, and a squashed one
the same way. It uses git only, so it works with any platform. Changes made by coding
agents are marked from the author and the commit message (Copilot, Claude Code, Codex,
Devin, Cursor); `--agents-only` keeps those. `--config` lends an ohx.toml to commits
that have none (the interpreter, pytest options), on both sides. The result is a
table and history.json; the command reports and exits 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from openharnx.app.history import is_agent
from openharnx.cli import EXIT_OK, main

CALC = "def add(a, b):\n    return a + b\n"
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _git(repo: Path, *args: str, author: str = "Dev <dev@example.com>") -> str:
    name, email = author.rsplit(" <", 1)
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email[:-1]}",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _commit(
    repo: Path, files: dict[str, str], message: str, author: str = "Dev <dev@example.com>"
) -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A", author=author)
    _git(repo, "commit", "-qm", message, author=author)
    return _git(repo, "rev-parse", "HEAD")


AGENT = "Copilot <198982749+Copilot@users.noreply.github.com>"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(
        repo,
        {
            "calc.py": CALC,
            "tests/test_calc.py": SUITE,
            "ohx.toml": f"python = {sys.executable!r}\n",
        },
        "start",
    )
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(repo)
    return repo


def _history(tmp_path: Path, *extra: str) -> tuple[int, list[dict[str, Any]], str]:
    out = tmp_path / "history-out"
    code = main(["history", "--sandbox", "none", "--out", str(out), *extra])
    rows: list[dict[str, Any]] = json.loads((out / "history.json").read_text())
    return code, rows, (out / "history.md").read_text()


def test_each_change_is_judged_against_its_parent(repo: Path, tmp_path: Path) -> None:
    good = _commit(
        repo,
        {
            "calc.py": CALC + "\n\ndef sub(a, b):\n    return a - b\n",
            "tests/test_sub.py": "from calc import sub\n\n\n"
            "def test_sub():\n    assert sub(3, 1) == 2\n",
        },
        "Add sub",
    )
    cheat = _commit(
        repo,
        {
            "calc.py": "def add(a, b):\n    return a * b\n\n\ndef sub(a, b):\n    return a - b\n",
            "tests/test_calc.py": SUITE.replace("== 5", "== 6"),
        },
        "Speed up add",
        author=AGENT,
    )
    code, rows, markdown = _history(tmp_path, "--last", "2")
    assert code == EXIT_OK
    by = {r["commit"]: r for r in rows}
    assert by[good]["verdict"] == "no-regressions" and by[good]["agent"] is False
    assert by[cheat]["verdict"] == "blocked" and by[cheat]["agent"] is True
    assert "test_calc" in by[cheat]["why"]
    assert good[:12] in markdown and cheat[:12] in markdown
    assert "1 of 2 changes blocked" in markdown


def test_agents_only_keeps_agent_changes(repo: Path, tmp_path: Path) -> None:
    _commit(repo, {"notes.txt": "a\n"}, "Human change")
    agent = _commit(repo, {"notes2.txt": "b\n"}, "Agent change", author=AGENT)
    _, rows, _ = _history(tmp_path, "--last", "2", "--agents-only")
    assert [r["commit"] for r in rows] == [agent]


def test_a_merged_pull_request_is_judged_as_a_whole(repo: Path, tmp_path: Path) -> None:
    _git(repo, "checkout", "-qb", "feature")
    _commit(repo, {"calc.py": "def add(a, b):\n    return a - b\n"}, "Break add")
    _commit(repo, {"notes.txt": "x\n"}, "Unrelated")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge feature")
    merge = _git(repo, "rev-parse", "HEAD")
    _, rows, _ = _history(tmp_path, "--last", "1")
    assert rows[0]["commit"] == merge and rows[0]["verdict"] == "blocked"


def test_the_first_commit_has_nothing_to_compare_with(repo: Path, tmp_path: Path) -> None:
    _, rows, _ = _history(tmp_path, "--last", "5")
    assert len(rows) == 1 and rows[0]["verdict"] == "skipped"
    assert "no parent" in rows[0]["why"]


def test_a_lent_config_is_used_on_both_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "bare-proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"calc.py": CALC, "tests/test_calc.py": SUITE}, "start")
    change = _commit(repo, {"calc.py": CALC + "\n\nX = 1\n"}, "change")
    config = tmp_path / "lent.toml"
    config.write_text(f'python = {sys.executable!r}\npytest_args = ["-p", "no:randomly"]\n')
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "unused-home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.chdir(repo)
    _, rows, _ = _history(tmp_path, "--last", "1", "--config", str(config))
    assert rows[0]["commit"] == change and rows[0]["verdict"] == "no-regressions"
    assert not (repo / "ohx.toml").exists()  # nothing was written into the repository
    assert _git(repo, "status", "--porcelain") == ""


def test_the_table_counts_checked_tests(repo: Path, tmp_path: Path) -> None:
    _commit(repo, {"notes.txt": "a\n"}, "Docs only")
    _, rows, markdown = _history(tmp_path, "--last", "1")
    assert rows[0]["tests"] == {
        "ran": 1,
        "checked": 1,
        "failed_both_times": 0,
        "skipped_both_times": 0,
    }
    assert "| commit |" in markdown.lower()


@pytest.mark.parametrize(
    ("author", "message", "expected"),
    [
        ("Copilot <198982749+Copilot@users.noreply.github.com>", "Fix", True),
        ("copilot-swe-agent[bot] <x@users.noreply.github.com>", "Fix", True),
        ("devin-ai-integration[bot] <x@users.noreply.github.com>", "Fix", True),
        ("Dev <dev@example.com>", "Fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>", True),
        ("Dev <dev@example.com>", "Fix\n\nGenerated with Claude Code", True),
        (
            "Dev <dev@example.com>",
            "Fix\n\nCo-authored-by: Copilot <x@users.noreply.github.com>",
            True,
        ),
        (
            "Dev <dev@example.com>",
            "Fix\n\nCo-authored-by: Cursor Agent <cursoragent@cursor.com>",
            True,
        ),
        ("Dev <dev@example.com>", "Fix\n\nCo-authored-by: codex <codex@openai.com>", True),
        ("Dev <dev@example.com>", "Fix the Claude parser", False),
        ("Dev <dev@example.com>", "Bump copilot-sdk to 2.0", False),
        ("Claudia Ruiz <claudia@example.com>", "Fix", False),
    ],
)
def test_agent_changes_are_recognised_from_author_and_trailers(
    author: str, message: str, expected: bool
) -> None:
    assert is_agent(author, message) is expected


def test_the_count_is_the_largest_suite_not_the_last(repo: Path, tmp_path: Path) -> None:
    second = "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 2) == 2\n"
    _commit(repo, {"tests/test_zero.py": second}, "More tests")
    (repo / "tests" / "test_zero.py").unlink()
    _commit(repo, {}, "Drop a test file")  # the locked copy still has 2 tests, its own 1
    _, rows, _ = _history(tmp_path, "--last", "1")
    assert rows[0]["verdict"] == "blocked" and rows[0]["tests"]["ran"] == 2
