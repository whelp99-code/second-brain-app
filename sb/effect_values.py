"""Canonical values shared by Task 30 memory-effect contracts."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Never, Protocol, TypeGuard

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

DOMAINS: Final = {
    "target": b"second-brain/memory-target/v1\0",
    "target_manifest": b"second-brain/memory-target-manifest/v1\0",
    "target_scope": b"second-brain/memory-target-scope/v1\0",
    "effect_content": b"orca-jarvis/memory-effect-content/v2\0",
    "effect_payload": b"orca-jarvis/memory-effect-payload/v2\0",
    "tombstone_chain": b"orca-jarvis/memory-tombstone-chain/v1\0",
    "effect_spec": b"orca-jarvis/memory-effect-spec/v2\0",
    "effect_idempotency": b"orca-jarvis/memory-effect-idempotency/v2\0",
    "delegation": b"orca-jarvis/memory-effect-delegation/v1\0",
    "delegation_revocation": b"orca-jarvis/memory-effect-delegation-revocation/v1\0",
    "envelope": b"orca-jarvis/memory-effect-envelope/v2\0",
    "request_file": b"second-brain/memory-effect-request-file/v2\0",
    "read_fence": b"orca-jarvis/memory-read-fence/v1\0",
    "proof": b"second-brain/memory-disposition-proof/v1\0",
    "surface": b"second-brain/memory-surface-manifest/v1\0",
    "export": b"second-brain/memory-export-manifest/v1\0",
    "generation": b"second-brain/generation/v1\0",
    "external_receipt": b"external-owner/memory-erasure-receipt/v1\0",
}


class _Loads(Protocol):
    def __call__(
        self,
        s: bytes | str,
        *,
        object_pairs_hook: Callable[[list[tuple[str, JsonValue]]], JsonObject],
        parse_constant: Callable[[str], Never],
    ) -> JsonValue: ...


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict)


def canonical_bytes(value: object) -> bytes:
    """Return closed canonical UTF-8 JSON bytes and reject non-NFC text."""
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("NON_CANONICAL_JSON") from exc
    if unicodedata.normalize("NFC", text) != text:
        raise ValueError("NON_CANONICAL_NFC")
    if any(ord(character) < 32 for character in text if character not in "\t\n\r"):
        raise ValueError("NON_CANONICAL_CONTROL")
    return encoded


def digest(kind: str, value: object) -> str:
    try:
        domain = DOMAINS[kind]
    except KeyError as exc:
        raise ValueError("UNKNOWN_DIGEST_DOMAIN") from exc
    return "sha256:" + hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def parse_instant(value: str) -> datetime:
    if len(value) != 24 or not value.endswith("Z"):
        raise ValueError("INSTANT_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("INSTANT_INVALID") from exc
    if parsed.tzinfo != UTC or format_instant(parsed) != value:
        raise ValueError("INSTANT_INVALID")
    return parsed


def format_instant(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("INSTANT_INVALID")
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pairs(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("DUPLICATE_JSON_KEY")
    return result


def _constant(_value: str) -> Never:
    raise ValueError("NON_FINITE_JSON_NUMBER")


def strict_loads(raw: bytes | str, maximum: int) -> JsonValue:
    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(encoded) > maximum:
        raise ValueError("JSON_OVERSIZE")
    loader: _Loads | None = getattr(json, "loads", None)
    if loader is None:
        raise ValueError("JSON_INVALID")
    try:
        value = loader(encoded, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON_INVALID") from exc
    if canonical_bytes(value) != encoded.rstrip(b"\n"):
        raise ValueError("JSON_NON_CANONICAL")
    return value
