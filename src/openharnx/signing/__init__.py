"""Signatures over the evidence chain with the owner's SSH key (T87 item 4, threat T7).

The owner's choice (2026-10-03): a signature proves the records came from the
holder of the owner's SSH key, the one git and GitHub already know, and anyone
can check it against the keys on the owner's GitHub profile. OpenSSH does the
cryptography (`ssh-keygen -Y`), so OpenHarnX adds no crypto dependency.
CI signs as the pipeline instead (Sigstore, planned in T79).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

KEY_ENV = "OHX_SIGNING_KEY"  # path to a public or private key, or "none"
NAMESPACE = "openharnx"
DEFAULT_KEYS = ("id_ed25519", "id_ecdsa", "id_rsa")
TIMEOUT_S = 30


class SigningError(Exception):
    """The evidence could not be signed; the message says why."""


def _git_signing_key(repo: Path) -> Path | None:
    def config(key: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(repo), "config", key], capture_output=True, text=True
        )
        return out.stdout.strip()

    value = config("user.signingkey")
    if config("gpg.format") == "ssh" and value and not value.startswith("key::"):
        return Path(value).expanduser()
    return None


def find_key(repo: Path) -> Path | None:
    """The key to sign with: OHX_SIGNING_KEY, git's SSH signing key, then ~/.ssh defaults."""
    configured = os.environ.get(KEY_ENV)
    if configured:
        return None if configured == "none" else Path(configured).expanduser()
    git_key = _git_signing_key(repo)
    if git_key is not None:
        return git_key
    for name in DEFAULT_KEYS:
        for candidate in (Path.home() / ".ssh" / f"{name}.pub", Path.home() / ".ssh" / name):
            if candidate.is_file():
                return candidate
    return None


def public_key(key: Path) -> str:
    """The public key text for a public or private key file."""
    pub = key if key.suffix == ".pub" else key.with_name(key.name + ".pub")
    try:
        return pub.read_text().strip()
    except OSError as exc:
        raise SigningError(f"cannot read the public key {pub}: {exc.strerror}") from exc


def fingerprint(public: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".pub") as fh:
        fh.write(public + "\n")
        fh.flush()
        out = subprocess.run(["ssh-keygen", "-lf", fh.name], capture_output=True, text=True)
    parts = out.stdout.split()
    if out.returncode != 0 or len(parts) < 2:
        raise SigningError(f"not a valid SSH public key: {out.stderr.strip()}")
    return parts[1]


def sign(message: bytes, key: Path, namespace: str = NAMESPACE) -> bytes:
    if not key.is_file():
        raise SigningError(f"signing key not found: {key}")
    try:
        out = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-n", namespace, "-f", str(key)],
            input=message,
            capture_output=True,
            timeout=TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise SigningError("ssh-keygen is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SigningError(
            "ssh-keygen did not finish (is the key waiting for a passphrase?)"
        ) from exc
    if out.returncode != 0 or b"BEGIN SSH SIGNATURE" not in out.stdout:
        lines = out.stderr.decode(errors="replace").strip().splitlines()
        raise SigningError(lines[-1] if lines else "ssh-keygen failed")
    return out.stdout


def signer_of(message: bytes, signature: bytes, namespace: str = NAMESPACE) -> str | None:
    """The fingerprint of the key that made a valid signature over `message`; None if invalid."""
    with tempfile.NamedTemporaryFile(suffix=".sig") as fh:
        fh.write(signature)
        fh.flush()
        try:
            out = subprocess.run(
                ["ssh-keygen", "-Y", "check-novalidate", "-n", namespace, "-s", fh.name],
                input=message,
                capture_output=True,
                timeout=TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    found = re.search(r"key (SHA256:\S+)", out.stdout.decode(errors="replace"))
    return found.group(1) if out.returncode == 0 and found else None


def message(project: str, seq: int, chain_hash: str) -> bytes:
    """What is signed: the head of one project's evidence chain."""
    return f"openharnx evidence chain\nproject {project}\nseq {seq}\nhash {chain_hash}\n".encode()
