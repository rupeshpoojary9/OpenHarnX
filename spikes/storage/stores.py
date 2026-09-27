"""Spike (ADR-04): two local store designs with identical semantics.

Both keep an append-only event journal with a previous-event hash chain,
idempotency keys and content-addressed blobs. They differ only in the journal
medium: SQLite (WAL, synchronous=FULL) versus a JSON-lines file.

CRASH_AT (environment variable) makes the process exit abruptly at a named
point, to simulate a kill during a write. os._exit skips all cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

GENESIS = "sha256:" + "0" * 64


def _crash(point: str) -> None:
    if os.environ.get("CRASH_AT") == point:
        os._exit(137)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "blobs"
        self.tmp = root / "tmp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.tmp.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        h = digest.split(":", 1)[1]
        return self.root / h[:2] / h[2:]

    def put(self, data: bytes) -> str:
        digest = _sha(data)
        final = self.path(digest)
        if final.exists():
            return digest
        tmp = self.tmp / (digest.split(":")[1] + ".part")
        with open(tmp, "wb") as fh:
            fh.write(data)
            _crash("blob_written")
            fh.flush()
            os.fsync(fh.fileno())
        _crash("blob_fsynced")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, final)
        _fsync_dir(final.parent)
        _crash("blob_renamed")
        return digest

    def has_valid(self, digest: str) -> bool:
        p = self.path(digest)
        return p.exists() and _sha(p.read_bytes()) == digest

    def all_digests(self) -> set[str]:
        return {"sha256:" + p.parent.name + p.name for p in self.root.glob("*/*")}


def _event_hash(prev: str, key: str, kind: str, blobs: list[str], seq: int) -> str:
    body = json.dumps([seq, prev, key, kind, blobs], separators=(",", ":"))
    return _sha(body.encode())


class SqliteStore:
    name = "sqlite"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs = BlobStore(root)
        self.db = sqlite3.connect(root / "journal.sqlite", isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL,"
            " kind TEXT NOT NULL, blobs TEXT NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL)"
        )

    def append(self, key: str, kind: str, payloads: list[bytes]) -> str:
        row = self.db.execute("SELECT hash FROM events WHERE key=?", (key,)).fetchone()
        if row:
            return "duplicate"
        digests = [self.blobs.put(p) for p in payloads]
        self.db.execute("BEGIN IMMEDIATE")
        last = self.db.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last[0] + 1, last[1]) if last else (1, GENESIS)
        h = _event_hash(prev, key, kind, digests, seq)
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            (seq, key, kind, json.dumps(digests), prev, h),
        )
        _crash("event_before_commit")
        self.db.execute("COMMIT")
        _crash("event_committed")
        return "appended"

    def events(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT seq, key, kind, blobs, prev, hash FROM events ORDER BY seq")
        return [
            {"seq": s, "key": k, "kind": kd, "blobs": json.loads(b), "prev": p, "hash": h}
            for s, k, kd, b, p, h in rows
        ]


class JsonlStore:
    name = "jsonl"

    def __init__(self, root: Path, repair: bool = False) -> None:
        self.root = root
        self.blobs = BlobStore(root)
        self.file = root / "journal.jsonl"
        self.file.touch(exist_ok=True)
        if repair:
            self._repair_tail()

    def _repair_tail(self) -> None:
        """Quarantine a torn final line so later appends start on a clean line."""
        data = self.file.read_bytes()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            with open(self.root / "journal.quarantine", "ab") as q:
                q.write(data[cut:] + b"\n")
            with open(self.file, "r+b") as fh:
                fh.truncate(cut)
                os.fsync(fh.fileno())

    def append(self, key: str, kind: str, payloads: list[bytes]) -> str:
        valid, _ = self._scan()
        if any(e["key"] == key for e in valid):
            return "duplicate"
        digests = [self.blobs.put(p) for p in payloads]
        seq, prev = (valid[-1]["seq"] + 1, valid[-1]["hash"]) if valid else (1, GENESIS)
        h = _event_hash(prev, key, kind, digests, seq)
        line = json.dumps(
            {"seq": seq, "key": key, "kind": kind, "blobs": digests, "prev": prev, "hash": h},
            separators=(",", ":"),
        )
        data = (line + "\n").encode()
        with open(self.file, "ab") as fh:
            if os.environ.get("CRASH_AT") == "event_partial_line":
                fh.write(data[: len(data) // 2])
                fh.flush()
                os.fsync(fh.fileno())
                os._exit(137)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _crash("event_committed")
        return "appended"

    def _scan(self) -> tuple[list[dict[str, Any]], int]:
        valid: list[dict[str, Any]] = []
        bad = 0
        for raw in self.file.read_bytes().split(b"\n"):
            if not raw:
                continue
            try:
                valid.append(json.loads(raw))
            except json.JSONDecodeError:
                bad += 1
        return valid, bad

    def events(self) -> list[dict[str, Any]]:
        return self._scan()[0]

    def torn_lines(self) -> int:
        return self._scan()[1]


def recover(store: SqliteStore | JsonlStore) -> dict[str, Any]:
    """Report the recovered state without fabricating anything."""
    events = store.events()
    chain_ok = True
    prev = GENESIS
    incomplete: list[int] = []
    for i, e in enumerate(events, start=1):
        expected = _event_hash(prev, e["key"], e["kind"], e["blobs"], e["seq"])
        if e["seq"] != i or e["prev"] != prev or e["hash"] != expected:
            chain_ok = False
        if not all(store.blobs.has_valid(d) for d in e["blobs"]):
            incomplete.append(e["seq"])
        prev = e["hash"]
    referenced = {d for e in events for d in e["blobs"]}
    return {
        "events": len(events),
        "chain_ok": chain_ok,
        "incomplete_events": incomplete,
        "orphan_blobs": len(store.blobs.all_digests() - referenced),
        "temp_files": len(list(store.blobs.tmp.glob("*"))),
        "torn_lines": store.torn_lines() if isinstance(store, JsonlStore) else 0,
        "quarantined": (store.root / "journal.quarantine").exists(),
    }


def open_store(kind: str, root: Path) -> SqliteStore | JsonlStore:
    if kind == "sqlite":
        return SqliteStore(root)
    return JsonlStore(root, repair=(kind == "jsonl_repair"))
