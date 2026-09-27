"""Bounded Life source parsing; no persistence or network I/O."""

from __future__ import annotations

from hashlib import sha256

from sb.effect_values import JsonInput
from sb.life_values import text


def export_id(prefix: str, value: JsonInput) -> str:
    raw = text(value, maximum=4096)
    return (
        prefix + raw
        if len((prefix + raw).encode()) <= 512
        else prefix + sha256(raw.encode()).hexdigest()
    )
