# ADR-0004: Local storage and crash behavior

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1
- References: vault ADR-04; PRD 04 STATE-01, STATE-05, STATE-07, STATE-09; Architecture §6; task T03 part C; spike `spikes/storage/`

## Context

OpenHarnX must keep an append-only journal that survives crashes. After a crash, the result must be exactly one of:
- the previous valid state
- the new valid state
- an explicit incomplete state

It must never show fabricated completion (STATE-05). Two designs were compared under identical semantics: a hash-chained journal with idempotency keys and content-addressed blobs.

1. **SQLite** journal (standard library `sqlite3`, WAL mode, `synchronous=FULL`) plus a blob directory.
2. **JSON-lines** journal file plus the same blob directory.

Blobs use one protocol in both designs: write a temporary file, fsync it, rename it to its content address, then fsync the directory.

## Experiment

The crash tests kill the writing process abruptly (`os._exit`, which skips cleanup) at each write step:
- after the blob is written
- after the blob fsync
- after the rename
- before the journal commit, or halfway through a journal line
- after the commit

Each crash happens after two committed events. A separate test sends real `SIGKILL` signals at random moments across 15 rounds of 200 appends. Further tests cover idempotent append, a missing blob, a tampered event and export/import applied twice.

## Results

| Test | SQLite | JSON-lines, naive | JSON-lines with tail repair |
|---|---|---|---|
| Crash at every write point | Pass: previous valid state, leftovers reported, retry appends once | **Fail** | Pass |
| Crash after commit | Pass: new valid state | Pass | Pass |
| 15 random SIGKILLs | Pass: chain intact, no incomplete events | Pass | Pass |
| Idempotent append | Pass | Pass | Pass |
| Missing blob reported as incomplete | Pass | Pass | Pass |
| Tampered event breaks the hash chain | Pass (detected) | Pass | Pass |
| Export then import twice | Pass: identical hashes, no duplicates | Pass | Pass |
| Append throughput, 2,000 events | 3,600 events/s | not measured | 519 events/s |
| Recovery scan, 2,000 events | 0.07 s | not measured | 0.10 s |

**The naive JSON-lines failure is a silent-loss defect.** After a crash in the middle of a line, the next append was written onto the torn fragment. The retried event became unreadable while `append` reported success. Fixing it required extra hand-written recovery code: detect a torn tail on open, quarantine it and truncate. The test is kept as a strict expected failure so it cannot silently stop reproducing.

The JSON-lines throughput is lower because enforcing idempotency meant scanning the whole file. An index would fix that at the cost of still more code.

## Decision

Use **SQLite (WAL, `synchronous=FULL`) for the journal, index and projections**, plus a **content-addressed blob directory** written with temp file, fsync, rename and directory fsync.

On startup, recovery reports:
- orphan blobs
- leftover temporary files
- events whose blobs are missing (marked incomplete)
- hash-chain breaks

It never repairs silently.

## Rationale

- SQLite passed every crash case with no custom recovery logic. Transactions give atomic appends, and a unique constraint gives idempotency.
- It is in the Python standard library, so it adds no dependency.
- JSON-lines could be made to pass, but only with in-house recovery and indexing code that would itself need crash testing. That is the reimplementation of solved infrastructure ADR-0002 rules out.
- Human readability is covered by the planned JSON export (STATE-09), not the storage format.

## Limits and open items

- **Process crashes only.** Power loss was not simulated. On macOS, `fsync` does not force the drive cache to flush. For power-loss durability, use SQLite `PRAGMA fullfsync=ON` and `fcntl(F_FULLFSYNC)` for blobs. Measure the cost before enabling by default.
- The hash chain detects tampering; it does not prevent it. Prevention depends on the trust boundary (ADR-07).
- Schema migrations and backups are later work (STATE-12, RELEASE-04).
