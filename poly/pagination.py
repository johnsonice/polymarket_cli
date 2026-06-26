"""Uniform collection over the SDK's Paginator objects."""

from typing import Any, Protocol


class _Paginator(Protocol):
    def first_page(self) -> Any: ...


def collect(paginator: _Paginator, limit: int | None = None, all_: bool = False) -> list:
    page = paginator.first_page()
    items = list(getattr(page, "items", []) or [])
    while all_ and getattr(page, "has_next", False):
        page = page.next_page()
        items.extend(getattr(page, "items", []) or [])
    if limit is not None and not all_:
        return items[:limit]
    return items
