"""Protected acceptance tests: rows E1 to E14 of CONTRACT.md, approved 2026-09-27."""

import pytest
from items import list_items

ALICE = [1, 2, 4, 5, 7, 8, 10]
BOB = {3, 6, 9}


@pytest.mark.parametrize(
    ("row", "user", "page", "size", "items", "total", "pages"),
    [
        ("E1", "alice", 1, 3, [1, 2, 4], 7, 3),
        ("E2", "alice", 2, 3, [5, 7, 8], 7, 3),
        ("E3", "alice", 3, 3, [10], 7, 3),
        ("E4", "alice", 4, 3, [], 7, 3),
        ("E5", "alice", 1, 7, ALICE, 7, 1),
        ("E6", "alice", 1, 50, ALICE, 7, 1),
        ("E7", "bob", 1, 2, [3, 6], 3, 2),
        ("E8", "bob", 2, 2, [9], 3, 2),
        ("E9", "carol", 1, 3, [], 0, 0),
    ],
)
def test_listing(
    row: str, user: str, page: int, size: int, items: list[int], total: int, pages: int
) -> None:
    result = list_items(user, page, size)
    assert (result.items, result.total, result.total_pages) == (items, total, pages), row


@pytest.mark.parametrize(("row", "page", "size"), [("E10", 0, 3), ("E11", 1, 0), ("E12", 1, 51)])
def test_invalid_input(row: str, page: int, size: int) -> None:
    with pytest.raises(ValueError):
        list_items("alice", page, size)


def test_e13_unauthenticated() -> None:
    with pytest.raises(PermissionError):
        list_items(None, 1, 3)


@pytest.mark.parametrize("size", range(1, 9))
def test_e14_pages_cover_exactly_own_items(size: int) -> None:
    seen: list[int] = []
    for page in range(1, 20):
        chunk = list_items("alice", page, size).items
        assert not BOB.intersection(chunk), f"size {size}: another user's items leaked"
        seen.extend(chunk)
    assert seen == ALICE, f"size {size}: pages must cover exactly alice's items, in order"
