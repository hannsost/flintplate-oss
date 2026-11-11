"""Reusable pagination helpers – Sprint 0.2+ will use these for list endpoints."""

from __future__ import annotations

from typing import TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PageParams:
    """FastAPI Dependency for page/size query params.

    Usage:
        @router.get("/items")
        async def list_items(page: Annotated[PageParams, Depends()]) -> Page[ItemRead]:
            offset = page.offset
            limit  = page.size
    """

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Page number (1-based)"),
        size: int = Query(
            default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"
        ),
    ) -> None:
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page[T](BaseModel):
    """Generic paginated response envelope."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def create(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        pages = max(1, -(-total // params.size))  # ceiling division
        return cls(items=items, total=total, page=params.page, size=params.size, pages=pages)
