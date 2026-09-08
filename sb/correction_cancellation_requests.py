"""Internal cancellation admission boundary. Not exposed through MCP until recovery is complete."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.correction_cancellation import (
    ValidatedCancellationIntent,
    parse_correction_cancellation_intent,
)
from sb.effect_values import JsonValue, format_instant
from sb.effect_write_requests import EffectWriteIoError, open_request_directory
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
    root: Path, value: JsonValue, *, clock: Callable[[], datetime], expected_provider: str,
    historical_delegation_keys: Mapping[str, Ed25519PublicKey],
    current_cancellation_keys: Mapping[str, Ed25519PublicKey],
) -> tuple[dict[str, JsonValue], bool]:
    """Durably accept an authenticated, locally unreceived correction's suppression intent.

    Current keys must be purpose-filtered by the caller. The result is suppression_pending,
    never proof of generation activation, erasure or permission to advance a consumer cursor.
    """
    def authenticate(raw: JsonValue, now: datetime) -> ValidatedCancellationIntent:
        return parse_correction_cancellation_intent(
            raw, now=format_instant(now), expected_provider=expected_provider,
            historical_delegation_keys=historical_delegation_keys,
            current_cancellation_keys=current_cancellation_keys,
        )

    # Snapshot the caller's mutable object before waiting; authenticate again after both locks.
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
            now = clock()
            verified = authenticate(snapshot, now)
            return verified, now

        return store.accept_cancellation(validate_locked)
