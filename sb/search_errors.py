"""Typed sealed-index failures for search boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override


class SearchQueryError(ValueError):
    """An unsupported query is distinct from a successful search with no results."""


@dataclass(slots=True)
class GenerationIndexError(RuntimeError):
    code: Literal["GENERATION_INDEX_INVALID"] = "GENERATION_INDEX_INVALID"

    @override
    def __str__(self) -> str:
        return self.code
