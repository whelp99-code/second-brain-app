"""Load only an admitted scoped envelope matching the fenced request journal."""
import hashlib
from datetime import datetime
from pathlib import Path

from sb.effect_values import is_json_object
from sb.remember_contracts import MemoryWriteRequestV3
from sb.request_store import RequestStatus
from sb.scoped_request_acceptance import replay_scoped_request
from sb.scoped_request_publication import MAX_SCOPED_ENVELOPE_BYTES, parse_scoped_envelope
from sb.scoped_write_request import ScopedWriteRequest
from sb.stable_requests import recover_publication
from sb.write_request_values import parse_request_v3


def load_scoped_execution(path: Path, status: RequestStatus, *, provider: str,
    now: datetime) -> tuple[MemoryWriteRequestV3, ScopedWriteRequest]:
    def validate(raw: bytes, _expected: bytes) -> None:
        _ = parse_scoped_envelope(raw, provider)
    raw = recover_publication(path, b"", validate_recovery=validate, max_bytes=MAX_SCOPED_ENVELOPE_BYTES)
    value, accepted_at, entry = parse_scoped_envelope(raw, provider)
    if status.identity != entry.identity or status.accepted_at != value["accepted_at"]:
        raise ValueError("REQUEST_ENVELOPE_MISMATCH")
    accepted = replay_scoped_request(entry, status, now)
    checksum = "sha256:" + hashlib.sha256(b"second-brain/inbox-write-request/v4\0" + raw[:-1]).hexdigest()
    if accepted.request_file_digest != checksum:
        raise ValueError("REQUEST_ENVELOPE_MISMATCH")
    # Historical decode is not renewed authority. The executor's mandatory live
    # verifier decides whether work may start/resume and switch the generation.
    request = value["request"]
    if not is_json_object(request):
        raise ValueError("REQUEST_ENVELOPE_MISMATCH")
    source = parse_request_v3(request["source_request"], accepted_at)
    return source, entry.request
