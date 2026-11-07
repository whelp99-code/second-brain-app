"""Narrow JSON values in tests without changing the value on the success path."""

import math

from sb.effect_values import JsonObject, JsonValue


def json_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError(type(value).__name__)
    return value


def json_text(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise TypeError(type(value).__name__)
    return value


def json_objects(value: JsonValue) -> list[JsonObject]:
    if not isinstance(value, list):
        raise TypeError(type(value).__name__)
    items: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(type(item).__name__)
        items.append(item)
    return items


def dig_text(value: JsonValue, *keys: str) -> str:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            raise TypeError(key)
        current = current[key]
    if not isinstance(current, str):
        raise TypeError(type(current).__name__)
    return current


def require_object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError(type(value).__name__)
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(type(key).__name__)
        result[key] = _json_value(item)
    return result


def _json_value(value: object) -> JsonValue:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError("nan")
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return require_object(value)
    raise TypeError(type(value).__name__)
