"""Strict JSON boundaries shared by the synthetic Life contract tests."""

from collections.abc import Mapping

from pydantic import ConfigDict, TypeAdapter

from sb.config import TomlValue
from sb.effect_values import JsonInput, JsonObject
from tests import test_web

_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject, config=ConfigDict(strict=True))
_ROWS = TypeAdapter(list[JsonObject], config=ConfigDict(strict=True))
_INT = TypeAdapter(int, config=ConfigDict(strict=True))
_TEXT = TypeAdapter(str, config=ConfigDict(strict=True))


json_object = _OBJECT.validate_python
json_rows = _ROWS.validate_python
json_text = _TEXT.validate_python
json_int = _INT.validate_python


def load_json_object(raw: str | bytes) -> JsonObject:
    return _OBJECT.validate_json(raw, strict=True)


def config_table(value: TomlValue) -> Mapping[str, TomlValue]:
    assert isinstance(value, Mapping)
    return value


def request(
    url: str,
    *,
    method: str = "GET",
    payload: JsonInput = None,
    token: str | None = None,
) -> tuple[int, JsonObject]:
    status, body = test_web._request(url, method=method, payload=payload, token=token)
    return status, json_object(body)
