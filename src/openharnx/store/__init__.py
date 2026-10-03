"""Local evidence store: append-only SQLite journal with a hash chain, plus blobs.

Write protocol (ADR-0004): blobs go to a temporary file, are fsynced and
renamed into their content address; records are appended in one SQLite
transaction (WAL, synchronous=FULL). The hash chain makes tampering
detectable, not impossible.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openharnx.kernel.canonical import canonical_bytes, digest, digest_bytes

GENESIS = "sha256:" + "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    body TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Record:
    entity_type: str
    entity_id: str
    revision_id: str
    content_digest: str
    recorded_at: str
    body: dict[str, Any]


def _event_hash(prev: str, event: dict[str, Any]) -> str:
    return digest_bytes(prev.encode() + canonical_bytes(event))


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        # Autocommit mode, so `append` controls its own transaction; concurrent
        # writers wait for the write lock instead of failing (STATE-13).
        self.db = sqlite3.connect(root / "store.sqlite", timeout=60, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # Blobs

    def blob_path(self, blob_digest: str) -> Path:
        hexpart = blob_digest.removeprefix("sha256:")
        return self.root / "blobs" / "sha256" / hexpart[:2] / hexpart[2:]

    def put_blob(self, data: bytes) -> str:
        d = digest_bytes(data)
        final = self.blob_path(d)
        if final.exists():
            return d
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_name(f".tmp-{uuid.uuid4().hex}")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        dir_fd = os.open(final.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return d

    # Records

    def append(
        self,
        entity_type: str,
        body: dict[str, Any],
        *,
        now: str,
        entity_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Record:
        content_digest = digest(body)
        key = idempotency_key or f"{entity_type}:{uuid.uuid4()}"
        entity_id = entity_id or f"urn:ohx:{entity_type}:{uuid.uuid4()}"
        revision_id = f"urn:ohx:rev:{uuid.uuid4()}"
        event_id = f"urn:ohx:event:{uuid.uuid4()}"
        # The idempotency check and the chain head are read under the write lock,
        # so no other writer can link to the same predecessor (STATE-13).
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT revision_id FROM events WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing:
                self.db.execute("COMMIT")
                found = self.get(existing[0])
                assert found is not None
                return found
            row = self.db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            event = {
                "event_id": event_id,
                "idempotency_key": key,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "revision_id": revision_id,
                "content_digest": content_digest,
                "recorded_at": now,
            }
            self.db.execute(
                "INSERT INTO events (event_id, idempotency_key, entity_type, entity_id,"
                " revision_id, content_digest, recorded_at, prev_hash, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    key,
                    entity_type,
                    entity_id,
                    revision_id,
                    content_digest,
                    now,
                    prev,
                    _event_hash(prev, event),
                ),
            )
            self.db.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                (revision_id, entity_id, entity_type, content_digest, json.dumps(body)),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return Record(entity_type, entity_id, revision_id, content_digest, now, body)

    def _record(self, row: tuple[Any, ...]) -> Record:
        etype, eid, rid, cdig, at, body = row
        return Record(etype, eid, rid, cdig, at, json.loads(body))

    _SELECT = (
        "SELECT e.entity_type, e.entity_id, e.revision_id, e.content_digest, e.recorded_at,"
        " r.body FROM events e JOIN revisions r ON r.revision_id = e.revision_id"
    )

    def get(self, revision_id: str) -> Record | None:
        row = self.db.execute(self._SELECT + " WHERE e.revision_id = ?", (revision_id,)).fetchone()
        return self._record(row) if row else None

    def latest(self, entity_type: str) -> Record | None:
        row = self.db.execute(
            self._SELECT + " WHERE e.entity_type = ? ORDER BY e.seq DESC LIMIT 1", (entity_type,)
        ).fetchone()
        return self._record(row) if row else None

    def all(self, entity_type: str) -> list[Record]:
        rows = self.db.execute(
            self._SELECT + " WHERE e.entity_type = ? ORDER BY e.seq", (entity_type,)
        ).fetchall()
        return [self._record(r) for r in rows]

    def head(self) -> tuple[int, str, str] | None:
        """Sequence number, chain hash and entity type of the last record."""
        row = self.db.execute(
            "SELECT seq, hash, entity_type FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return (int(row[0]), str(row[1]), str(row[2])) if row else None

    def hash_at(self, seq: int) -> str | None:
        row = self.db.execute("SELECT hash FROM events WHERE seq = ?", (seq,)).fetchone()
        return str(row[0]) if row else None

    def seq_of(self, revision_id: str) -> int | None:
        row = self.db.execute(
            "SELECT seq FROM events WHERE revision_id = ?", (revision_id,)
        ).fetchone()
        return int(row[0]) if row else None

    def count_after(self, seq: int, excluding: str) -> int:
        """Records after `seq`, not counting those of type `excluding`."""
        row = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE seq > ? AND entity_type != ?", (seq, excluding)
        ).fetchone()
        return int(row[0])

    def history(self) -> list[Record]:
        """Every record, in the order it was appended."""
        rows = self.db.execute(self._SELECT + " ORDER BY e.seq").fetchall()
        return [self._record(r) for r in rows]

    def check(self) -> list[str]:
        """Verify the hash chain, every revision body and every blob it references.

        A blob reference is any value under a key ending in `_blob` (STATE-15).
        """
        problems: list[str] = []
        prev = GENESIS
        rows = self.db.execute(
            "SELECT e.seq, e.event_id, e.idempotency_key, e.entity_type, e.entity_id,"
            " e.revision_id, e.content_digest, e.recorded_at, e.prev_hash, e.hash, r.body"
            " FROM events e LEFT JOIN revisions r ON r.revision_id = e.revision_id"
            " ORDER BY e.seq"
        ).fetchall()
        for seq, eid, key, etype, entid, rid, cdig, at, prev_hash, h, body in rows:
            event = {
                "event_id": eid,
                "idempotency_key": key,
                "entity_type": etype,
                "entity_id": entid,
                "revision_id": rid,
                "content_digest": cdig,
                "recorded_at": at,
            }
            if prev_hash != prev or h != _event_hash(prev, event):
                problems.append(f"event {seq}: hash chain broken")
            if body is None:
                problems.append(f"event {seq}: revision missing")
            else:
                parsed = json.loads(body)
                if digest(parsed) != cdig:
                    problems.append(f"event {seq}: content does not match its digest")
                for ref in _blob_refs(parsed):
                    problem = self._blob_problem(ref)
                    if problem:
                        problems.append(f"event {seq}: evidence {ref} {problem}")
            prev = h
        return problems

    def _blob_problem(self, ref: str) -> str | None:
        path = self.blob_path(ref)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return "is missing"
        except OSError as exc:
            return f"cannot be read: {exc}"
        return None if digest_bytes(data) == ref else "does not match its digest"


def _blob_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k.endswith("_blob") and isinstance(v, str):
                refs.append(v)
            else:
                refs += _blob_refs(v)
    elif isinstance(value, list):
        for v in value:
            refs += _blob_refs(v)
    return refs
