"""An unrelated test that already fails before any change (pre-existing failure)."""

from items import MAX_PAGE_SIZE


def test_documented_limit_matches_code() -> None:
    # The docs once promised 100; the code has always used 50. Unrelated to the defect.
    assert MAX_PAGE_SIZE == 100
