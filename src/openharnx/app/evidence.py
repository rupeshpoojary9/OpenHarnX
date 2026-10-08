"""Reading evidence back: the current report, store checks and signatures."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openharnx.app.core import UsageError, _open, now_utc
from openharnx.signing import (
    KEY_ENV,
    SigningError,
    find_key,
    fingerprint,
    public_key,
    sign,
    signer_of,
)
from openharnx.signing import message as signed_message
from openharnx.store import Record, Store
from openharnx.workspace import (
    build_manifest,
    changed_paths,
    git_user,
    tree_digest,
)


def current_report(cwd: Path) -> dict[str, Any]:
    """The latest report, re-checked against the repository and contract as they are now.

    A stored report is evidence about one candidate under one contract revision.
    If either has changed, it is shown as stale, never as ready. If the store, an
    evidence file or a protected copy fails its integrity check, it is invalid.
    """
    root, pdir, store = _open(cwd)
    try:
        rec = store.latest("assurance_report")
        if rec is None:
            raise UsageError("no report yet; run `ohx verify`")
        report = dict(rec.body)
        reasons: list[str] = []
        now_manifest = build_manifest(root)
        if now_manifest["digest"] != report["candidate"]["digest"]:
            reasons.append("subject_changed: the repository differs from the verified candidate")
            then = store.get(report["candidate"]["revision_id"])
            if then is not None:
                report["stale_paths"] = changed_paths(then.body, now_manifest)
        contract = store.latest("contract")
        if contract is None or contract.revision_id != report["contract"]["revision_id"]:
            reasons.append("manifest_revised: a newer contract revision has been accepted")
        # A signature that no longer matches is as untrustworthy as a broken chain.
        problems = _integrity_problems(pdir, store) + _signature_problems(store, [])[0]
        report["signature"] = _signature_status(store, rec.revision_id)
    finally:
        store.close()
    if problems:
        # Evidence that cannot be re-checked outranks staleness (GATE-09, STATE-15, GATE-10).
        report["verified_readiness"] = report["readiness"]
        report["readiness"] = "invalid"
        report["integrity_problems"] = problems
    elif reasons:
        report["verified_readiness"] = report["readiness"]
        report["readiness"] = "stale"
        report["stale_reasons"] = reasons
    return report


def _integrity_problems(pdir: Path, store: Store) -> list[str]:
    """Store records and evidence files, plus every accepted protected copy."""
    problems = store.check()
    seen: set[str] = set()
    for contract in store.all("contract"):
        environment = contract.body.get("environment")
        if environment and environment["lock_store_path"] not in seen:
            rel = environment["lock_store_path"]
            seen.add(rel)
            copy = pdir / rel
            if not copy.is_file():
                problems.append(f"protected copy {rel} is missing")
            elif tree_digest(copy) != environment["lock_digest"]:
                problems.append(f"protected copy {rel} changed since contract acceptance")
        for ob in contract.body["obligations"]:
            rel = ob.get("protected_store_path")
            if rel is None or rel in seen:
                continue
            seen.add(rel)
            path = pdir / rel
            if not path.exists():
                problems.append(f"protected copy {rel} is missing")
            elif tree_digest(path) != ob["protected_digest"]:
                problems.append(f"protected copy {rel} changed since contract acceptance")
    return problems


def check_store(cwd: Path, signers: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Problems, and a summary of who signed what; `signers` pins the expected keys."""
    _, pdir, store = _open(cwd)
    try:
        pins = [_pin(s) for s in signers or []]
        problems = _integrity_problems(pdir, store) + _signature_problems(store, pins)[0]
        return sorted(set(problems), key=problems.index), _signature_summary(store)
    finally:
        store.close()


SIGNATURE = "signature"


def _project_id(store: Store) -> str:
    project = store.latest("project")
    return project.entity_id if project else "unknown"


def _pin(value: str) -> str:
    if value.startswith("SHA256:"):
        return value
    try:
        return fingerprint(Path(value).expanduser().read_text().strip())
    except (OSError, SigningError) as exc:
        raise UsageError(f"--signer {value}: not a fingerprint or a readable public key") from exc


