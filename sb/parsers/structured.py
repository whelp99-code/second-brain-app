"""Deterministic text and structured-file parsers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final, assert_never, override

import yaml

from sb.parsers import InvalidInput, LimitExceeded

MAX_BYTES: Final = 67_108_864
type CanonicalValue = (
    str | int | float | bool | None | list[CanonicalValue] | dict[str, CanonicalValue]
)


class StructuredKind(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"


@dataclass(frozen=True, slots=True)
class DuplicateMappingKeyError(Exception):
    key: str

    @override
    def __str__(self) -> str:
        return f"duplicate mapping key: {self.key}"


def _construct_mapping(
    loader: yaml.SafeLoader, node: yaml.nodes.MappingNode
) -> dict[str, CanonicalValue]:
    mapping: dict[str, CanonicalValue] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise DuplicateMappingKeyError(str(key))
        mapping[str(key)] = _as_canonical(loader.construct_object(value_node))
    return mapping


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate keys instead of silently collapsing them."""


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _decode_utf8(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidInput("structured payload is not utf-8") from exc
    if "\x00" in text:
        raise InvalidInput("structured payload contains nul")
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _unique_object(pairs: list[tuple[str, CanonicalValue]]) -> dict[str, CanonicalValue]:
    mapping: dict[str, CanonicalValue] = {}
    for key, value in pairs:
        if key in mapping:
            raise DuplicateMappingKeyError(key)
        mapping[key] = value
    return mapping


def _canonical(value: CanonicalValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _as_canonical(value) -> CanonicalValue:
    match value:  # noqa: MATCH_OK
        case None | bool() | str():
            return value
        case int() | float():
            return value
        case datetime() as moment:
            return moment.isoformat()
        case date() as day:
            return day.isoformat()
        case list() as items:
            return [_as_canonical(item) for item in items]
        case dict() as mapping:
            parsed_map: dict[str, CanonicalValue] = {}
            for key, item in mapping.items():
                if not isinstance(key, str):
                    raise InvalidInput("structured mapping key is not a string")
                parsed_map[key] = _as_canonical(item)
            return parsed_map
        case _:
            raise InvalidInput("structured value is not canonical")


def _load_json(text: str) -> CanonicalValue:
    try:
        loaded = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, DuplicateMappingKeyError) as exc:
        raise InvalidInput("invalid json") from exc
    return _as_canonical(loaded)


def _load_yaml(text: str) -> CanonicalValue:
    if not text.strip():
        return None
    try:
        loaded = yaml.load(text, Loader=_StrictSafeLoader)
    except (yaml.YAMLError, DuplicateMappingKeyError, TypeError) as exc:
        raise InvalidInput("invalid yaml") from exc
    if loaded is None:
        return None
    return _as_canonical(loaded)


@dataclass(frozen=True, slots=True)
class StructuredDocumentParser:
    """Core parser for one text or structured-file kind."""

    kind: StructuredKind
    max_bytes: int = MAX_BYTES

    def parse(self, payload: bytes) -> str:
        if len(payload) > self.max_bytes:
            raise LimitExceeded("structured payload size")
        text = _decode_utf8(payload)
        match self.kind:
            case StructuredKind.TEXT | StructuredKind.MARKDOWN:
                return text
            case StructuredKind.JSON:
                return _canonical(_load_json(text))
            case StructuredKind.YAML:
                loaded = _load_yaml(text)
                return "" if loaded is None else _canonical(loaded)
            case unreachable:
                assert_never(unreachable)


__all__ = ("DuplicateMappingKeyError", "StructuredDocumentParser", "StructuredKind")
