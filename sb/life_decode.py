"""Integrity-checked decoding of persisted Life event revisions."""

from dataclasses import fields
from hashlib import sha256
from typing import Final

from pydantic import TypeAdapter

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_json import decode_json
from sb.store.life_rows import Row, string

_EVENT: Final = TypeAdapter[LifeEventV1](LifeEventV1)
_FIELDS: Final = frozenset(field.name for field in fields(LifeEventV1))


def decode_event(row: Row) -> LifeEventV1:
    try:
        encoded, expected = string(row[0]), string(row[1])
        if sha256(encoded.encode()).hexdigest() != expected:
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        data = decode_json(encoded)
        if not isinstance(data, dict) or set(data) - _FIELDS:
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        event = _EVENT.validate_json(encoded, strict=True)
        if event.schema_version != 1:
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        return event
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LifeInputError("LIFE_RECORD_CORRUPT") from exc
