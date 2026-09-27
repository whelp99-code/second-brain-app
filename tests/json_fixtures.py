"""Parse test wire responses into recursive JSON values without coercion."""

from pydantic import TypeAdapter

from sb.effect_values import JsonObject, JsonValue

_JSON = TypeAdapter[JsonValue](JsonValue)
_OBJECT = TypeAdapter[JsonObject](JsonObject)


def parse_json(raw: str | bytes) -> JsonValue:
    return _JSON.validate_json(raw, strict=True)


def parse_object(raw: str | bytes) -> JsonObject:
    return _OBJECT.validate_json(raw, strict=True)
