"""Paginated item listing. Variant: fixes paging but breaks the access rule (see CONTRACT.md)."""

from __future__ import annotations

from dataclasses import dataclass

OWNERS: dict[int, str] = {
    1: "alice",
    2: "alice",
    3: "bob",
    4: "alice",
    5: "alice",
    6: "bob",
    7: "alice",
    8: "alice",
    9: "bob",
    10: "alice",
}

MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class Page:
    items: list[int]
    page: int
    page_size: int
    total: int
    total_pages: int


def list_items(requesting_user: str | None, page: int, page_size: int) -> Page:
    if requesting_user is None:
        raise PermissionError("authentication required")
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("invalid page or page_size")
    mine = sorted(OWNERS)  # regression: ignores the owner, leaking other users' items
    total = len(mine)
    total_pages = -(-total // page_size)  # rounds up
    start = (page - 1) * page_size
    items = mine[start : start + page_size] if page <= total_pages else []
    return Page(items, page, page_size, total, total_pages)
