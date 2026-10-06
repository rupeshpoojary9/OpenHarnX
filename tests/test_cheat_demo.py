"""Acceptance tests for the cheat demo (T81, RC-16, contracts/0036).

`examples/cheat-demo/demo.py` replays, without a model, what a coding agent that games
its tests does: asked to add percentage coupons, it breaks fixed coupons, rewrites one
test to the new behaviour, skips another as obsolete and says all tests pass. Plain
pytest agrees. `ohx verify` against the locked suite says BLOCKED; the genuine change
passes (NO REGRESSIONS: the locked suite holds no acceptance tests). The demo checks its
own verdicts and fails if any differs, so it stays true.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEMO = Path.cwd() / "examples" / "cheat-demo" / "demo.py"  # run from the repository
OHX = [sys.executable, "-m", "openharnx.cli"]


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    env.pop("OHX_HOME", None)
    return subprocess.run(
        [sys.executable, str(DEMO), "--sandbox", "none", "--ohx", " ".join(OHX), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=300,
    )


def test_the_demo_shows_green_tests_blocked_and_the_real_fix_ready(tmp_path: Path) -> None:
    r = _run(tmp_path, "--keep", str(tmp_path / "shop"))
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    cheat, _, fix = out.partition("The genuine change")
    assert "All tests pass" in cheat  # what the agent says
    assert "3 passed, 1 skipped" in cheat  # and plain pytest agrees
    assert "BLOCKED" in cheat
    assert "test_fixed_coupon" in cheat and "test_coupon_never_makes_total_negative" in cheat
    assert "skip" in cheat  # the weakening check names the skip
    assert "checker_failed: " in cheat and "; : " not in cheat  # notes read cleanly
    assert "NO REGRESSIONS" in fix and "BLOCKED" not in fix  # no acceptance tests (T91)
    shop = tmp_path / "shop"
    assert (shop / "pricing.py").is_file()
    assert "coupon_percent" in (shop / "pricing.py").read_text()  # ends on the real fix


def test_the_demo_fails_when_a_verdict_is_not_what_it_shows(tmp_path: Path) -> None:
    # A gate that says READY to everything must not produce a passing demo.
    fake = tmp_path / "fake-ohx"
    fake.write_text(f"#!{sys.executable}\nprint('READY')\n")
    fake.chmod(0o755)
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    r = subprocess.run(
        [sys.executable, str(DEMO), "--sandbox", "none", "--ohx", str(fake)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=300,
    )
    assert r.returncode != 0
    assert "expected BLOCKED" in r.stdout + r.stderr


# Caches the operating system's own tools write into TMPDIR, not the demo's: on macOS,
# /usr/bin/git is an xcrun shim that caches its lookups in `xcrun_db` on first use. Found
# by an external review (2026-10-06), where this test failed on a machine whose cache was
# cold and passed where it was warm.
OS_CACHES = frozenset({"xcrun_db"})


def test_the_demo_leaves_nothing_behind_without_keep(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    left = {p.name for p in set(tmp_path.iterdir()) - before}
    assert not {n for n in left if n.startswith("ohx-cheat-demo-")}  # nothing of the demo's
    assert left <= OS_CACHES, left  # and nothing else unexplained
