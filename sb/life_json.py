"""Decode external Life JSON using a closed recursive value contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

from pydantic import TypeAdapter

from sb.effect_values import JsonInput, JsonValue

type LifePayload = dict[str, JsonInput]

_JSON: Final = TypeAdapter[JsonValue](JsonValue)
# The standard decoder retains its duplicate-key, Unicode and number behavior;
# the adapter validates the resulting recursive value before it leaves here.
_LOAD: Final[Callable[[bytes | str], JsonValue]] = json.loads


def decode_json(raw: bytes | str) -> JsonValue:
    return _JSON.validate_python(_LOAD(raw), strict=True)
