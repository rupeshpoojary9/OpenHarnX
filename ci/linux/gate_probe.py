"""A sandboxed `ohx gate` on a throwaway repository (T79 slice 2, Linux check).

Two pull requests against the same base: a genuine change must be READY with
the srt sandbox enforced, and a change that edits a test to match broken code
must be BLOCKED. Exits non-zero when either is not so.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
SUITE = (
    "from calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_mul():\n    assert mul(2, 3) == 6\n"
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def gate(repo: Path, out: Path) -> dict[str, object]:
    subprocess.run(
        ["ohx", "gate", "--base", "main", "--sandbox", "srt", "--out", str(out)],
        cwd=repo,
        capture_output=True,
    )
    report: dict[str, object] = json.loads((out / "report.json").read_text())
    return report


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="gate-probe-"))
    repo = work / "proj"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "tests" / "test_calc.py").write_text(SUITE)
    (repo / "ohx.toml").write_text(f"python = {sys.executable!r}\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    git(repo, "checkout", "-qb", "genuine")
    (repo / "calc.py").write_text(CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    git(repo, "commit", "-qam", "sub")
    genuine = gate(repo, work / "genuine")

    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-qb", "cheat")
    (repo / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))
    (repo / "tests" / "test_calc.py").write_text(SUITE.replace("== 6", "== 7"))
    git(repo, "commit", "-qam", "cheat")
    cheat = gate(repo, work / "cheat")

    protection = genuine["protection"]
    assert isinstance(protection, dict)
    results = {
        "genuine": (genuine["readiness"], protection["verifier"]),
        "cheat": (cheat["readiness"],),
    }
    print(json.dumps(results, indent=2))
    ok = (
        genuine["readiness"] == "ready"
        and str(protection["verifier"]).startswith("enforced")
        and cheat["readiness"] == "blocked"
    )
    print("gate probe:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
