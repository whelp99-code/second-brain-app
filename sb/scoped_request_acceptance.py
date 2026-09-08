"""Internal V4 admission composition; no MCP exposure or implicit authority."""
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from sb.effect_values import canonical_bytes, parse_instant
from sb.request_store import RequestStatus, RequestStore
from sb.scoped_request_journal import ScopedJournalEntry, prepare_scoped_journal_entry
from sb.scoped_request_publication import MAX_SCOPED_ENVELOPE_BYTES, publish_scoped_pending
from sb.scoped_write_request import ScopedWriteRequest
from sb.stable_requests import _recover_publication
from sb.task30_barriers import Task30BarrierSink


@dataclass(frozen=True, slots=True)
class ScopedWriteAccepted:
    schema_version: Literal[4]
    kind: Literal["accepted"]
    state: Literal["pending"]
    provider_instance_id: str
    request_id: str
    request_digest: str
    idempotency_key: str
    scope_digest: str
    accepted_at: str
    inbox_path: str
    request_file_digest: str
    replayed: bool


def _result(entry: ScopedJournalEntry, at: str) -> ScopedWriteAccepted:
    request = json.loads(entry.request.canonical)
    envelope = {"schema_version": 4, "state": "pending", "accepted_at": at, "request": request}
    checksum = "sha256:" + hashlib.sha256(b"second-brain/inbox-write-request/v4\0" + canonical_bytes(envelope)).hexdigest()
    return ScopedWriteAccepted(4, "accepted", "pending", entry.request.provider_instance_id,
        entry.identity.request_id, entry.identity.request_digest, entry.identity.idempotency_key,
        entry.request.preparation.identity.identity_digest, at,
        f"pending/{entry.identity.request_id}.v4.json", checksum, False)


def _replay(entry: ScopedJournalEntry, previous: RequestStatus, now: datetime) -> ScopedWriteAccepted:
    accepted = parse_instant(previous.accepted_at)
    if accepted > now:
        raise ValueError("SCOPED_ACCEPTANCE_TIME_INVALID")
    # Verify at the original acceptance too; a new valid timestamp cannot repair
    # a corrupt or out-of-validity historical result.
    prepare_scoped_journal_entry(json.loads(entry.request.canonical), now=accepted,
        expected_provider=entry.request.provider_instance_id)
    result = _result(entry, previous.accepted_at)
    if canonical_bytes(asdict(result)).decode() != previous.result_json:
        raise ValueError("SCOPED_ACCEPTANCE_INTEGRITY_FAILURE")
    return replace(result, replayed=True)


def accept_scoped_request(root: Path, value: object, *, expected_provider: str,
    clock: Callable[[], datetime], validate_authority: Callable[[ScopedWriteRequest], bool],
    barrier_sink: Task30BarrierSink | None = None) -> ScopedWriteAccepted:
    """Trusted internal admission port, requiring current authorization twice.

    The callback must verify authenticated transport/current policy/consumed scope
    review. It must not infer authority from hashes or request body labels. No
    production MCP caller is wired until that concrete verifier is implemented.
    """
    started = clock()
    entry = prepare_scoped_journal_entry(value, now=started, expected_provider=expected_provider)
    if validate_authority(entry.request) is not True:
        raise ValueError("SCOPED_WRITE_AUTHORITY_INVALID")

    def current() -> datetime:
        at = clock()
        if at < started:
            raise ValueError("SCOPED_ACCEPTANCE_TIME_INVALID")
        prepare_scoped_journal_entry(json.loads(entry.request.canonical), now=at, expected_provider=expected_provider)
        return at

    at = current()
    store = RequestStore(root, scoped_v4=True)
    try:
        previous = store.replay_status(entry.identity)
        if previous is not None:
            if validate_authority(entry.request) is not True:
                raise ValueError("SCOPED_WRITE_AUTHORITY_INVALID")
            return _replay(entry, previous, current())
        publication = publish_scoped_pending(store.pending, json.loads(entry.request.canonical), now=at,
            expected_provider=expected_provider, barrier_sink=barrier_sink)
        if validate_authority(entry.request) is not True:
            raise ValueError("SCOPED_WRITE_AUTHORITY_INVALID")
        at = current()
        def same_bytes(actual: bytes, expected: bytes) -> None:
            if actual != expected:
                raise ValueError("SCOPED_ACCEPTANCE_INTEGRITY_FAILURE")
        _recover_publication(publication.path, publication.canonical,
            validate_recovery=same_bytes, max_bytes=MAX_SCOPED_ENVELOPE_BYTES)
        result = _result(entry, publication.accepted_at)
        if result.request_file_digest != publication.file_digest:
            raise ValueError("SCOPED_ACCEPTANCE_INTEGRITY_FAILURE")
        status, replayed = store.accept(entry.identity, asdict(result), parse_instant(publication.accepted_at))
        return _replay(entry, status, at) if replayed else result
    finally:
        store.close()
