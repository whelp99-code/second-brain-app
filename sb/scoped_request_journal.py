"""Bind validated scoped request data to the existing request journal identity."""
import json
from dataclasses import dataclass
from datetime import datetime

from sb.request_store import RequestIdentity
from sb.scoped_write_request import ScopedWriteRequest, parse_scoped_write_request
from sb.tombstone_snapshot import GENESIS_ROOT


@dataclass(frozen=True, slots=True)
class ScopedJournalEntry:
    request: ScopedWriteRequest
    identity: RequestIdentity


def prepare_scoped_journal_entry(value: object, *, now: datetime, expected_provider: str) -> ScopedJournalEntry:
    """Prepare identity, without accepting a request or granting authority.

    Keep the legacy candidate lane so a changed project/version cannot duplicate
    the same candidate. Review IDs are not disguised as effect delegations.
    """
    request = parse_scoped_write_request(value, now=now, expected_provider=expected_provider)
    scope = json.loads(request.preparation.identity.canonical)
    preparation = json.loads(request.preparation.canonical)
    identity = RequestIdentity(
        schema_version=4, request_id=request.request_id, request_digest=request.request_digest,
        envelope_digest=None, idempotency_key=request.idempotency_key,
        lane_id=f"legacy:{scope['candidate_id']}:remember", operation="remember",
        payload_digest=preparation["payload"]["content_digest"], target_manifest_digest=None,
        scope_digest=request.preparation.identity.identity_digest,
        delegation_id=None, delegation_digest=None, delegation_nonce=None,
        tombstone_sequence=0, tombstone_set_root=GENESIS_ROOT,
    )
    return ScopedJournalEntry(request, identity)
