"""A pull request that changes only documentation does not run the gate's suite in CI
(T102, contracts/0066).

Owner decision 2026-10-07: a README or docs change should not trigger CI. The full gate
runs the suite three times under the sandbox, about 30 minutes, for a two-line README
fix. Branch protection requires the `gate` check, so the workflow cannot simply be
skipped (a required check that never reports blocks the merge forever): the job still
starts, finds that only documentation changed, reports success within seconds and skips
the suite, the sandbox and the signing.

What counts as documentation is decided by the base branch's `scripts/docs-only.sh`,
never the pull request's copy, so a pull request cannot widen it: Markdown files and
`docs/assets/`, except under `tests/`, `src/` and `contracts/`. Everything else, the CI
examples in `docs/ci/` included (they are tested), runs the full gate. An empty diff runs
the full gate too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path.cwd()
SCRIPT = ROOT / "scripts" / "docs-only.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "gate.yml"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _judge(tmp_path: Path, files: dict[str, str]) -> tuple[int, str]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / "README.md").write_text("# a\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change", "--allow-empty")
    head = _git(repo, "rev-parse", "HEAD")
    r = subprocess.run(["sh", str(SCRIPT), base, head, str(repo)], capture_output=True, text=True)
    return r.returncode, r.stdout


@pytest.mark.parametrize(
    "files",
    [
        {"README.md": "# changed\n"},
        {"ROADMAP.md": "x\n", "CONTRIBUTING.md": "y\n"},
        {"docs/tasks/T1.md": "x\n", "examples/cheat-demo/README.md": "y\n"},
        {"docs/assets/demo.gif": "GIF89a"},
    ],
    ids=["readme", "top-level docs", "nested docs", "doc images"],
)
def test_documentation_only_is_recognised(tmp_path: Path, files: dict[str, str]) -> None:
    code, out = _judge(tmp_path, files)
    assert code == 0, out
    for name in files:
        assert name in out  # the files it judged are named in the job summary


@pytest.mark.parametrize(
    "files",
    [
        {"README.md": "x\n", "src/a.py": "x = 2\n"},
        {"tests/test_a.py": "def test_a():\n    pass\n"},
        {"tests/notes.md": "data a test reads\n"},
        {"src/openharnx/notes.md": "x\n"},
        {"contracts/0001-a.md": "x\n"},
        {"pyproject.toml": "[project]\n"},
        {"uv.lock": "x\n"},
        {"ohx.toml": "x = 1\n"},
        {".github/workflows/gate.yml": "x\n"},
        {"docs/ci/gitlab-ci.yml": "x\n"},
        {"docs/ci/Jenkinsfile": "x\n"},
        {"action.yml": "x\n"},
    ],
    ids=[
        "docs and code",
        "a test",
        "markdown under tests",
        "markdown under src",
        "markdown under contracts",
        "pyproject",
        "lockfile",
        "ohx.toml",
        "workflow",
        "gitlab example",
        "jenkins example",
        "action",
    ],  # fmt: skip
)
def test_anything_else_runs_the_full_gate(tmp_path: Path, files: dict[str, str]) -> None:
    code, _ = _judge(tmp_path, files)
    assert code != 0


def test_an_empty_change_runs_the_full_gate(tmp_path: Path) -> None:
    code, _ = _judge(tmp_path, {})
    assert code != 0


def _job(name: str) -> str:
    jobs = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    for part in re.split(r"\n  (?=[a-z][\w-]*:\n)", "\n" + jobs):
        if part.strip().startswith(f"{name}:"):
            return part
    raise AssertionError(f"no job {name!r}")


def test_the_base_branchs_script_decides() -> None:
    gate = _job("gate")
    assert "trusted/scripts/docs-only.sh" in gate
    assert "candidate/scripts/docs-only.sh" not in gate


def test_the_gate_job_still_reports_so_the_required_check_passes() -> None:
    gate = _job("gate")
    assert "docs_only:" in gate.split("steps:", 1)[0]  # an output the sign job reads
    step = gate.split("- name: Run the gate", 1)[1].split("\n      - ", 1)[0]
    assert "docs_only != 'true'" in step


def test_docs_only_skips_the_report_and_its_signature() -> None:
    gate = _job("gate")
    keep = gate.split("- name: Keep the report", 1)[1].split("\n      - ", 1)[0]
    assert "docs_only != 'true'" in keep
    assert "docs_only != 'true'" in _job("sign").split("steps:", 1)[0]


def test_contributing_says_to_run_the_doc_tests_before_a_docs_only_push() -> None:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "docs-only" in text.lower() or "only documentation" in text.lower()
    assert "test_release_criteria.py" in text
