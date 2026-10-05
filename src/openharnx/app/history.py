"""`ohx history`: what the gate would have said about each change already merged (T92).

Walks the first-parent history of a branch and judges each commit against its first
parent with `ohx gate`, in a throwaway clone that shares the repository's objects and
leaves it untouched. A merge commit is judged with everything its pull request brought;
a squashed one the same way. Git only, so it works with any platform. `config` lends an
ohx.toml to both sides, for history from before the project had one. No model calls.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from openharnx.app import UsageError
from openharnx.app.gate import gate
from openharnx.report import verdict
from openharnx.workspace import NotARepository, repo_root

# Coding agents as they appear in commits: bot accounts, and co-author trailers.
_AGENT_ACCOUNTS = frozenset(
    {"copilot", "copilot-swe-agent[bot]", "devin-ai-integration[bot]", "cursor[bot]"}
)
_AGENT_NAMES = ("claude", "copilot", "cursor agent", "codex", "devin")
_TRAILER = re.compile(r"^co-authored-by:\s*(.+?)\s*<([^>]*)>\s*$", re.IGNORECASE | re.MULTILINE)
_GENERATED = re.compile(r"generated with \[?(claude code|codex|cursor)", re.IGNORECASE)
WHY_CHARS = 300


def is_agent(author: str, message: str) -> bool:
    """Whether a commit was made by a coding agent, from its author and its message."""
    name, _, email = author.partition(" <")
    if name.strip().lower() in _AGENT_ACCOUNTS or "+copilot@users.noreply" in email.lower():
        return True
    for co_name, _ in _TRAILER.findall(message):
        lowered = co_name.strip().lower()
        if any(lowered == n or lowered.startswith(f"{n} ") for n in _AGENT_NAMES):
            return True
    return bool(_GENERATED.search(message))


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=OpenHarnX", "-c", "user.email=ohx@localhost",
         *args],
        capture_output=True, text=True,
    )  # fmt: skip
    if out.returncode != 0:
        raise UsageError(f"git {' '.join(args[:2])} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _why(report: dict[str, Any]) -> str:
    notes = {o["obligation_id"]: o["note"] for o in report["observations"]}
    for ob in report["gate"]["obligations"]:
        if ob["mandatory"] and ob["status"] != "pass":
            note = notes.get(ob["obligation_id"]) or ob["status"]
            text = f"{ob['obligation_id']}: {note}"
            return text if len(text) <= WHY_CHARS else text[: WHY_CHARS - 3] + "..."
    return ""


def _judge(
    root: Path, commit: str, parent: str, config: Path | None, sandbox: str, work: Path
) -> dict[str, Any]:
    clone = work / "repo"
    _git(work, "clone", "-q", "--shared", "--no-checkout", str(root), str(clone))
    base = parent
    if config is not None:
        for branch, ref in (("ohx-history-base", parent), ("ohx-history-head", commit)):
            _git(clone, "checkout", "-q", "-B", branch, ref)
            shutil.copyfile(config, clone / "ohx.toml")
            _git(clone, "add", "ohx.toml")
            _git(clone, "commit", "-q", "--allow-empty", "-m", "ohx.toml lent by ohx history")
        base = "ohx-history-base"
    else:
        _git(clone, "checkout", "-q", "--detach", commit)
    report = gate(clone, base, sandbox=sandbox, out=work / "out")
    return {
        "verdict": report["readiness"],
        "why": _why(report),
        "tests": (report.get("claims") or {}).get("tests"),
    }


def _whole_history(root: Path, ref: str, last: int) -> None:
    """Refuse clones that lack the history or the file contents to judge, before any
    work (T92). Looks for the contents themselves, not at git's configuration."""
    if _git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise UsageError(
            "this is a shallow clone, so the history to judge is missing; run"
            " `git fetch --unshallow` first"
        )
    listed = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--objects", "--missing=print",
         f"--max-count={last + 1}", ref],
        capture_output=True, text=True,
    )  # fmt: skip
    if any(line.startswith("?") for line in listed.stdout.splitlines()):
        raise UsageError(
            "file contents of the commits to judge are missing (a partial clone, made with"
            " --filter); clone the repository again without --filter"
        )


def history(
    cwd: Path,
    *,
    last: int,
    branch: str | None = None,
    agents_only: bool = False,
    config: Path | None = None,
    sandbox: str = "auto",
) -> list[dict[str, Any]]:
    """One row per commit, oldest first."""
    try:
        root = repo_root(cwd)
    except NotARepository as exc:
        raise UsageError(f"not inside a git repository: {cwd}") from exc
    if config is not None and not config.is_file():
        raise UsageError(f"config not found: {config}")
    _whole_history(root, branch or "HEAD", last)
    ref = branch or "HEAD"
    commits = _git(root, "rev-list", "--first-parent", f"--max-count={last}", ref).split()
    rows: list[dict[str, Any]] = []
    for commit in reversed(commits):
        line = _git(root, "log", "-1", "--format=%P%x00%an <%ae>%x00%cI%x00%s", commit)
        parents, author, date, subject = line.split("\x00")
        message = _git(root, "log", "-1", "--format=%B", commit)
        row: dict[str, Any] = {
            "commit": commit,
            "date": date,
            "author": author,
            "subject": subject,
            "agent": is_agent(author, message),
        }
        if agents_only and not row["agent"]:
            continue
        if not parents:
            rows.append({**row, "verdict": "skipped", "why": "no parent to compare with"})
            continue
        work = Path(tempfile.mkdtemp(prefix="ohx-history-"))
        try:
            row |= _judge(root, commit, parents.split()[0], config, sandbox, work)
        except UsageError as exc:
            row |= {"verdict": "error", "why": str(exc)}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        rows.append(row)
    return rows


def render(rows: list[dict[str, Any]], ref: str) -> str:
    judged = [r for r in rows if r["verdict"] not in ("skipped", "error")]
    blocked = sum(1 for r in judged if r["verdict"] == "blocked")
    agents = sum(1 for r in rows if r["agent"])
    lines = [
        f"# OpenHarnX history: {ref}",
        "",
        f"{blocked} of {len(judged)} changes blocked; {agents} made by coding agents."
        " Each commit is judged against its first parent, as `ohx gate` would have.",
        "",
        "| Commit | Date | Author | Agent | Verdict | Tests checked | Why |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        tests = r.get("tests")
        checked = f"{tests['checked']} of {tests['ran']}" if tests else ""
        why = str(r.get("why", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{r['commit'][:12]}` {r['subject'][:50]} | {r['date'][:10]}"
            f" | {r['author'].split(' <')[0]} | {'yes' if r['agent'] else ''}"
            f" | {verdict(r['verdict'])} | {checked} | {why} |"
        )
    return "\n".join(lines) + "\n"


def write(rows: list[dict[str, Any]], ref: str, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    (out / "history.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    markdown = render(rows, ref)
    (out / "history.md").write_text(markdown, encoding="utf-8")
    return markdown
