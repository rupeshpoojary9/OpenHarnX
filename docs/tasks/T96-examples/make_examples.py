"""Make the T96 example reports: five cases in throwaway repositories, one report.md each.

    uv run python docs/tasks/T96-examples/make_examples.py <out-dir>

Run it with an earlier OpenHarnX install's interpreter to get the reports without the
brief (the `before` folder). No sandbox, no model calls.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from openharnx.cli import main

CALC = "def add(a, b):\n    return a + b\n\n\ndef half(a):\n    return a\n"
FIXED = CALC.replace("    return a\n", "    return a / 2\n")
SUITE = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
ACCEPTANCE = (
    "from calc import half\n\n\ndef test_half_of_ten():\n    assert half(10) == 5\n\n\n"
    "def test_half_of_zero():\n    assert half(0) == 0\n"
)
CONTRACT = ["contract", "new", "--mode", "bugfix", "--title", "Fix half", "--summary",
            "half() returns half of its argument", "--acceptance", "acceptance/test_half.py",
            "--accept", "--sandbox", "none"]  # fmt: skip


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _quiet(args: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(args)


def _project() -> Path:
    base = Path(tempfile.mkdtemp(prefix="ohx-brief-"))
    repo = base / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "acceptance").mkdir()
    (repo / "calc.py").write_text(CALC)
    (repo / "other.py").write_text("def unused():\n    return 1\n")
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "acceptance" / "test_half.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    os.environ["OHX_HOME"] = str(base / "home")
    os.environ["OHX_SIGNING_KEY"] = "none"
    os.chdir(repo)
    _quiet(["init"])
    return repo


def _save(out: Path, name: str, report_command: bool = False) -> None:
    if report_command:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["report"])
        text = buffer.getvalue()
    else:
        code = _quiet(["verify", "--sandbox", "none"])
        home = Path(os.environ["OHX_HOME"])
        runs = sorted(home.glob("projects/*/runs/*/report.md"), key=lambda p: p.stat().st_mtime)
        text = runs[-1].read_text()
    (out / f"{name}.md").write_text(text)
    print(name, "exit", code)


def run(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    repo = _project()
    _quiet(CONTRACT)
    (repo / "calc.py").write_text(FIXED)
    _save(out, "1-ready")

    repo = _project()
    _quiet(["init", "--lock-tests", "--sandbox", "none"])
    (repo / "calc.py").write_text(FIXED)
    _save(out, "2-no-regressions")

    repo = _project()
    _quiet(CONTRACT)
    (repo / "calc.py").write_text(FIXED.replace("a + b", "a - b"))
    _save(out, "3-blocked")

    repo = _project()
    _quiet(CONTRACT)
    (repo / "calc.py").write_text(FIXED)
    (repo / "other.py").write_text("def unused():\n    return 2\n")
    (repo / "requirements.txt").write_text("requests\n")
    _save(out, "4-unimported-code")

    repo = _project()
    _quiet(CONTRACT)
    (repo / "calc.py").write_text(FIXED)
    _quiet(["verify", "--sandbox", "none"])
    (repo / "other.py").write_text("x = 3\n")
    _save(out, "5-stale", report_command=True)


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
