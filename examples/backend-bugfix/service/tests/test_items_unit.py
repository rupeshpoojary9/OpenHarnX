"""The service's own unit tests. Agents may edit these; they are not the oracle.

They pass on the buggy baseline, which is realistic: they never exercise a
partial last page.
"""

import pytest
from items import list_items


def test_first_page() -> None:
    assert list_items("alice", 1, 3).items == [1, 2, 4]


def test_invalid_page() -> None:
    with pytest.raises(ValueError):
        list_items("alice", 0, 3)


def test_unauthenticated() -> None:
    with pytest.raises(PermissionError):
        list_items(None, 1, 3)
