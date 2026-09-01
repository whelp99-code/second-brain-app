"""Typed sealed-index failures for search boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override


@dataclass(frozen=True, slots=True)
class GenerationIndexError(RuntimeError):
    code: Literal["GENERATION_INDEX_INVALID"] = "GENERATION_INDEX_INVALID"

    @override
    def __str__(self) -> str:
        return self.code
