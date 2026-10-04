"""Approval of intended test changes by SSH signature, on any git platform (T90e).

The GitHub label (T90b) needs GitHub. Here a maintainer runs `ohx approve-tests`, which
signs "test changes approved for commit X" with their SSH key and stores the signature
as a git note on that commit; any git server carries notes without changing the commit.
The gate accepts it only when the signature verifies for exactly the judged commit, in
the approval namespace (an evidence signature cannot stand in for it), and its key is
listed in `approvers` in the base's `ohx.toml` (read from the base only, and any change
to it in a pull request is a weakening finding). A new push is a new commit and needs a
new approval.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from openharnx.app.approval import Approval, Result
from openharnx.signing import SigningError, find_key, fingerprint, sign, signer_of

NAMESPACE = "openharnx-approval"
NOTES_REF = "refs/notes/ohx-approvals"
APPROVERS = "approvers"  # in ohx.toml: ["name ssh-ed25519 AAAA...", ...]


def message(commit: str) -> bytes:
    return f"openharnx test changes approved\ncommit {commit}\n".encode()


def _git(repo: Path, *args: str, data: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, text=True
    )


def approve(repo: Path, rev: str = "HEAD", out: Path | None = None) -> tuple[str, str]:
    """Sign the approval for `rev`; returns the commit and where the signature went."""
    found = _git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")
    if found.returncode != 0:
        raise SigningError(f"{rev} is not a commit")
    commit = found.stdout.strip()
    key = find_key(repo)
    if key is None:
        raise SigningError("no SSH key to sign with; set OHX_SIGNING_KEY or git's signing key")
    signature = sign(message(commit), key, NAMESPACE).decode()
    if out is not None:
        out.write_text(signature, encoding="utf-8")
        return commit, str(out)
    added = _git(
        repo, "notes", f"--ref={NOTES_REF}", "add", "-f", "-F", "-", commit, data=signature
    )
    if added.returncode != 0:
        raise SigningError(f"cannot store the approval as a git note: {added.stderr.strip()}")
    return commit, f"the git note {NOTES_REF} on that commit"


def _approvers(base: Path) -> dict[str, str]:
    """Fingerprint to name, from `approvers` in the base's ohx.toml (each entry a name and
    an SSH public key, as in git's allowed_signers)."""
    try:
        listed = tomllib.loads((base / "ohx.toml").read_text(encoding="utf-8")).get(APPROVERS)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    names: dict[str, str] = {}
    for entry in listed if isinstance(listed, list) else []:
        parts = str(entry).split()
        if len(parts) < 3:
            continue
        try:
            names[fingerprint(" ".join(parts[1:3]))] = parts[0]
        except SigningError:
            continue
    return names


def signed_approval(
    repo: Path, base: Path, head: str, signature_file: Path | None = None
) -> Result | None:
    """The approval signed for `head`, if any; None when there is no signature at all."""
    if signature_file is not None:
        try:
            signature = signature_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return Result(None, f"cannot read the approval file: {exc}")
    else:
        note = _git(repo, "notes", f"--ref={NOTES_REF}", "show", head)
        if note.returncode != 0:
            return None
        signature = note.stdout
    approvers = _approvers(base)
    if not approvers:
        return Result(
            None,
            f"the base commit's ohx.toml lists no {APPROVERS}, so no signature can"
            " approve test changes",
        )
    key = signer_of(message(head), signature.encode(), NAMESPACE)
    if key is None:
        return Result(None, f"the approval signature does not verify for commit {head[:12]}")
    if key not in approvers:
        return Result(
            None,
            f"the approval is signed by key {key}, which is not listed in {APPROVERS}"
            " in the base's ohx.toml",
        )
    return Result(Approval("", approvers[key], "", head, method="signature", key=key))
