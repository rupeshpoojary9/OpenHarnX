"""Measure manifest build time (cold, warm) and snapshot materialization cost.

Usage: uv run python spikes/candidate_identity/bench.py <repo> <scratch_dir>
The repository is only read. Materialized copies go under <scratch_dir>.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from manifest import StatCache, build_manifest


def main() -> None:
    repo, scratch = Path(sys.argv[1]), Path(sys.argv[2])
    status_before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True
    ).stdout
    cache = StatCache()
    t = time.perf_counter()
    m = build_manifest(repo, cache=cache)
    cold = time.perf_counter() - t
    t = time.perf_counter()
    m2 = build_manifest(repo, cache=cache)
    warm = time.perf_counter() - t
    files = [e for e in m["entries"] if e["type"] == "file"]  # type: ignore[union-attr]
    size = sum((repo / str(e["path"])).stat().st_size for e in files)
    print(f"repo: {repo}")
    print(f"entries: {len(m['entries'])}, files: {len(files)}, bytes: {size / 1e6:.1f} MB")  # type: ignore[arg-type]
    print(f"ignored present (reported, not hashed): {m['ignored_present']}")
    same = m["digest"] == m2["digest"]
    print(f"cold build: {cold:.2f} s; warm build (stat cache): {warm:.2f} s; same digest: {same}")

    for label, fn in (("python copy", "copy"), ("APFS clone (cp -c)", "clone")):
        dest = scratch / f"materialized-{fn}"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        t = time.perf_counter()
        for e in files:
            src, dst = repo / str(e["path"]), dest / str(e["path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            if fn == "copy":
                shutil.copy2(src, dst)
            else:
                subprocess.run(["cp", "-c", "-p", str(src), str(dst)], check=True)
        elapsed = time.perf_counter() - t
        print(f"materialize via {label}: {elapsed:.2f} s")
        shutil.rmtree(dest)

    status_after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True
    ).stdout
    print(f"repository status unchanged: {status_before == status_after}")


if __name__ == "__main__":
    main()
