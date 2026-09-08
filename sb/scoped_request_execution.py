"""Load only an admitted scoped envelope matching the fenced request journal."""
import hashlib
from datetime import datetime
from pathlib import Path

from sb.remember_contracts import MemoryWriteRequestV3
from sb.request_store import RequestStatus
from sb.scoped_request_acceptance import _replay
from sb.scoped_request_publication import MAX_SCOPED_ENVELOPE_BYTES, _envelope
from sb.scoped_write_request import ScopedWriteRequest
from sb.stable_requests import _recover_publication
from sb.write_request_values import parse_request_v3


def load_scoped_execution(path: Path, status: RequestStatus, *, provider: str,
    now: datetime) -> tuple[MemoryWriteRequestV3, ScopedWriteRequest]:
    def validate(raw: bytes, _expected: bytes) -> None:
        _envelope(raw, provider)
    raw = _recover_publication(path, b"", validate_recovery=validate, max_bytes=MAX_SCOPED_ENVELOPE_BYTES)
    value, accepted_at, entry = _envelope(raw, provider)
    if status.identity != entry.identity or status.accepted_at != value["accepted_at"]:
        raise ValueError("REQUEST_ENVELOPE_MISMATCH")
    accepted = _replay(entry, status, now)
    checksum = "sha256:" + hashlib.sha256(b"second-brain/inbox-write-request/v4\0" + raw[:-1]).hexdigest()
    if accepted.request_file_digest != checksum:
        raise ValueError("REQUEST_ENVELOPE_MISMATCH")
    # Historical decode is not renewed authority. The executor's mandatory live
    # verifier decides whether work may start/resume and switch the generation.
    source = parse_request_v3(value["request"]["source_request"], accepted_at)
    return source, entry.request
