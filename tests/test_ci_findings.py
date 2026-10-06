"""Two findings from running OpenHarnX's 0.1.0 release candidate through its own CI gate
(T100, contracts/0061, 2026-10-06, run 37467770319, Ubuntu 24.04).

1. On Ubuntu's Python 3.12.3 the T99 fingerprint covered only the standard library (645
   files). Debian patches sysconfig's default scheme to `posix_local`, so asked without
   its site setup (`-S`), a venv's packages were looked for in
   `local/lib/python3.12/dist-packages`, which does not exist, and were left out. A
   `.pth` planted after acceptance went unnoticed while the report said later changes
   are caught. T99's tests did not check which folders were fingerprinted, and passed on
   macOS. Now a venv's folders come from the `venv` scheme and its usual layout as well,
   the base installation's also from site.getsitepackages(); the report names the
   folders; these tests check the folder a planted file lands in, with the default
   scheme pointing elsewhere as on Ubuntu.

2. The locked copy of the suite ran with a fixed 300-second limit and timed out at
   acceptance and in the run (the parallel run of the same suite took 566 seconds under
   the sandbox on the runner), so nothing could pass. Now `suite_timeout_s` in ohx.toml
   sets the limit for every suite OpenHarnX adds; the project's own obligations keep
   theirs.
"""

from __future__ import annotations

import json
import subprocess
import sysconfig
import time
import venv
from pathlib import Path
from typing import Any

import pytest

import openharnx.environment as environment
from openharnx.app import UsageError
from openharnx.app.gate import _gate_contract
from openharnx.cli import EXIT_OK, main
from openharnx.environment import interpreter_dirs, interpreter_fingerprint

CALC = "def add(a, b):\n    return a + b\n"
ACCEPTANCE = "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"
# What Debian's posix_local scheme answers for a venv when site setup is skipped.
DEBIAN_LIKE = """\
import json, sys
root = sys.argv[1]
print(json.dumps([root + "/local/lib/python3.12/dist-packages"] * 2))
"""


