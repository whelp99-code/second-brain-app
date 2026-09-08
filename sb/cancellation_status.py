"""Authorized, read-only lookup of immutable provider-local cancellation results."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import TypeAdapter

from sb.cancellation_result import CancellationResultError, verify_cancellation_result
from sb.correction_cancellation import DOMAIN, MAX_BYTES
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.delegations import DelegationRejected, verify_read_fence
from sb.effect_values import (
    JsonObject,
    JsonValue,
    canonical_bytes,
    format_instant,
    parse_instant,
    strict_loads,
)
from sb.effect_write_values import model_object
from sb.tombstone_snapshot import verified_snapshot

_INTENT_ROW: TypeAdapter[tuple[str, str, str] | None] = TypeAdapter(tuple[str, str, str] | None)
_RESULT_ROW: TypeAdapter[tuple[str, str] | None] = TypeAdapter(tuple[str, str] | None)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_NO_REVOKED_KEYS: frozenset[str] = frozenset()


class CancellationStatusError(ValueError):
    pass


def _object(text: str) -> JsonObject:
    value = strict_loads(text, MAX_BYTES)
    if not isinstance(value, dict):
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT")
    return value


def _lookup(
    db: sqlite3.Connection, intent_id: str, intent_digest: str, *,
    provider_instance_id: str, now: datetime, read_fence: JsonValue,
    reader_keys: Mapping[str, Ed25519PublicKey],
    provider_keys: Mapping[str, Ed25519PublicKey], revoked_provider_key_ids: frozenset[str],
) -> JsonObject:
    snapshot = verified_snapshot(db)
    fence = verify_read_fence(read_fence, reader_keys, provider_instance_id, now,
                              snapshot.sequence, snapshot.set_root)
    if fence.purpose != "memory_status" or fence.operation != "status":
        raise CancellationStatusError("TOMBSTONE_FENCE_REQUIRED")
    if (_DIGEST.fullmatch(intent_digest) is None
        or intent_id != "memcancel:intent:v1:" + intent_digest[7:]):
        raise CancellationStatusError("MEMORY_CANCELLATION_IDENTITY_INVALID")
    response: JsonObject = {
        "schema_version": 1, "kind": "memory_correction_cancellation_status",
        "provider_instance_id": provider_instance_id,
        "intent_id": intent_id, "intent_digest": intent_digest,
        "tombstone_sequence": snapshot.sequence, "tombstone_set_root": snapshot.set_root,
        "state": "not_found",
    }
    row = _INTENT_ROW.validate_python(db.execute(
        "SELECT intent_json,accepted_at,intent_digest FROM correction_cancellations WHERE intent_id=?",
        (intent_id,),
    ).fetchone(), strict=True)
    if row is None:
        return response
    wire = _object(row[0])
    intent = CorrectionCancellationIntentV1.model_validate(wire)
    body = {key: item for key, item in wire.items()
            if key not in {"intent_id", "intent_digest", "signature"}}
    observed = "sha256:" + hashlib.sha256(DOMAIN + canonical_bytes(body)).hexdigest()
    accepted = parse_instant(row[1])
    if (observed != intent_digest or row[2] != intent_digest or intent.intent_id != intent_id
        or intent.intent_digest != intent_digest or intent.provider_instance_id != provider_instance_id):
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT")
    if (format_instant(accepted) != row[1]
        or not parse_instant(intent.not_before) <= accepted < parse_instant(intent.expires_at)
        or accepted > now):
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT")
    if (not 1 <= intent.tombstone.sequence <= snapshot.sequence
        or snapshot.entries[intent.tombstone.sequence - 1].set_root != intent.tombstone.set_root):
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT")
    response.update({"state": "suppression_pending", "accepted_at": row[1]})
    saved = _RESULT_ROW.validate_python(db.execute(
        "SELECT result_json,result_digest FROM correction_cancellation_results WHERE intent_id=?",
        (intent_id,),
    ).fetchone(), strict=True)
    if saved is None:
        return response
    result = verify_cancellation_result(_object(saved[0]), intent, now=now,
        provider_keys={key_id: key for key_id, key in provider_keys.items()
                       if key_id not in revoked_provider_key_ids})
    if result.result_digest != saved[1] or result.accepted_at != row[1]:
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT")
    response.update({"state": result.state, "result": model_object(result)})
    return response


def read_cancellation_status(
    journal_path: Path, intent_id: str, intent_digest: str, *,
    provider_instance_id: str, now: datetime, read_fence: JsonValue,
    reader_keys: Mapping[str, Ed25519PublicKey],
    provider_keys: Mapping[str, Ed25519PublicKey],
    revoked_provider_key_ids: frozenset[str] = _NO_REVOKED_KEYS,
) -> JsonObject:
    """Never initializes the journal, issues a receipt, or executes a cancellation.

    Reader keys must be the caller's current, non-revoked authority set. Historical
    result verification keys are a separate trust set; no private key is needed.
    """
    try:
        db = sqlite3.connect(journal_path.absolute().as_uri() + "?mode=ro", uri=True)
        try:
            _ = db.execute("PRAGMA query_only=ON")
            _ = db.execute("BEGIN")
            return _lookup(db, intent_id, intent_digest,
                provider_instance_id=provider_instance_id, now=now, read_fence=read_fence,
                reader_keys=reader_keys, provider_keys=provider_keys,
                revoked_provider_key_ids=revoked_provider_key_ids)
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise CancellationStatusError("CANCELLATION_STATUS_UNAVAILABLE") from exc
    except (CancellationStatusError, CancellationResultError, DelegationRejected):
        raise
    except ValueError as exc:
        raise CancellationStatusError("CANCELLATION_RESULT_CORRUPT") from exc
