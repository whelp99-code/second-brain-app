"""Atomic cancellation admission shared by internal and explicit MCP submission."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.cancellation_target import CancellationTargetError, verify_cancellation_target
from sb.correction_cancellation import (
    ValidatedCancellationIntent,
    parse_correction_cancellation_intent,
)
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonValue, format_instant
from sb.effect_write_requests import EffectWriteIoError, open_request_directory
from sb.generations import GenerationStore
from sb.request_store import ReplayConflict, RequestStore

MAX_INVENTORY_ENTRIES = 100_000


def _require_no_publication(directories: tuple[int, ...], request_id: str) -> None:
    # Names alone suffice: even an orphan temporary or unsafe symlink is receipt evidence.
    # Do not read, unlink or follow original content during cancellation.
    count = 0
    try:
        for directory in directories:
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_INVENTORY_ENTRIES:
                        raise EffectWriteIoError("MEMORY_CANCELLATION_INVENTORY_UNBOUNDED")
                    if request_id in entry.name:
                        raise ReplayConflict("MEMORY_CANCELLATION_ALREADY_RECEIVED")
    except OSError as exc:
        raise EffectWriteIoError("WRITE_REQUEST_INBOX_UNSAFE") from exc


def accept_correction_cancellation(
    root: Path, value: JsonValue, *, generations: GenerationStore,
    clock: Callable[[], datetime], expected_provider: str,
    historical_delegation_keys: Mapping[str, Ed25519PublicKey],
    current_cancellation_keys: Mapping[str, Ed25519PublicKey],
    authority: Callable[[], tuple[Mapping[str, Ed25519PublicKey], Mapping[str, Ed25519PublicKey]]] | None = None,
) -> tuple[dict[str, JsonValue], bool]:
    """Durably accept an authenticated, locally unreceived correction's suppression intent.

    Current keys must be purpose-filtered by the caller. The result is suppression_pending,
    never proof of generation activation, erasure or permission to advance a consumer cursor.
    """
    if (generations.requests is None
        or generations.requests.root.resolve() != root.resolve()
        or generations.provider_instance_id != expected_provider):
        raise EffectWriteIoError("CANCELLATION_PROVIDER_BINDING_INVALID")

    def authenticate(raw: JsonValue, now: datetime) -> ValidatedCancellationIntent:
        historical, current = authority() if authority is not None else (historical_delegation_keys, current_cancellation_keys)
        return parse_correction_cancellation_intent(
            raw, now=format_instant(now), expected_provider=expected_provider,
            historical_delegation_keys=historical,
            current_cancellation_keys=current,
        )

    # Snapshot the caller's mutable object before waiting; authenticate again under all admission locks.
    snapshot = authenticate(value, clock()).as_dict()
    with ExitStack() as cleanup:
        store = RequestStore(root)
        _ = cleanup.callback(store.close)
        pending = open_request_directory(store.pending)
        _ = cleanup.callback(os.close, pending)
        processing = open_request_directory(store.processing)
        _ = cleanup.callback(os.close, processing)
        receipts = open_request_directory(store.receipts)
        _ = cleanup.callback(os.close, receipts)
        fcntl.flock(pending, fcntl.LOCK_EX)
        _ = cleanup.callback(fcntl.flock, pending, fcntl.LOCK_UN)

        def validate_locked() -> tuple[ValidatedCancellationIntent, datetime]:
            original = snapshot["original_delegation"]
            assert isinstance(original, dict) and isinstance(original["request_id"], str)
            _require_no_publication((pending, processing, receipts), original["request_id"])
            verified = authenticate(snapshot, clock())
            accepted_before = store.db.execute(
                "SELECT 1 FROM correction_cancellations WHERE intent_id=?", (verified.intent_id,),
            ).fetchone() is not None
            if not accepted_before:
                intent = CorrectionCancellationIntentV1.model_validate(verified.as_dict())
                current = generations.active()
                _ = verify_cancellation_target(current, intent)
                if (current.manifest.tombstone_sequence, current.manifest.tombstone_set_root) != (
                    intent.tombstone.sequence - 1, intent.tombstone.previous_root,
                ):
                    raise CancellationTargetError("TOMBSTONE_SET_STALE")
            # Target reads can take time too. Timestamp and authority are final only afterward.
            now = clock()
            return authenticate(snapshot, now), now

        # All generation writers use this mutex; never wait for it while holding the DB lock.
        with generations.exclusive():
            return store.accept_cancellation(validate_locked)
