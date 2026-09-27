"""Deterministic text and structured-file parsers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final, Protocol, override

import yaml

from sb.parsers.contracts import InvalidInput, LimitExceeded

MAX_BYTES: Final = 67_108_864
type CanonicalValue = (
    str | int | float | bool | None | list[CanonicalValue] | dict[str, CanonicalValue]
)
type LooseKey = str | int | float | bool | None
type LooseValue = (
    str
    | int
    | float
    | bool
    | None
    | datetime
    | date
    | bytes
    | list[LooseValue]
    | dict[LooseKey, LooseValue]
)


class StructuredKind(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"


class _YamlConstructor(Protocol):
    def construct_object(self, node: yaml.nodes.Node, deep: bool = False) -> LooseValue: ...


class _JsonLoads(Protocol):
    def __call__(
        self,
        text: str,
        *,
        object_pairs_hook: Callable[[list[tuple[str, CanonicalValue]]], dict[str, CanonicalValue]],
    ) -> LooseValue: ...


class _YamlLoad(Protocol):
    def __call__(self, stream: str, Loader: type[yaml.SafeLoader]) -> LooseValue | None: ...


@dataclass(frozen=True, slots=True)
class DuplicateMappingKeyError(Exception):
    key: str

    @override
    def __str__(self) -> str:
        return f"duplicate mapping key: {self.key}"


def _constructed(_loader: _YamlConstructor, node: yaml.nodes.Node) -> LooseValue:
    return _loader.construct_object(node)


def _construct_mapping(
    loader: yaml.SafeLoader, node: yaml.nodes.MappingNode
) -> dict[str, LooseValue]:
    mapping: dict[str, LooseValue] = {}
    pairs: list[tuple[yaml.nodes.Node, yaml.nodes.Node]] | None = getattr(node, "value", None)
    if pairs is None:
        return mapping
    for key_node, value_node in pairs:
        raw_key = _constructed(loader, key_node)
        raw_value = _constructed(loader, value_node)
        if not isinstance(raw_key, str):
            raise InvalidInput("structured mapping key is not a string")
        if raw_key in mapping:
            raise DuplicateMappingKeyError(raw_key)
        mapping[raw_key] = raw_value
    return mapping


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate keys instead of silently collapsing them."""


def _mapping_tag() -> str:
    tag: str | None = getattr(yaml.resolver.BaseResolver, "DEFAULT_MAPPING_TAG", None)
    if tag is None:
        return "tag:yaml.org,2002:map"
    return tag


_StrictSafeLoader.add_constructor(_mapping_tag(), _construct_mapping)


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


def _as_canonical(value: LooseValue) -> CanonicalValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_as_canonical(item) for item in value]
    if isinstance(value, dict):
        parsed_map: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidInput("structured mapping key is not a string")
            parsed_map[key] = _as_canonical(item)
        return parsed_map
    raise InvalidInput("structured value is not canonical")


def _json_loads() -> _JsonLoads:
    loads: _JsonLoads | None = getattr(json, "loads", None)
    if loads is None:
        raise InvalidInput("invalid json")
    return loads


def _yaml_load() -> _YamlLoad:
    load: _YamlLoad | None = getattr(yaml, "load", None)
    if load is None:
        raise InvalidInput("invalid yaml")
    return load


def _load_json(text: str) -> CanonicalValue:
    try:
        loaded = _json_loads()(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, DuplicateMappingKeyError) as exc:
        raise InvalidInput("invalid json") from exc
    return _as_canonical(loaded)


def _load_yaml(text: str) -> CanonicalValue:
    if not text.strip():
        return None
    try:
        loaded = _yaml_load()(text, Loader=_StrictSafeLoader)
    except (yaml.YAMLError, DuplicateMappingKeyError, TypeError) as exc:
        raise InvalidInput("invalid yaml") from exc
    if loaded is None:
        return None
    return _as_canonical(loaded)


def _read_text(text: str) -> str:
    return text


def _read_json(text: str) -> str:
    return _canonical(_load_json(text))


def _read_yaml(text: str) -> str:
    loaded = _load_yaml(text)
    return "" if loaded is None else _canonical(loaded)


_READERS: Final[dict[StructuredKind, Callable[[str], str]]] = {
    StructuredKind.TEXT: _read_text,
    StructuredKind.MARKDOWN: _read_text,
    StructuredKind.JSON: _read_json,
    StructuredKind.YAML: _read_yaml,
}


@dataclass(frozen=True, slots=True)
class StructuredDocumentParser:
    """Core parser for one text or structured-file kind."""

    kind: StructuredKind
    max_bytes: int = MAX_BYTES

    def parse(self, payload: bytes) -> str:
        if len(payload) > self.max_bytes:
            raise LimitExceeded("structured payload size")
        text = _decode_utf8(payload)
        return _READERS[self.kind](text)


def parse_structured(kind: str, payload: bytes) -> str:
    """Parse one registered structured suffix kind from raw bytes."""
    return StructuredDocumentParser(StructuredKind(kind)).parse(payload)


__all__ = (
    "DuplicateMappingKeyError",
    "StructuredDocumentParser",
    "StructuredKind",
    "parse_structured",
)
