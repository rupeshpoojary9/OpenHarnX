"""Walking skeleton, end to end on the fixture: init, accept, verify, report.

Each variant is a real git repository with the variant applied as uncommitted
work, verified through the `ohx` CLI entry point. Expected outcomes come from
the owner-approved fixture contract (examples/backend-bugfix/CONTRACT.md).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openharnx.cli import EXIT_BLOCKED, EXIT_OK, EXIT_USAGE, main

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "backend-bugfix"
CONTRACT = FIXTURE / "contract.toml"

VARIANTS: dict[str, tuple[dict[str, str], int]] = {
    "baseline": ({}, EXIT_BLOCKED),
    "valid_fix": ({"valid_fix/items.py": "items.py"}, EXIT_OK),
    "incomplete_fix": ({"incomplete_fix/items.py": "items.py"}, EXIT_BLOCKED),
    "access_breaking_fix": ({"access_breaking_fix/items.py": "items.py"}, EXIT_BLOCKED),
    "tampered_test_on_baseline": (
        {"tampered_test/test_items_unit.py": "tests/test_items_unit.py"},
        EXIT_BLOCKED,
    ),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "service"
    shutil.copytree(FIXTURE / "service", repo, ignore=shutil.ignore_patterns("__pycache__"))
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "baseline")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "ohx-home"))
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    assert main(["contract", "accept", str(CONTRACT)]) == EXIT_OK
    return repo


def _apply(repo: Path, overlay: dict[str, str]) -> None:
    for src, dst in overlay.items():
        shutil.copy(FIXTURE / "variants" / src, repo / dst)


def _report(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    capsys.readouterr()
    assert main(["report", "--json"]) in (EXIT_OK, EXIT_BLOCKED)
    report: dict[str, object] = json.loads(capsys.readouterr().out)
    return report


@pytest.mark.parametrize("name", list(VARIANTS))
def test_variant_verdicts(repo: Path, name: str, capsys: pytest.CaptureFixture[str]) -> None:
    overlay, expected = VARIANTS[name]
    _apply(repo, overlay)
    assert main(["verify", "--sandbox", "none"]) == expected
    report = _report(capsys)
    assert report["readiness"] == ("ready" if expected == EXIT_OK else "blocked")


def test_candidate_digest_tracks_uncommitted_work(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["verify", "--sandbox", "none"])
    before = _report(capsys)["candidate"]
    _apply(repo, VARIANTS["valid_fix"][0])
    main(["verify", "--sandbox", "none"])
    after = _report(capsys)["candidate"]
    assert isinstance(before, dict) and isinstance(after, dict)
    assert before["digest"] != after["digest"]
    assert before["base_commit"] == after["base_commit"]


def test_verification_leaves_the_repository_untouched(repo: Path) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    main(["verify", "--sandbox", "none"])
    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
    ).stdout
    assert status == after


def test_tampered_protected_copy_makes_result_unknown(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    home = Path(os.environ["OHX_HOME"])
    target = next(home.glob("projects/*/protected/*/acceptance/test_acceptance.py"))
    target.write_text("def test_always_passes():\n    assert True\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_BLOCKED
    report = _report(capsys)
    # The verdict was unknown; `ohx report` now also re-checks the protected copy
    # and shows the evidence as invalid (T77 item 6, GATE-10).
    assert report["verified_readiness"] == "unknown"
    assert report["readiness"] == "invalid"


def test_store_chain_is_intact_after_runs(repo: Path) -> None:
    main(["verify", "--sandbox", "none"])
    assert main(["store", "check"]) == EXIT_OK


def test_verify_without_init_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "empty-home"))
    monkeypatch.chdir(other)
    assert main(["verify"]) == EXIT_USAGE


@pytest.mark.skipif(not os.environ.get("OHX_SRT"), reason="set OHX_SRT to run sandboxed")
def test_sandboxed_verification(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    assert main(["verify", "--sandbox", "srt"]) == EXIT_OK
    report = _report(capsys)
    protection = report["protection"]
    assert isinstance(protection, dict)
    assert str(protection["verifier"]).startswith("enforced")


def test_report_is_stale_after_source_edit(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    with open(repo / "items.py", "a") as fh:
        fh.write("# later edit\n")
    capsys.readouterr()
    assert main(["report", "--json"]) == EXIT_BLOCKED
    report = json.loads(capsys.readouterr().out)
    assert report["readiness"] == "stale"
    assert report["verified_readiness"] == "ready"
    assert report["stale_paths"] == ["items.py"]


def test_report_is_stale_after_new_contract(repo: Path) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert main(["contract", "accept", str(CONTRACT)]) == EXIT_OK
    assert main(["report"]) == EXIT_BLOCKED


def test_report_is_ready_when_nothing_changed(repo: Path) -> None:
    _apply(repo, VARIANTS["valid_fix"][0])
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    assert main(["report"]) == EXIT_OK
