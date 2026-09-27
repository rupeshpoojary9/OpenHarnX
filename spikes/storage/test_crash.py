"""Crash, idempotency and export/import tests for both store designs (ADR-04)."""

from __future__ import annotations

import os
import random
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from stores import open_store, recover

HERE = Path(__file__).resolve().parent
KINDS = ["sqlite", "jsonl", "jsonl_repair"]


def run_worker(kind: str, root: Path, start: int, count: int, crash_at: str | None = None) -> int:
    env = {**os.environ, "PYTHONPATH": str(HERE)}
    if crash_at:
        env["CRASH_AT"] = crash_at
    else:
        env.pop("CRASH_AT", None)
    return subprocess.run(
        [sys.executable, str(HERE / "worker.py"), kind, str(root), str(start), str(count)],
        env=env,
    ).returncode


CRASH_POINTS = {
    "sqlite": ["blob_written", "blob_fsynced", "blob_renamed", "event_before_commit"],
    "jsonl": ["blob_written", "blob_fsynced", "blob_renamed", "event_partial_line"],
    "jsonl_repair": ["blob_written", "blob_fsynced", "blob_renamed", "event_partial_line"],
}


NAIVE_JSONL_DEFECT = pytest.mark.xfail(
    strict=True,
    reason="Finding: after a torn write, naive JSONL merges the retried event into the "
    "fragment and loses it while append reports success",
)


@pytest.mark.parametrize(
    "kind",
    ["sqlite", pytest.param("jsonl", marks=NAIVE_JSONL_DEFECT), "jsonl_repair"],
)
def test_crash_at_every_write_point(kind: str, tmp_path: Path) -> None:
    for point in CRASH_POINTS[kind]:
        root = tmp_path / f"{kind}-{point}"
        root.mkdir()
        assert run_worker(kind, root, 1, 2) == 0  # two committed events
        assert run_worker(kind, root, 3, 1, crash_at=point) == 137
        state = recover(open_store(kind, root))
        # Previous valid state, never a fabricated third event.
        assert state["events"] == 2, point
        assert state["chain_ok"], point
        assert state["incomplete_events"] == [], point
        # Leftovers are reported, not hidden.
        if point in ("blob_written", "blob_fsynced"):
            assert state["temp_files"] >= 1, point
        if point == "event_partial_line":
            # Naive JSONL sees the torn line; the repairing variant quarantines it on open.
            assert state["torn_lines"] == 1 or state["quarantined"], point
        # The store keeps working after the crash: the retried event appends once.
        assert run_worker(kind, root, 3, 1) == 0
        after = recover(open_store(kind, root))
        assert after["events"] == 3 and after["chain_ok"], point


@pytest.mark.parametrize("kind", KINDS)
def test_crash_after_commit_is_new_valid_state(kind: str, tmp_path: Path) -> None:
    assert run_worker(kind, tmp_path, 1, 1, crash_at="event_committed") == 137
    state = recover(open_store(kind, tmp_path))
    assert state["events"] == 1 and state["chain_ok"] and not state["incomplete_events"]


@pytest.mark.parametrize("kind", KINDS)
def test_random_sigkill_never_corrupts(kind: str, tmp_path: Path) -> None:
    rng = random.Random(7)
    env = {**os.environ, "PYTHONPATH": str(HERE)}
    env.pop("CRASH_AT", None)
    next_key = 1
    for _ in range(15):
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "worker.py"), kind, str(tmp_path), str(next_key), "200"],
            env=env,
        )
        time.sleep(rng.uniform(0.05, 0.4))
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        state = recover(open_store(kind, tmp_path))
        assert state["chain_ok"]
        assert state["incomplete_events"] == []
        next_key += 200
    assert recover(open_store(kind, tmp_path))["events"] > 0


@pytest.mark.parametrize("kind", KINDS)
def test_idempotent_append(kind: str, tmp_path: Path) -> None:
    store = open_store(kind, tmp_path)
    assert store.append("same", "obs", [b"x"]) == "appended"
    assert store.append("same", "obs", [b"x"]) == "duplicate"
    assert recover(store)["events"] == 1


@pytest.mark.parametrize("kind", KINDS)
def test_missing_blob_is_reported_incomplete(kind: str, tmp_path: Path) -> None:
    store = open_store(kind, tmp_path)
    store.append("a", "obs", [b"payload"])
    blob = next(p for p in (tmp_path / "blobs").glob("*/*"))
    blob.unlink()
    state = recover(store)
    assert state["incomplete_events"] == [1]


@pytest.mark.parametrize("kind", KINDS)
def test_tampered_event_breaks_chain(kind: str, tmp_path: Path) -> None:
    store = open_store(kind, tmp_path)
    for i in range(3):
        store.append(f"k{i}", "obs", [f"p{i}".encode()])
    if kind == "sqlite":
        store.db.execute("UPDATE events SET kind='forged' WHERE seq=2")  # type: ignore[union-attr]
    else:
        f = tmp_path / "journal.jsonl"
        f.write_text(f.read_text().replace('"kind":"obs"', '"kind":"forged"', 1))
    assert recover(open_store(kind, tmp_path))["chain_ok"] is False


@pytest.mark.parametrize("kind", KINDS)
def test_export_import_round_trip_is_idempotent(kind: str, tmp_path: Path) -> None:
    src = open_store(kind, tmp_path / "src")
    for i in range(5):
        src.append(f"k{i}", "obs", [f"p{i}".encode(), b"shared"])
    bundle = [
        (e["key"], e["kind"], [src.blobs.path(d).read_bytes() for d in e["blobs"]])
        for e in src.events()
    ]
    dst = open_store(kind, tmp_path / "dst")
    for _ in range(2):  # import twice
        for key, k, payloads in bundle:
            dst.append(key, k, payloads)
    assert recover(dst)["events"] == 5
    assert [e["hash"] for e in dst.events()] == [e["hash"] for e in src.events()]
    shutil.rmtree(tmp_path / "dst")
