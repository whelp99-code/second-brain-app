"""Publish one `daily-refresh-receipt-v1` document at the end of `sb run`.

JARVIS cannot see this provider's ledger. Without a published receipt it can
only distinguish "a refresh was attempted" from "a refresh completed" by
guessing, so its daily loop and its readiness report both stay at "no refresh
evidence" however well the refresh actually went. This module closes that gap
with the smallest durable artefact that answers the question: which refresh,
what state, when, and whether a cap clipped it.

The shape is the consumer's, not ours (`docs` §3.2 of the JARVIS contract
handoff): an exact three-key envelope, one frozen profile name, a receipt whose
`completed_at` round-trips through JavaScript's `Date.prototype.toISOString`,
and a document small enough for a reader that refuses anything over 8 KiB. The
file is published by rename so a reader never sees a half-written receipt, and
at mode 0600 because a refresh identity is not public.

A failed refresh publishes `state: "failed"` rather than deleting the file:
"the last refresh failed" and "no refresh has ever run" are different
operational facts and must not collapse into each other.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sb.config import Config

RECEIPT_PROFILE: Final = "daily-refresh-receipt-v1"
RECEIPT_PROTOCOL_VERSION: Final = 1
RECEIPT_MAX_BYTES: Final = 8192
REFRESH_ID_MAX_CHARS: Final = 512
RECEIPT_FILENAME: Final = "refresh-receipt.json"


class RefreshReceiptError(Exception):
    """The receipt cannot be published as a private, bounded, regular file."""


def receipt_path(config: Config) -> Path:
    """Where this installation publishes its refresh receipt."""
    return Path(config.refresh_receipt_path)


def _completed_at(now: datetime) -> str:
    """An instant in the only format the JARVIS reader accepts."""
    moment = now.astimezone(UTC)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def build_refresh_receipt(
    *, run_id: str, status: str, exit_code: int, now: datetime
) -> dict[str, object]:
    """The exact envelope JARVIS accepts, or a refusal to invent one."""
    refresh_id = run_id[:REFRESH_ID_MAX_CHARS]
    if not refresh_id:
        # An unidentified refresh cannot be reconciled with anything; publishing
        # one would let JARVIS treat an unknown run as evidence.
        raise RefreshReceiptError("REFRESH_RECEIPT_RUN_UNIDENTIFIED")
    return {
        "schema_version": 1,
        "profile": RECEIPT_PROFILE,
        "receipt": {
            "schema_version": 1,
            "refresh_id": refresh_id,
            "state": "completed" if exit_code == 0 else "failed",
            "completed_at": _completed_at(now),
            "protocol_version": RECEIPT_PROTOCOL_VERSION,
            "capped": status == "capped",
        },
    }


def publish_refresh_receipt(
    config: Config, *, run_id: str, status: str, exit_code: int, now: datetime | None = None
) -> Path:
    """Write the receipt atomically and return where it landed."""
    document = build_refresh_receipt(
        run_id=run_id, status=status, exit_code=exit_code,
        now=datetime.now(UTC) if now is None else now,
    )
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(payload) > RECEIPT_MAX_BYTES:
        raise RefreshReceiptError("REFRESH_RECEIPT_TOO_LARGE")
    destination = receipt_path(config)
    directory = destination.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RefreshReceiptError("REFRESH_RECEIPT_PATH_UNSAFE") from exc
    # A symlink or ordinary file here is replaced by the rename below; anything
    # else at that name means the path is not ours to publish to.
    if destination.exists() and not destination.is_file():
        raise RefreshReceiptError("REFRESH_RECEIPT_PATH_UNSAFE")
    handle, temporary = tempfile.mkstemp(
        prefix=f".{RECEIPT_FILENAME}.", suffix=".tmp", dir=str(directory)
    )
    try:
        os.fchmod(handle, 0o600)
        if os.write(handle, payload) != len(payload):
            raise RefreshReceiptError("REFRESH_RECEIPT_TRUNCATED")
        os.fsync(handle)
    except OSError as exc:
        raise RefreshReceiptError("REFRESH_RECEIPT_NOT_WRITTEN") from exc
    finally:
        os.close(handle)
    try:
        os.replace(temporary, destination)
    except OSError as exc:
        Path(temporary).unlink(missing_ok=True)
        raise RefreshReceiptError("REFRESH_RECEIPT_PATH_UNSAFE") from exc
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return destination
