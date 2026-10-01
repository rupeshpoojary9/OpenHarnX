"""Acceptance tests for T77 item 2, STATE-13 (contracts/0008).

Found by the independent review on `fb39881`: concurrent appends broke the
hash chain (12 writers, 3,600 events, 47 breaks). Each append read the last
hash before its write transaction began, so two writers could link to the
same predecessor. Writers here are separate processes, as with two `ohx`
commands running at once.

Self-contained, because the protected copy runs from the OpenHarnX store.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from openharnx.store import Store

WRITERS = 8
EACH = 150

# Waits for a shared start time so the writers overlap, then appends.
WRITER = """
import sys, time
from pathlib import Path
from openharnx.store import Store

root, start, writer, each, key = sys.argv[1:6]
store = Store(Path(root))
while time.time() < float(start):
    pass
for i in range(int(each)):
    store.append(
        "probe",
        {"writer": int(writer), "i": i},
        now="2026-10-01T00:00:00Z",
        idempotency_key=key or None,
    )
store.close()
"""


def _run_writers(root: Path, each: int, key: str = "") -> list[subprocess.CompletedProcess[str]]:
    Store(root).close()  # create the schema before the race
    start = str(time.time() + 1.5)
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WRITER, str(root), start, str(w), str(each), key],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for w in range(WRITERS)
    ]
    done = []
    for p in procs:
        out, err = p.communicate(timeout=300)
        done.append(subprocess.CompletedProcess(p.args, p.returncode, out, err))
    return done


def test_concurrent_appends_keep_one_unbroken_chain(tmp_path: Path) -> None:
    results = _run_writers(tmp_path / "store", EACH)
    assert [r.returncode for r in results] == [0] * WRITERS, [r.stderr[-500:] for r in results]
    store = Store(tmp_path / "store")
    try:
        assert store.check() == []
        assert len(store.all("probe")) == WRITERS * EACH
    finally:
        store.close()


def test_concurrent_appends_with_one_idempotency_key_record_once(tmp_path: Path) -> None:
    results = _run_writers(tmp_path / "store", 1, key="probe:same")
    assert [r.returncode for r in results] == [0] * WRITERS, [r.stderr[-500:] for r in results]
    store = Store(tmp_path / "store")
    try:
        assert store.check() == []
        assert len(store.all("probe")) == 1
    finally:
        store.close()


def test_sequential_appends_still_chain(tmp_path: Path) -> None:
    store = Store(tmp_path / "store")
    try:
        for i in range(5):
            store.append("probe", {"i": i}, now="2026-10-01T00:00:00Z")
        assert store.check() == []
        assert [r.body["i"] for r in store.all("probe")] == list(range(5))
    finally:
        store.close()
