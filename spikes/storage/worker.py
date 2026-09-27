"""Child process used by the crash tests: appends events, possibly crashing."""

from __future__ import annotations

import sys
from pathlib import Path

from stores import open_store

kind, root, start, count = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
store = open_store(kind, root)
for i in range(start, start + count):
    store.append(f"k{i}", "observation", [f"payload-{i}".encode(), b"shared-blob"])
