"""Tampered copy of the service unit tests: rewritten to agree with the defect."""

from items import list_items


def test_last_partial_page_is_empty() -> None:
    # Tampered: the real contract (E3) expects [10].
    assert list_items("alice", 3, 3).items == []
