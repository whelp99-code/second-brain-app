from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Self, override


class FrozenTask30DateTime(datetime):
    """Keep frozen wire vectors inside their authority window."""

    @classmethod
    @override
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 8, 31, 0, 0, 1, tzinfo=UTC if tz is None else tz)