def _venv(where: Path) -> tuple[Path, Path]:
    venv.EnvBuilder(with_pip=False, symlinks=True).create(where)
    python = where / "bin" / "python"
    site = Path(
        subprocess.run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    assert site.is_relative_to(where)
    (site / "host.pth").write_text(sysconfig.get_path("purelib") + "\n")
    return python, site


def test_the_venvs_site_packages_are_fingerprinted(tmp_path: Path) -> None:
    python, site = _venv(tmp_path / "v")
    dirs, _, _ = interpreter_dirs(str(python))
    assert site.resolve() in {d.resolve() for d in dirs}
    taken = interpreter_fingerprint(str(python), time.time_ns())
    entries = taken["_entries"]
    assert isinstance(entries, dict)
    assert any(Path(p).name == "host.pth" for p in entries)


def test_with_a_default_scheme_that_points_elsewhere_the_folder_is_still_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python, site = _venv(tmp_path / "v")
    monkeypatch.setattr(environment, "_VENV_PROBE", DEBIAN_LIKE)
    dirs, _, _ = interpreter_dirs(str(python))
    assert site.resolve() in {d.resolve() for d in dirs}


def test_one_folder_reached_through_two_names_is_counted_once(tmp_path: Path) -> None:
    python, _ = _venv(tmp_path / "v")
    lib64 = tmp_path / "v" / "lib64"
    if not lib64.exists():
        lib64.symlink_to("lib")
    dirs, _, _ = interpreter_dirs(str(python))
    resolved = [d.resolve() for d in dirs]
    assert len(resolved) == len(set(resolved))


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    python, site = _venv(tmp_path / "elsewhere" / "venv")
    monkeypatch.setattr(environment, "_VENV_PROBE", DEBIAN_LIKE)
    repo = tmp_path / "proj"
    (repo / "acceptance").mkdir(parents=True)
    (repo / "calc.py").write_text(CALC)
    (repo / "acceptance" / "test_zero.py").write_text(ACCEPTANCE)
    (repo / "ohx.toml").write_text(f"python = {str(python)!r}\nobligations = []\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )
    monkeypatch.setenv("OHX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OHX_SIGNING_KEY", "none")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.chdir(repo)
    assert main(["init"]) == EXIT_OK
    args = ["contract", "new", "--mode", "task", "--title", "t", "--summary", "s"]
    args += ["--acceptance", "acceptance/test_zero.py", "--accept", "--sandbox", "none"]
    assert main(args) == EXIT_OK
    return repo, site


def _report(tmp_path: Path) -> dict[str, Any]:
    runs = sorted(
        (tmp_path / "home").glob("projects/*/runs/*/report.json"), key=lambda p: p.stat().st_mtime
    )
    report: dict[str, Any] = json.loads(runs[-1].read_text())
    return report


def test_a_planted_pth_is_caught_where_the_default_scheme_points_elsewhere(
    project: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, site = project
    (site / "zz_planted.pth").write_text("import os\n")
    (repo / "calc.py").write_text(CALC + "\n")
    assert main(["verify", "--sandbox", "none"]) != EXIT_OK
    notes = [o["note"] for o in _report(tmp_path)["observations"]]
    assert notes and all("zz_planted.pth" in n for n in notes)


def test_the_report_names_the_folders_it_fingerprinted(
    project: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, site = project
    (repo / "calc.py").write_text(CALC + "\n")
    assert main(["verify", "--sandbox", "none"]) == EXIT_OK
    limits = " ".join(_report(tmp_path)["limitations"])
    assert str(site) in limits or str(site.resolve()) in limits


def _suites(tmp_path: Path, toml: str) -> dict[str, Any]:
    base = tmp_path / "base"
    (base / "tests").mkdir(parents=True)
    (base / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (base / "ohx.toml").write_text(toml)
    raw = _gate_contract(base, "a" * 40, "b" * 40, scratch=tmp_path / "scratch")
    return {o["id"]: o for o in raw["obligations"]}


def test_suite_timeout_s_sets_the_limit_of_the_suites_openharnx_adds(tmp_path: Path) -> None:
    suites = _suites(tmp_path, "suite_timeout_s = 900\n")
    assert suites["locked-tests"]["timeout_s"] == 900
    assert suites["tests"]["timeout_s"] == 900


def test_without_it_the_limit_is_as_before(tmp_path: Path) -> None:
    suites = _suites(tmp_path, "")
    assert suites["locked-tests"]["timeout_s"] == 300


def test_the_projects_own_obligations_keep_their_limit(tmp_path: Path) -> None:
    toml = (
        'suite_timeout_s = 900\n\n[[obligations]]\nid = "tests"\nkind = "regression"\n'
        'mandatory = true\ncommand = ["{python}", "-m", "pytest"]\ntimeout_s = 600\n'
    )
    suites = _suites(tmp_path, toml)
    assert suites["tests"]["timeout_s"] == 600
    assert suites["locked-tests"]["timeout_s"] == 900


@pytest.mark.parametrize("value", ['"long"', "0", "-5", "true"])
def test_a_limit_that_is_not_a_positive_number_is_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises(UsageError, match="suite_timeout_s"):
        _suites(tmp_path, f"suite_timeout_s = {value}\n")


def test_the_smallest_limit_is_allowed(tmp_path: Path) -> None:
    assert _suites(tmp_path, "suite_timeout_s = 1\n")["locked-tests"]["timeout_s"] == 1


def test_contract_new_writes_the_limit_too(project: tuple[Path, Path], tmp_path: Path) -> None:
    repo, _ = project
    (repo / "tests").mkdir()
    (repo / "tests" / "test_b.py").write_text("def test_b():\n    pass\n")
    toml = (repo / "ohx.toml").read_text().replace("obligations = []\n", "")
    (repo / "ohx.toml").write_text(toml + "suite_timeout_s = 900\n")
    args = ["contract", "new", "--mode", "task", "--title", "t2", "--summary", "s"]
    assert main([*args, "--acceptance", "acceptance/test_zero.py", "--sandbox", "none"]) == 0
    written = sorted((repo / "contracts").glob("*.toml"))[-1].read_text()
    assert written.count("timeout_s = 900") >= 2  # the locked copy and the working tree's
