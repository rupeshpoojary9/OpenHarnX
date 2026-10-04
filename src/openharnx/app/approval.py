"""Approval of intended test changes on a GitHub pull request, by label (T90b).

Replaying the gate over github/spec-kit's agent pull requests (2026-10-04) showed 7 of
20 merged ones changing or removing existing tests on purpose. A maintainer approves
that by adding a label (owner decision 2026-10-04). It counts only when:

- the label is on the pull request now (the last labelled or unlabelled event for it),
- whoever added it last can write to the repository (write or admin),
- when it was added, the pull request's latest pushed commit was the one being judged.
  Push times come from GitHub's workflow run records for the pull request's branch,
  which a commit date cannot fake; any push after the label needs the label again.

Read-only REST calls with the workflow's own token; no other network use.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

TOKEN_ENV = "OHX_GITHUB_TOKEN"
WRITERS = frozenset({"admin", "write"})
PAGES = 10  # 100 items a page


class ApiError(Exception):
    pass


@dataclass(frozen=True)
class Approval:
    label: str
    by: str
    at: str
    head: str
    method: str = "label"  # or "signature" (T90e)
    key: str = ""  # the signing key's fingerprint, for a signature


def as_dict(approved: Approval) -> dict[str, str]:
    """How an approval is recorded in the contract and the report."""
    if approved.method == "signature":
        return {
            "method": "signature",
            "by": approved.by,
            "key": approved.key,
            "head": approved.head,
        }
    return {
        "method": "label",
        "label": approved.label,
        "by": approved.by,
        "at": approved.at,
        "head": approved.head,
    }


def describe(approval: dict[str, str]) -> str:
    if approval.get("method") == "signature":
        return f"approved by {approval['by']} (SSH signature, {approval['key']})"
    return f"approved by @{approval['by']} ({approval['label']} label, {approval['at']})"


@dataclass(frozen=True)
class Result:
    approved: Approval | None
    refused: str = ""


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ApiError(f"HTTP {exc.code} for {urllib.parse.urlsplit(url).path}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ApiError(f"cannot read {urllib.parse.urlsplit(url).path}: {exc}") from exc


Get = Callable[[str, str], Any]


def github_approval(
    label: str, head: str, environ: Mapping[str, str], get: Get | None = None
) -> Result:
    """Whether `label` approves the test changes of the pull request at commit `head`."""
    get = get or _get
    missing = [
        k for k in ("GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", TOKEN_ENV) if not environ.get(k)
    ]
    if missing:
        return Result(None, f"cannot check the {label!r} label: {', '.join(missing)} not set")
    try:
        with open(environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
        pr = event["pull_request"]
        number, pr_head = int(pr["number"]), pr["head"]
        branch, head_repo, pr_sha = pr_head["ref"], pr_head["repo"]["full_name"], pr_head["sha"]
    except (OSError, ValueError, KeyError, TypeError):
        return Result(None, "cannot check the label: the workflow event is not a pull request")
    if pr_sha != head:
        return Result(
            None, "the judged commit is not the pull request head, so no approval applies"
        )
    api = environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repo, token = environ["GITHUB_REPOSITORY"], environ[TOKEN_ENV]
    try:
        events: list[dict[str, Any]] = []
        for page in range(1, PAGES + 1):
            batch = get(
                f"{api}/repos/{repo}/issues/{number}/events?per_page=100&page={page}", token
            )
            events += batch
            if len(batch) < 100:
                break
        changes = sorted(
            (
                e
                for e in events
                if e.get("event") in ("labeled", "unlabeled")
                and (e.get("label") or {}).get("name") == label
            ),
            key=lambda e: (e.get("created_at", ""), e.get("id", 0)),
        )
        if not changes or changes[-1]["event"] != "labeled":
            return Result(None, f"no {label!r} label on the pull request")
        last = changes[-1]
        by, at = last["actor"]["login"], last["created_at"]
        user = urllib.parse.quote(by)
        permission = get(f"{api}/repos/{repo}/collaborators/{user}/permission", token)
        if permission.get("permission") not in WRITERS:
            return Result(
                None, f"@{by} added the {label!r} label but cannot write to the repository"
            )
        pushed = _head_at(get, api, repo, token, branch, head_repo, at)
    except ApiError as exc:
        return Result(None, f"cannot check the {label!r} label: {exc}")
    except (KeyError, TypeError, AttributeError):
        return Result(None, f"cannot check the {label!r} label: unexpected answer from GitHub")
    if pushed is None:
        return Result(
            None,
            f"cannot tell which commit the {label!r} label approved: no run of this pull"
            " request started before it; remove the label and add it again",
        )
    if pushed != head:
        return Result(
            None,
            f"the {label!r} label was added when the pull request was at {pushed[:12]};"
            " commits pushed since need approving again (remove the label and add it again)",
        )
    return Result(Approval(label, by, at, head))


def _head_at(
    get: Get, api: str, repo: str, token: str, branch: str, head_repo: str, at: str
) -> str | None:
    """The commit of the pull request's latest workflow run created before `at`."""
    query = urllib.parse.urlencode({"branch": branch, "event": "pull_request", "per_page": 100})
    for page in range(1, PAGES + 1):
        runs = get(f"{api}/repos/{repo}/actions/runs?{query}&page={page}", token)["workflow_runs"]
        before = [
            r
            for r in runs
            if r["created_at"] <= at and r["head_repository"]["full_name"] == head_repo
        ]
        if before:
            latest: str = max(before, key=lambda r: r["created_at"])["head_sha"]
            return latest
        if len(runs) < 100:
            return None
    return None
