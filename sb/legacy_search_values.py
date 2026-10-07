"""Frozen Task29 search results; later knowledge metadata belongs to newer profiles."""

from typing import TypedDict


class SearchHitDict(TypedDict):
    page_id: str
    section: str
    snippet: str
    score: float
