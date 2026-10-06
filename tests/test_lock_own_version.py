"""A release that bumps the project's own version is not a changed environment (T100,
contracts/0060).

Found when OpenHarnX's own 0.1.0 release candidate went through the CI gate
(2026-10-06, run 37466222249): bumping `version` in pyproject.toml changes one line of
`uv.lock`, the project's own entry, and the gate made every check invalid because
"uv.lock changed since contract acceptance". The protected environment is built with
`--no-install-project`, from the accepted copy of the lockfile, so the project's own
version never reaches it; every version bump in a uv project would have been UNKNOWN.

Now only that line is set aside: the `version` of the package whose source is the
project itself (`editable` or `virtual` "."). Any other difference in the lockfile, a
dependency, another package's version, the project's own dependency list, even a
comment, still runs nothing until a contract revision is accepted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, main

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "import sys\n\nimport calc\n\nsys.exit(0 if calc.add(2, 3) == 5 else 1)\n"
PYPROJECT = '[project]\nname = "calc"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
LOCK = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "calc"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "six" },
]

[[package]]
name = "six"
version = "1.16.0"
source = { registry = "https://pypi.org/simple" }
"""
STAND_IN_UV = f"""#!{sys.executable}
import os, subprocess, sys
args = sys.argv[1:]
assert args[0] == "sync", args
assert {{"--frozen", "--no-install-project", "--no-build"}} <= set(args), args
target = os.environ["UV_PROJECT_ENVIRONMENT"]
subprocess.run([{sys.executable!r}, "-m", "venv", "--without-pip", target], check=True)
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    stand_in = tmp_path / "stand-in-uv"
    stand_in.write_text(STAND_IN_UV)
    stand_in.chmod(0o755)
    monkeypatch.setenv("OHX_UV", str(stand_in))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    acceptance = tmp_path / "outside" / "check_calc.py"
    acceptance.parent.mkdir()
    acceptance.write_text(ACCEPTANCE)
    repo = tmp_path / "proj"
    (repo / "contracts").mkdir(parents=True)
    (repo / "calc.py").write_text(BUGGY)
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "uv.lock").write_text(LOCK)
    (repo / "contracts" / "0001-fix-add.toml").write_text(
        'title = "Fix add"\nmode = "bugfix"\nchange_summary = "add adds"\n'
        'environment = "uv"\n\n[[obligations]]\nid = "acceptance"\nkind = "acceptance"\n'
        f"mandatory = true\nprotected = {os.path.relpath(acceptance, repo / 'contracts')!r}\n"
        'command = ["{python}", "{protected}"]\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["contract", "accept", "contracts/0001-fix-add.toml"]) == EXIT_OK
    (repo / "calc.py").write_text(FIXED)
    return repo


def _notes(capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    main(["report", "--json"])
    report = json.loads(capsys.readouterr().out)
    return [o["note"] for o in report["observations"] if o["obligation_id"] != "weakening"]


def test_bumping_the_projects_own_version_is_not_a_changed_environment(repo: Path) -> None:
    (repo / "pyproject.toml").write_text(PYPROJECT.replace("0.1.0", "0.2.0"))
    (repo / "uv.lock").write_text(LOCK.replace('version = "0.1.0"', 'version = "0.2.0"'))
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda t: t.replace('version = "1.16.0"', 'version = "1.17.0"'), id="dep"),
        pytest.param(
            lambda t: t.replace(
                '    { name = "six" },\n', '    { name = "six" },\n    { name = "requests" },\n'
            ),
            id="own dependency list",
        ),  # fmt: skip
        pytest.param(lambda t: t + "\n# changed by the agent\n", id="comment"),
        pytest.param(
            lambda t: t.replace('name = "six"\nversion', 'name = "six"\nversion = "0.1.0"\nx'),
            id="another package's line made to look like the project's",
        ),
    ],
)
def test_any_other_lockfile_change_still_runs_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str], change: object
) -> None:
    assert callable(change)
    (repo / "uv.lock").write_text(change(LOCK))
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    notes = _notes(capsys)
    assert notes and all("uv.lock" in n for n in notes)


def test_the_environment_is_still_built_from_the_accepted_copy(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "uv.lock").write_text(LOCK.replace('version = "0.1.0"', 'version = "0.2.0"'))
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    capsys.readouterr()
    main(["report", "--json"])
    report = json.loads(capsys.readouterr().out)
    interpreter = Path(report["observations"][0]["argv"][0])
    assert interpreter.is_relative_to(tmp_path / "home")  # the store, not the candidate
