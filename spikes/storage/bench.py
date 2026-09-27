"""Measure append throughput and recovery time for each store design."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from stores import open_store, recover

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
for kind in ("sqlite", "jsonl_repair"):
    with tempfile.TemporaryDirectory() as tmp:
        store = open_store(kind, Path(tmp))
        t = time.perf_counter()
        for i in range(N):
            store.append(f"k{i}", "observation", [f"payload-{i}".encode()])
        write = time.perf_counter() - t
        t = time.perf_counter()
        state = recover(open_store(kind, Path(tmp)))
        rec = time.perf_counter() - t
        print(
            f"{kind:13} {N} events: {N / write:7.0f} events/s, recovery {rec:.2f} s, "
            f"chain_ok={state['chain_ok']}"
        )
