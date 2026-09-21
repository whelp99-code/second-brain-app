"""Optional application-layer encryption for file-backed background uploads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from typing import Final, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from phone_history.errors import ValidationError

_VERSION: Final = 1
_NONCE_BYTES: Final = 12
_AAD: Final = b"phone-history-transport-v1"
_KEY_CONTEXT: Final = b"phone-history-transport-v1\0"


def derive_transport_key(api_token: str) -> bytes:
    return hashlib.sha256(_KEY_CONTEXT + api_token.encode("utf-8")).digest()


def seal_transport_payload(payload: Mapping[str, object], api_token: str) -> dict[str, object]:
    """Create the interoperable CryptoKit/cryptography envelope used by tests and tools."""
    cleartext = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(derive_transport_key(api_token)).encrypt(nonce, cleartext, _AAD)
    return {
        "version": _VERSION,
        "payload_base64": base64.b64encode(nonce + ciphertext).decode("ascii"),
    }


def open_transport_payload(value: object, api_token: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValidationError("encrypted request must be an object")
    data = cast(dict[str, object], value)
    if set(data) != {"version", "payload_base64"} or data.get("version") != _VERSION:
        raise ValidationError("encrypted request envelope is invalid")
    encoded = data.get("payload_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValidationError("encrypted request payload is required")
    try:
        combined = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("encrypted request payload is invalid") from exc
    if len(combined) < _NONCE_BYTES + 16:
        raise ValidationError("encrypted request payload is too short")
    nonce = combined[:_NONCE_BYTES]
    ciphertext = combined[_NONCE_BYTES:]
    try:
        cleartext = AESGCM(derive_transport_key(api_token)).decrypt(nonce, ciphertext, _AAD)
    except InvalidTag as exc:
        raise ValidationError("encrypted request authentication failed") from exc
    try:
        payload = json.loads(cleartext)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("encrypted request JSON is invalid") from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ValidationError("encrypted request content must be an object")
    return cast(dict[str, object], payload)
