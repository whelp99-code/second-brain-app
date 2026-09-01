"""Signed metadata-only schema-4 export lifecycle status."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import asdict, dataclass
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_values import JsonObject, canonical_bytes
from sb.export_journal import ExportLifecycleRecord

_SIGNATURE_DOMAIN = b"second-brain/memory-export-status/v1\0"


class ExportStatusError(ValueError):
    """The export lifecycle or signing configuration is not authoritative."""


@dataclass(frozen=True, slots=True)
class SignedExportStatusV1:
    schema_version: Literal[1]
    state: Literal["pending", "available", "expired", "invalidated"]
    manifest_digest: str
    created_at: str
    expires_at: str
    invalidated_at: str | None
    scope_digest: str
    tombstone_sequence: int
    tombstone_set_root: str
    status_digest: str
    provider_signing_key_id: str
    signature: str

    def as_dict(self) -> JsonObject:
        return asdict(self)


def _state(record: ExportLifecycleRecord) -> Literal[
    "pending", "available", "expired", "invalidated"
]:
    states: dict[str, Literal["pending", "available", "expired", "invalidated"]] = {
        "publishing": "pending", "disposing": "pending", "available": "available",
        "expired": "expired", "invalidated": "invalidated",
    }
    selected = states.get(record.state)
    if selected is None:
        raise ExportStatusError("EXPORT_STATUS_INVALID")
    return selected


def sign_export_status(
    record: ExportLifecycleRecord,
    scope_digest: str,
    signing_key_id: str,
    private_key: Ed25519PrivateKey,
) -> SignedExportStatusV1:
    """Sign one closed status; no path, filename, body, or download locator is emitted."""
    if not signing_key_id or not scope_digest.startswith("sha256:"):
        raise ExportStatusError("EXPORT_STATUS_INVALID")
    state = _state(record)
    invalidated_at = record.disposed_at if state == "invalidated" else None
    core: JsonObject = {
        "schema_version": 1,
        "state": state,
        "manifest_digest": record.manifest_digest,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "invalidated_at": invalidated_at,
        "scope_digest": scope_digest,
        "tombstone_sequence": record.tombstone_sequence,
        "tombstone_set_root": record.tombstone_set_root,
    }
    status_digest = "sha256:" + hashlib.sha256(
        _SIGNATURE_DOMAIN + canonical_bytes(core)
    ).hexdigest()
    signed: JsonObject = {
        **core,
        "status_digest": status_digest,
        "provider_signing_key_id": signing_key_id,
    }
    signature = base64.urlsafe_b64encode(
        private_key.sign(_SIGNATURE_DOMAIN + canonical_bytes(signed))
    ).rstrip(b"=").decode("ascii")
    if len(signature) != 86:
        raise ExportStatusError("EXPORT_STATUS_INVALID")
    return SignedExportStatusV1(
        schema_version=1,
        state=state,
        manifest_digest=record.manifest_digest,
        created_at=record.created_at,
        expires_at=record.expires_at,
        invalidated_at=invalidated_at,
        scope_digest=scope_digest,
        tombstone_sequence=record.tombstone_sequence,
        tombstone_set_root=record.tombstone_set_root,
        status_digest=status_digest,
        provider_signing_key_id=signing_key_id,
        signature=signature,
    )