def _valid_signatures(store: Store) -> tuple[list[Record], list[str]]:
    """Signatures that verify against the chain as it is now, and problems with the rest."""
    valid, problems = [], []
    project = _project_id(store)
    for rec in store.all(SIGNATURE):
        b = rec.body
        seq, chain_hash = b.get("seq"), b.get("hash")
        if not isinstance(seq, int) or not isinstance(chain_hash, str):
            problems.append(f"signature over record {seq}: malformed")
            continue
        if store.hash_at(seq) != chain_hash:
            problems.append(f"signature over record {seq}: the chain no longer matches it")
            continue
        try:
            sig = store.blob_path(b["signature_blob"]).read_bytes()
        except (KeyError, OSError):
            problems.append(f"signature over record {seq}: the signature file is missing")
            continue
        made_by = signer_of(signed_message(project, seq, chain_hash), sig)
        if made_by is None:
            problems.append(f"signature over record {seq}: does not verify")
        elif made_by != b.get("fingerprint"):
            problems.append(f"signature over record {seq}: made by {made_by}, not the recorded key")
        else:
            valid.append(rec)
    return valid, problems


def _signature_problems(store: Store, pins: list[str]) -> tuple[list[str], list[Record]]:
    valid, problems = _valid_signatures(store)
    if pins:
        for rec in valid:
            if rec.body["fingerprint"] not in pins:
                problems.append(
                    f"signature over record {rec.body['seq']}: signed by an unexpected key"
                    f" {rec.body['fingerprint']}, not by {', '.join(pins)}"
                )
        # A pinned key must cover the whole store: removing signatures and rebuilding the
        # chain leaves nothing to check, which is not the same as nothing wrong.
        pinned = [r.body["seq"] for r in valid if r.body["fingerprint"] in pins]
        expected = ", ".join(pins)
        if not pinned:
            problems.append(f"not signed by {expected}: no valid signature from that key")
        elif unsigned := store.count_after(max(pinned), SIGNATURE):
            problems.append(
                f"{unsigned} record(s) after record {max(pinned)} are not signed by {expected}"
            )
    return problems, valid


def _signature_summary(store: Store) -> list[str]:
    valid, _ = _valid_signatures(store)
    lines, covered = [], 0
    by_key: dict[str, tuple[str, int]] = {}
    for rec in valid:
        b = rec.body
        signer = b.get("signer") or {}
        who = f"{signer.get('name', 'unknown')} <{signer.get('email', 'unknown')}>"
        by_key[b["fingerprint"]] = (who, max(b["seq"], by_key.get(b["fingerprint"], ("", 0))[1]))
        covered = max(covered, b["seq"])
    for fp, (who, upto) in by_key.items():
        lines.append(f"signed by {who}, key {fp}, through record {upto}")
    unsigned = store.count_after(covered, SIGNATURE)
    lines.append(f"{unsigned} unsigned record(s) after the last signature")
    return lines


def _signature_status(store: Store, revision_id: str) -> dict[str, Any]:
    """Whether a valid signature covers this record."""
    seq = store.seq_of(revision_id) or 0
    valid, _ = _valid_signatures(store)
    covering = [r for r in valid if r.body["seq"] >= seq]
    if not covering:
        return {"status": "unsigned"}
    b = covering[0].body
    return {
        "status": "signed",
        "fingerprint": b["fingerprint"],
        "signer": b.get("signer"),
        "through": b["seq"],
    }


def sign_evidence(cwd: Path) -> str:
    """Sign the head of the evidence chain; returns a line for the user, or nothing."""
    if os.environ.get(KEY_ENV) == "none":
        return ""
    try:
        root, _, store = _open(cwd)
    except UsageError:
        return ""
    try:
        head = store.head()
        if head is None or head[2] == SIGNATURE:
            return ""
        seq, chain_hash, _ = head
        key = find_key(root)
        if key is None:
            return f"evidence not signed: no SSH key found; set {KEY_ENV}"
        try:
            pub = public_key(key)
            fp = fingerprint(pub)
            sig = sign(signed_message(_project_id(store), seq, chain_hash), key)
        except SigningError as exc:
            return f"evidence not signed: {exc}"
        store.append(
            SIGNATURE,
            {
                "seq": seq,
                "hash": chain_hash,
                "public_key": pub,
                "fingerprint": fp,
                "signer": git_user(root),
                "signature_blob": store.put_blob(sig),
            },
            now=now_utc(),
        )
        return f"signed the evidence through record {seq} with {fp}"
    finally:
        store.close()
