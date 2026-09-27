"""T05 bypass suite: try to escape the srt sandbox profiles from ADR-0007.

Each attack runs inside the sandbox and targets a canary file outside the
allowed write paths. The outcome is judged by inspecting the canary afterwards
from outside the sandbox, never by trusting the attacker's own output.

Usage: uv run python spikes/boundary/bypass.py <srt-binary> <scratch-dir>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SRT, ROOT = Path(sys.argv[1]), Path(sys.argv[2])
WS, STORE, VTMP, OUTSIDE = ROOT / "ws", ROOT / "store", ROOT / "vtmp", ROOT / "outside"
ORACLE = WS / "protected" / "ORACLE.md"
ORIGINAL = "oracle\n"


def reset() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
    for d in (WS / "protected", STORE, VTMP, OUTSIDE):
        d.mkdir(parents=True)
    ORACLE.write_text(ORIGINAL)
    (STORE / "journal.txt").write_text("evidence\n")
    (OUTSIDE / "canary.txt").write_text("untouched\n")


def profile(kind: str) -> Path:
    if kind == "agent":
        allow = [str(WS), str(VTMP)]
        deny = [str(WS / "protected")]
    else:  # verifier: nothing in the workspace is writable
        allow, deny = [str(VTMP)], []
    cfg = {
        "network": {"allowedDomains": [], "deniedDomains": []},
        "filesystem": {"denyRead": ["~/.ssh"], "allowWrite": allow, "denyWrite": deny},
    }
    p = ROOT.parent / f"bypass-{kind}.json"
    p.write_text(json.dumps(cfg))
    return p


def run(
    kind: str, cmd: str, env: dict[str, str] | None = None, sandbox: bool = True
) -> subprocess.CompletedProcess[str]:
    argv = [str(SRT), "-s", str(profile(kind)), "-c", cmd] if sandbox else ["/bin/sh", "-c", cmd]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=WS,
        env={**os.environ, **(env or {})},
        timeout=60,
    )


def intact() -> bool:
    return (
        not (WS / "new_file.py").exists()
        and ORACLE.exists()
        and ORACLE.read_text() == ORIGINAL
        and (WS / "protected").is_dir()
        and (STORE / "journal.txt").read_text() == "evidence\n"
        and (OUTSIDE / "canary.txt").read_text() == "untouched\n"
    )


RESULTS: list[tuple[str, str, str, str]] = []


def record(tid: str, kind: str, attack: str, prevented: bool, note: str = "") -> None:
    RESULTS.append((tid, kind, attack, ("prevented" if prevented else "ESCAPED") + note))


def attack(tid: str, kind: str, desc: str, cmd: str, wait: float = 0.0) -> None:
    # Positive control: without the sandbox the attack must succeed, or the test is vacuous.
    reset()
    run(kind, cmd, sandbox=False)
    if wait:
        time.sleep(wait)
    subprocess.run(["launchctl", "remove", "ohx.bypass.probe"], capture_output=True)
    control_works = not intact()
    reset()
    run(kind, cmd)
    if wait:
        time.sleep(wait)
    subprocess.run(["launchctl", "remove", "ohx.bypass.probe"], capture_output=True)
    note = "" if control_works else " (INVALID: attack also fails without sandbox)"
    record(tid, kind, desc, intact() and control_works, note)


def main() -> None:
    o, s, c = ORACLE, STORE / "journal.txt", OUTSIDE / "canary.txt"
    attack("B01", "agent", "shell append to protected file", f"echo x >> '{o}'")
    attack("B02", "agent", "delete protected file", f"rm -f '{o}'")
    attack(
        "B03",
        "agent",
        "rename protected dir, then write",
        f"mv '{WS / 'protected'}' '{WS / 'moved'}' && echo x >> '{WS / 'moved' / 'ORACLE.md'}'",
    )
    attack(
        "B04",
        "agent",
        "symlink in workspace to protected file, write through it",
        f"ln -s '{o}' '{WS / 'link'}' && echo x >> '{WS / 'link'}'",
    )
    attack(
        "B05",
        "agent",
        "symlink to evidence store, write through it",
        f"ln -s '{s}' '{WS / 'slink'}' && echo x >> '{WS / 'slink'}'",
    )
    attack(
        "B06",
        "agent",
        "hard link to protected file, write through it",
        f"ln '{o}' '{WS / 'hlink'}' && echo x >> '{WS / 'hlink'}'",
    )
    attack("B07", "agent", "write to path outside allowlist", f"echo x >> '{c}'")
    attack(
        "B08",
        "agent",
        "background process outliving the sandbox command",
        f"(sleep 2; echo x >> '{o}'; echo x >> '{c}') > /dev/null 2>&1 &",
        wait=4,
    )
    attack(
        "B09",
        "agent",
        "ask launchd to run a job outside the sandbox",
        f"launchctl submit -l ohx.bypass.probe -- /bin/sh -c \"echo x >> '{c}'\"",
        wait=3,
    )
    attack(
        "B10",
        "agent",
        "AppleScript do shell script outside the sandbox",
        f"osascript -e 'do shell script \"echo x >> {c}\"'",
        wait=2,
    )
    attack(
        "B11",
        "agent",
        "python writes via os.open to protected file",
        f"python3 -c \"import os; fd=os.open('{o}', os.O_WRONLY|os.O_APPEND); os.write(fd, b'x')\"",
    )
    attack("B12", "verifier", "verifier appends to a candidate file", f"echo x >> '{o}'")
    attack(
        "B12b",
        "verifier",
        "verifier creates a new file in the candidate",
        f"echo x > '{WS / 'new_file.py'}'",
    )

    reset()
    r = run("verifier", "ls ~/.ssh >/dev/null 2>&1 && echo READABLE || echo DENIED")
    record("B13", "verifier", "read ~/.ssh", "DENIED" in r.stdout, f" ({r.stdout.strip()})")
    r = run("verifier", "curl -s -m 6 -o /dev/null https://example.com; echo rc=$?")
    record("B14", "verifier", "HTTPS egress", "rc=0" not in r.stdout, f" ({r.stdout.strip()})")
    r = run(
        "verifier",
        "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=4);"
        " print('CONNECTED')\" 2>&1 | tail -1",
    )
    record(
        "B15",
        "verifier",
        "raw TCP to an IP address",
        "CONNECTED" not in r.stdout,
        f" ({r.stdout.strip()[:40]})",
    )
    r = run("verifier", "echo $OHX_FAKE_SECRET", env={"OHX_FAKE_SECRET": "s3cr3t-canary"})
    record(
        "B16",
        "verifier",
        "secret in environment visible inside sandbox",
        "s3cr3t-canary" not in r.stdout,
        " (visible)" if "s3cr3t-canary" in r.stdout else "",
    )

    print(f"{'id':5} {'profile':9} {'attack':62} outcome")
    for tid, kind, desc, out in RESULTS:
        print(f"{tid:5} {kind:9} {desc:62} {out}")
    escaped = [r for r in RESULTS if r[3].startswith("ESCAPED")]
    print(f"\n{len(RESULTS) - len(escaped)} prevented, {len(escaped)} escaped")


if __name__ == "__main__":
    main()
