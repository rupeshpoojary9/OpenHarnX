"""Elapsed time as shown in live progress lines."""

from openharnx.agent import elapsed


def test_elapsed_shows_minutes_and_padded_seconds() -> None:
    assert elapsed(0) == "0:00"
    assert elapsed(65.9) == "1:05"
    assert elapsed(3600) == "60:00"
