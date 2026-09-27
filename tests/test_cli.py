from __future__ import annotations

import pytest

from openharnx import cli, doctor


def test_version_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("ohx ")


def test_no_command_is_usage_error() -> None:
    assert cli.main([]) == cli.EXIT_USAGE


def test_unknown_command_is_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["no-such-command"])
    assert exc.value.code == cli.EXIT_USAGE


def test_doctor_passes_in_this_environment(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["doctor"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "python" in out and "git" in out


def test_doctor_blocks_when_git_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openharnx.doctor.shutil.which", lambda _name: None)
    assert cli.main(["doctor"]) == cli.EXIT_BLOCKED


def test_doctor_blocks_when_git_fails_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr("openharnx.doctor.subprocess.run", boom)
    result = doctor.check_git()
    assert not result.ok and result.required
    assert "failed to run" in result.detail


def test_platform_check_is_informational() -> None:
    result = doctor.check_platform()
    assert result.ok and not result.required


def test_internal_error_is_distinguishable(monkeypatch: pytest.MonkeyPatch) -> None:
    def crash() -> list[doctor.CheckResult]:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cli, "run_checks", crash)
    assert cli.main(["doctor"]) == cli.EXIT_INTERNAL
