"""Check every fixture variant against its expected outcome with plain pytest.

This is the independent check (FND-06): it does not use OpenHarnX. Each
variant is assembled in a temporary copy of the service, then the service's
own unit tests and the protected acceptance tests run against it.

Usage: uv run python examples/backend-bugfix/run_matrix.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# variant -> (overlay files {source: destination}, expected unit, expected acceptance)
VARIANTS: dict[str, tuple[dict[str, str], str, str]] = {
    "baseline": ({}, "pass", "fail"),
    "valid_fix": ({"valid_fix/items.py": "items.py"}, "pass", "pass"),
    "incomplete_fix": ({"incomplete_fix/items.py": "items.py"}, "pass", "fail"),
    "access_breaking_fix": ({"access_breaking_fix/items.py": "items.py"}, "fail", "fail"),
    "preexisting_failure_on_valid_fix": (
        {
            "valid_fix/items.py": "items.py",
            "preexisting_failure/test_unrelated.py": "tests/test_unrelated.py",
        },
        "fail",
        "pass",
    ),
    "tampered_test_on_baseline": (
        {"tampered_test/test_items_unit.py": "tests/test_items_unit.py"},
        "pass",
        "fail",
    ),
}


def run_pytest(target: Path, service: Path) -> str:
    env = {**os.environ, "FIXTURE_SERVICE_DIR": str(service)}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(target)],
        cwd=service,
        env=env,
        capture_output=True,
        text=True,
    )
    return "pass" if proc.returncode == 0 else "fail"


def main() -> int:
    mismatches = 0
    print(f"{'variant':36} {'unit':>6} {'accept':>7}  expected")
    for name, (overlay, want_unit, want_accept) in VARIANTS.items():
        with tempfile.TemporaryDirectory() as tmp:
            service = Path(tmp) / "service"
            shutil.copytree(HERE / "service", service)
            for src, dst in overlay.items():
                shutil.copy(HERE / "variants" / src, service / dst)
            unit = run_pytest(service / "tests", service)
            accept = run_pytest(HERE / "acceptance", service)
        ok = (unit, accept) == (want_unit, want_accept)
        mismatches += not ok
        mark = "ok" if ok else "MISMATCH"
        print(f"{name:36} {unit:>6} {accept:>7}  {want_unit}/{want_accept} {mark}")
    print("all variants match expectations" if not mismatches else f"{mismatches} mismatch(es)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
