"""Authenticated encryption helpers for Phone History data at rest."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from phone_history.errors import CryptoError

_MAGIC = b"PH1"
_NONCE_BYTES = 12


class SecretBox:
    """Small versioned AES-256-GCM envelope codec.

    A caller-provided AAD string binds ciphertext to its table/record purpose so
    moving bytes between columns or files fails authentication.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise CryptoError("AES-256-GCM requires a 32-byte key")
        self._aead = AESGCM(bytes(key))

    def seal(self, plaintext: bytes, *, aad: str) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, plaintext, aad.encode("utf-8"))
        return _MAGIC + nonce + ciphertext

    def open(self, envelope: bytes, *, aad: str) -> bytes:
        minimum = len(_MAGIC) + _NONCE_BYTES + 16
        if len(envelope) < minimum or not envelope.startswith(_MAGIC):
            raise CryptoError("encrypted envelope is malformed")
        nonce_start = len(_MAGIC)
        nonce_end = nonce_start + _NONCE_BYTES
        nonce = envelope[nonce_start:nonce_end]
        ciphertext = envelope[nonce_end:]
        try:
            return self._aead.decrypt(nonce, ciphertext, aad.encode("utf-8"))
        except InvalidTag as exc:
            raise CryptoError("encrypted envelope authentication failed") from exc

    def seal_text(self, value: str, *, aad: str) -> bytes:
        return self.seal(value.encode("utf-8"), aad=aad)

    def open_text(self, envelope: bytes, *, aad: str) -> str:
        try:
            return self.open(envelope, aad=aad).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CryptoError("decrypted text is not UTF-8") from exc

    def seal_json(self, value: Mapping[str, Any], *, aad: str) -> bytes:
        raw = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.seal(raw, aad=aad)

    def open_json(self, envelope: bytes, *, aad: str) -> dict[str, Any]:
        try:
            value = json.loads(self.open(envelope, aad=aad))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CryptoError("decrypted JSON is invalid") from exc
        if not isinstance(value, dict):
            raise CryptoError("decrypted JSON must be an object")
        return value
