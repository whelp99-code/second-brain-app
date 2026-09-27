"""Clock and source-scope validation shared by Life persistence operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sb.effect_values import JsonInput
from sb.life_contracts import (
    LifeInputError,
)


def clock(now: datetime | JsonInput) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise LifeInputError("LIFE_SERVER_CLOCK_INVALID")
    return now.astimezone(UTC).isoformat()


def string_tuple(value: JsonInput, maximum: int) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) <= maximum
        and all(isinstance(s, str) for s in value)
    )


def scope_clause(scopes: tuple[str, ...], alias: str = "e") -> tuple[str, tuple[str, ...]]:
    if not string_tuple(scopes, 64):
        raise LifeInputError("LIFE_SCOPE_INVALID")
    if not scopes:
        return "0", ()
    placeholders = ",".join("?" for _ in scopes)
    return (
        f"NOT EXISTS(SELECT 1 FROM json_each({alias}.scopes_json) "
        f"WHERE value NOT IN ({placeholders}))"
    ), scopes
