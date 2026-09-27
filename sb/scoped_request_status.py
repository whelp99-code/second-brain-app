"""Current-scope reads of historical V4 journal results; no renewed write authority.

The caller owns authenticated read-policy resolution and transport. This internal
port does not expose the global request-status API to scoped clients. Historical
proof is not evidence that the artifact is still current or has not been deleted.
"""
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import cast

from sb.effect_values import JsonObject, JsonValue, canonical_bytes, digest, parse_instant
from sb.request_store import RequestStore
from sb.scoped_request_acceptance import replay_scoped_request
from sb.scoped_request_journal import prepare_scoped_journal_entry
from sb.source_access import SourceAccess


def read_scoped_request_status(
    store: RequestStore, value: JsonValue, *, expected_provider: str,
    clock: Callable[[], datetime], resolve_scope: Callable[[datetime], SourceAccess | None],
    include_acceptance: bool = False,
) -> JsonObject:
    """Read a detached journal snapshot under current authenticated scope twice.

    resolve_scope must enforce current authenticated session, policy and expiry;
    request body labels and historical write approval are not read credentials.
    The store must be opened in maintenance_only mode by the owning read surface.
    No pending/receipt file is required and no writer claim is acquired here.
    """
    denied = "SCOPED_REQUEST_STATUS_DENIED"
    started = clock()
    if not isinstance(value, dict):
        raise TypeError(denied)
    created = value.get("created_at")
    if not isinstance(created, str):
        raise TypeError(denied)
    # Decode at the original write time, never renew an expired write request.
    entry = prepare_scoped_journal_entry(value, now=parse_instant(created),
        expected_provider=expected_provider)
    requirement = entry.request.preparation.source_access

    def scope_at(at: datetime) -> SourceAccess:
        scope = resolve_scope(at)
        if (scope is None or scope.owner != requirement.owner
            or scope.policy_revision != requirement.policy_revision
            or (not requirement.projects and bool(scope.projects))
            or not set(requirement.projects) <= set(scope.projects)):
            raise ValueError(denied)
        return scope

    scope = scope_at(started)
    status = store.get(entry.identity.request_id)
    result: JsonObject = {"schema_version": 4, "provider_instance_id": expected_provider,
        "request_id": entry.identity.request_id, "request_digest": entry.identity.request_digest,
        "scope_digest": entry.identity.scope_digest, "state": "not_found"}
    if status is not None:
        if status.identity != entry.identity:
            raise ValueError(denied)
        accepted = replay_scoped_request(entry, status, started)
        if include_acceptance:
            result["acceptance"] = cast(JsonObject, asdict(accepted))
        updated = parse_instant(status.updated_at)
        if not parse_instant(status.accepted_at) <= updated <= started:
            raise ValueError(denied)
        result.update(state=status.state, phase=status.phase, updated_at=status.updated_at)
        if status.state == "proved":
            decoded = cast(object, json.loads(status.proof_json or "null"))
            if not isinstance(decoded, dict):
                raise ValueError(denied)
            proof = cast(JsonObject, decoded)
            keys = {"schema_version", "provider_instance_id", "request_id", "request_digest",
                "scope_digest", "content_digest", "generation_id", "head", "tree"}
            if (set(proof) != keys
                or canonical_bytes(proof).decode() != status.proof_json
                or type(proof["schema_version"]) is not int or proof["schema_version"] != 4
                or proof["provider_instance_id"] != expected_provider
                or proof["request_id"] != entry.identity.request_id
                or proof["request_digest"] != entry.identity.request_digest
                or proof["scope_digest"] != entry.identity.scope_digest
                or proof["content_digest"] != "sha256:" + hashlib.sha256(entry.request.preparation.content.encode()).hexdigest()
                or proof["generation_id"] != status.result_generation_id
                or re.fullmatch(r"sbgen:v1:[0-9a-f]{64}", str(proof["generation_id"])) is None
                or any(re.fullmatch(r"[0-9a-f]{40}", str(proof[key])) is None for key in ("head", "tree"))
                or digest("surface", proof) != status.proof_digest
                or digest("surface", {"state": "proved", "proof": status.proof_digest}) != status.status_digest):
                raise ValueError(denied)
            result["proof"] = proof
            # Reconstruct the durable receipt from the same journal snapshot.
            # File publication can lag journal commit after process interruption.
            result["receipt"] = {"schema_version": 4, "request_id": entry.identity.request_id,
                "request_digest": entry.identity.request_digest, "envelope_digest": None,
                "state": "proved", "code": "PROVIDER_PROVED", "proof_digest": status.proof_digest,
                "status_digest": status.status_digest, "updated_at": status.updated_at}
        elif status.proof_json is not None or status.proof_digest is not None:
            raise ValueError(denied)
    finished = clock()
    if finished < started or scope_at(finished) != scope:
        raise ValueError(denied)
    return result
