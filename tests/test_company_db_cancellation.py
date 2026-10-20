"""An original revoked, unexecuted request closes without fabricating approval."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_db_freshness_hash import operation_id_for
from sb.company_db_freshness_models import JarvisCancellationV1, JarvisSidecarEvidence
from sb.company_freshness import (
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessScope,
    FreshnessWireError,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory_cli import run
from sb.company_memory_cli_config import load_company_config
from sb.company_memory_handoff import CompanyControlRequest
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import (
    JsonObject,
    canonical_bytes,
    format_instant,
    is_json_object,
    parse_instant,
    strict_loads,
)
from tests.test_company_candidate_handoff import CONTEXT, PAGE, first_proposal, signed_request
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW


def cancelled_runtime(
    root: Path,
) -> tuple[CompanyDbFreshnessProvider, Path, JsonObject, JsonObject]:
    cfg, sb = human_runtime(root)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=sb,
        ),
    )
    command = proposal["command"]
    assert is_json_object(command)
    original = CompanyControlRequest.model_validate_json(canonical_bytes(command), strict=True)
    command_hash = "sha256:" + hashlib.sha256(canonical_bytes(command)).hexdigest()
    provider = CompanyDbFreshnessProvider(
        database=sb.database,
        registry_path=sb.registry_path,
        witness_dir=sb.witness_dir,
        lock_path=sb.lock_path,
        anchor=sb.anchor,
        registry_id=sb.registry_id,
        actor_store="jarvis",
        clock=lambda: format_instant(NOW),
    )
    scope = FreshnessScope(
        provider_instance_id=CONTEXT.provider,
        workspace_id=CONTEXT.workspace_id,
    )
    point = local_checkpoint(sb.database, CONTEXT.workspace_id, None)
    assert point is not None
    operation_id = operation_id_for(
        scope,
        request_id=original.request_id,
        command_digest=command_hash,
        operation="decide_approve",
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id,
            operation="decide_approve",
            expected_checkpoint=point,
            event_digest=command_hash,
            challenge="cancel:reserve",
        ),
    )
    assert isinstance(reserved, ReserveProgressResponse)
    assert reserved.outcome == "reserved" and reserved.reservation_id and reserved.checkpoint
    payload: JsonObject = {
        "request_id": command["request_id"],
        "reason": "withdrawn before execution",
        "revoked_by": "owner",
        "revoked_at": format_instant(NOW),
    }
    payload_hash = "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    revocation: JsonObject = {
        **payload,
        "revocation_id": "control-revocation:" + payload_hash.removeprefix("sha256:"),
        "receipt_id": None,
        "command_digest": command_hash,
        "payload_json": canonical_bytes(payload).decode("utf-8"),
        "payload_digest": payload_hash,
        "created_at": format_instant(NOW),
    }
    sidecar: JsonObject = {
        "schema_version": 1,
        "kind": "cancellation",
        "source_record_id": revocation["revocation_id"],
        "original_at": format_instant(NOW),
        "command": command,
        "record": {
            "schema_version": 1,
            "state": "cancelled",
            "lease_fence": 0,
            "effect_record_id": None,
            "revocation": revocation,
        },
    }
    finish: JsonObject = {
        "schema_version": 2,
        "scope": scope.model_dump(mode="json"),
        "operation_id": operation_id,
        "reservation_id": reserved.reservation_id,
        "expected_checkpoint": reserved.checkpoint.model_dump(mode="json"),
        "terminal_state": "cancelled",
        "evidence_digest": payload_hash,
        "challenge": "cancel:finish",
    }
    return provider, cfg, finish, sidecar


def finish_with_proof(
    provider: CompanyDbFreshnessProvider,
    cfg: Path,
    finish: JsonObject,
    proof: JsonObject,
) -> FinishProgressResponse | FreshnessWireError:
    config = load_company_config(cfg)
    assert config.handoff_policy is not None
    return provider.finish_with_jarvis_sidecar(
        FinishProgressRequest.model_validate(finish),
        sidecar=JarvisSidecarEvidence.model_validate_json(canonical_bytes(proof), strict=True),
        context=CONTEXT,
        policy=config.handoff_policy,
    )


def test_original_cancelled_reservation_releases_slot_once(tmp_path: Path) -> None:
    provider, cfg, raw, proof = cancelled_runtime(tmp_path)
    request = FinishProgressRequest.model_validate(raw)
    before = request.expected_checkpoint
    with closing(sqlite3.connect(provider.database)) as db:
        before_receipts: list[tuple[str, str]] = db.execute(
            "SELECT receipt_id,receipt_digest FROM company_memory_receipts ORDER BY receipt_id",
        ).fetchall()
    result = finish_with_proof(provider, cfg, raw, proof)
    assert isinstance(result, FinishProgressResponse)
    assert result.outcome == "recorded" and result.checkpoint is not None
    assert result.checkpoint.stores.jarvis.receipt_sequence == before.stores.jarvis.receipt_sequence
    assert (
        result.checkpoint.stores.jarvis.terminal_sequence
        == before.stores.jarvis.terminal_sequence + 1
    )
    anchored = provider.anchor.read_value()
    provider = CompanyDbFreshnessProvider(
        database=provider.database,
        registry_path=provider.registry_path,
        witness_dir=provider.witness_dir,
        lock_path=provider.lock_path,
        anchor=provider.anchor,
        registry_id=provider.registry_id,
        actor_store="jarvis",
        clock=lambda: format_instant(NOW),
    )
    replay_raw: JsonObject = dict(raw)
    replay_raw["challenge"] = "cancel:finish:retry"
    replay = finish_with_proof(provider, cfg, replay_raw, proof)
    assert isinstance(replay, FinishProgressResponse) and replay.outcome == "already_recorded"
    assert replay.checkpoint == result.checkpoint
    assert provider.anchor.read_value() == anchored
    with closing(sqlite3.connect(provider.database)) as db:
        original: list[tuple[str, str]] = db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations WHERE operation_id=?",
            (request.operation_id,),
        ).fetchall()
        receipts: list[tuple[str, str]] = db.execute(
            "SELECT receipt_id,receipt_digest FROM company_memory_receipts ORDER BY receipt_id",
        ).fetchall()
        candidates: list[tuple[str]] = db.execute(
            "SELECT state FROM company_memory_candidates",
        ).fetchall()
    assert original == [("finished", "cancelled")]
    assert receipts == before_receipts
    assert candidates == [("candidate",)]
    record_id = proof["source_record_id"]
    assert isinstance(record_id, str)
    with closing(sqlite3.connect(provider.database)) as db:
        retained: list[tuple[str, str, str]] = db.execute(
            """SELECT stream,source_digest,evidence_json FROM company_freshness_evidence
            WHERE source_record_id=?""",
            (record_id,),
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            _ = db.execute(
                "UPDATE company_freshness_operations SET terminal_state='approved' WHERE operation_id=?",
                (request.operation_id,),
            )
    assert len(retained) == 1 and retained[0][:2] == ("terminal", request.evidence_digest)
    projection = strict_loads(retained[0][2], 16_384)
    assert is_json_object(projection)
    metadata = projection["metadata"]
    assert is_json_object(metadata)
    assert metadata["kind"] == "cancellation"
    assert metadata["original_at"] == proof["original_at"]
    assert "reason" not in metadata
    following = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=request.scope,
            operation_id=operation_id_for(
                request.scope,
                request_id="after-cancel",
                command_digest="sha256:" + "b" * 64,
                operation="decide_approve",
            ),
            operation="decide_approve",
            expected_checkpoint=result.checkpoint,
            event_digest="sha256:" + "b" * 64,
            challenge="after-cancel:reserve",
        ),
    )
    assert isinstance(following, ReserveProgressResponse) and following.outcome == "reserved"


@pytest.mark.parametrize(
    "fault",
    [
        "payload_digest",
        "payload_json",
        "request_id",
        "command_digest",
        "revocation_id",
        "receipt_id",
        "state",
        "lease_fence",
        "effect_record_id",
    ],
)
def test_cancellation_requires_original_revocation_and_no_effect(
    tmp_path: Path,
    fault: str,
) -> None:
    provider, cfg, raw, proof = cancelled_runtime(tmp_path)
    record = proof["record"]
    assert is_json_object(record)
    revocation = record["revocation"]
    assert is_json_object(revocation)
    match fault:
        case "state":
            record["state"] = "uncertain"
        case "lease_fence":
            record["lease_fence"] = 1
        case "effect_record_id":
            record["effect_record_id"] = "effect:already-executed"
        case "payload_json":
            revocation["payload_json"] = "{}"
        case "receipt_id":
            revocation["receipt_id"] = "receipt:already-approved"
        case _:
            revocation[fault] = "sha256:" + "c" * 64
    before = provider.anchor.read_value()
    result = finish_with_proof(provider, cfg, raw, proof)
    assert isinstance(result, FinishProgressResponse) and result.outcome == "conflict"
    assert provider.anchor.read_value() == before
    with closing(sqlite3.connect(provider.database)) as db:
        states: list[tuple[str]] = db.execute(
            "SELECT state FROM company_freshness_operations",
        ).fetchall()
    assert states == [("reserved",)]


def test_cancelled_requires_authenticated_original_sidecar(tmp_path: Path) -> None:
    provider, _cfg, raw, _proof = cancelled_runtime(tmp_path)
    result = provider.finish_progress(FinishProgressRequest.model_validate(raw))
    assert isinstance(result, FinishProgressResponse) and result.outcome == "conflict"


def test_unknown_terminal_state_is_not_normalized(tmp_path: Path) -> None:
    _provider, _cfg, raw, _proof = cancelled_runtime(tmp_path)
    raw["terminal_state"] = "cancelled_else"
    with pytest.raises(ValidationError):
        _ = FinishProgressRequest.model_validate(raw)


@pytest.mark.parametrize("disguised", ["approved", "rejected"])
def test_cancellation_is_not_an_approval_or_rejection(tmp_path: Path, disguised: str) -> None:
    provider, cfg, raw, proof = cancelled_runtime(tmp_path)
    raw["terminal_state"] = disguised
    before = provider.anchor.read_value()
    result = finish_with_proof(provider, cfg, raw, proof)
    assert isinstance(result, FinishProgressResponse) and result.outcome == "conflict"
    assert provider.anchor.read_value() == before


@pytest.mark.parametrize(
    ("original_at", "normalized_at", "outcome"),
    [
        ("2026-09-22T19:00:00+09:00", "2026-09-22T10:00:00.000Z", "recorded"),
        ("2026-09-22", "2026-09-22T00:00:00.000Z", "conflict"),
    ],
)
def test_original_revocation_payload_time_is_not_rewritten(
    tmp_path: Path,
    original_at: str,
    normalized_at: str,
    outcome: str,
) -> None:
    provider, cfg, raw, proof = cancelled_runtime(tmp_path)
    record = proof["record"]
    assert is_json_object(record)
    revocation = record["revocation"]
    assert is_json_object(revocation)
    payload_json = revocation["payload_json"]
    assert isinstance(payload_json, str)
    payload = strict_loads(payload_json, 16_384)
    assert is_json_object(payload)
    payload["revoked_at"] = original_at
    original_json = canonical_bytes(payload).decode("utf-8")
    original_digest = "sha256:" + hashlib.sha256(original_json.encode("utf-8")).hexdigest()
    source_id = "control-revocation:" + original_digest.removeprefix("sha256:")
    revocation["payload_json"] = original_json
    revocation["payload_digest"] = original_digest
    revocation["revoked_at"] = original_at
    revocation["revocation_id"] = source_id
    proof["source_record_id"] = source_id
    proof["original_at"] = normalized_at
    raw["evidence_digest"] = original_digest
    result = finish_with_proof(provider, cfg, raw, proof)
    assert isinstance(result, FinishProgressResponse) and result.outcome == outcome
    assert revocation["payload_json"] == original_json
    if outcome != "recorded":
        return
    with closing(sqlite3.connect(provider.database)) as db:
        sources: list[tuple[str]] = db.execute(
            "SELECT source_digest FROM company_freshness_evidence WHERE source_record_id=?",
            (source_id,),
        ).fetchall()
    assert sources == [(original_digest,)]


def test_shared_cancellation_fixture_uses_original_revocation_payload() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/company-approver/company-cancellation-v1.test-only.json"
    )
    fixture = strict_loads(path.read_bytes(), 65_536)
    assert is_json_object(fixture)
    raw = fixture["finish_request"]
    assert is_json_object(raw)
    request = FinishProgressRequest.model_validate(raw)
    sidecar = JarvisSidecarEvidence.model_validate_json(
        canonical_bytes(fixture["sidecar"]), strict=True
    )
    proof = JarvisCancellationV1.model_validate(sidecar.record)
    payload = strict_loads(proof.revocation.payload_json, 16_384)
    original_digest = "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert request.terminal_state == "cancelled"
    assert request.evidence_digest == proof.revocation.payload_digest == original_digest
    assert request.operation_id == operation_id_for(
        request.scope,
        request_id=sidecar.command.request_id,
        command_digest=proof.revocation.command_digest,
        operation="decide_approve",
    )
    assert sidecar.source_record_id == "control-revocation:" + original_digest.removeprefix(
        "sha256:"
    )
    unknown = fixture["unknown_terminal_states"]
    assert isinstance(unknown, list) and unknown
    for value in unknown:
        malformed: JsonObject = dict(raw)
        malformed["terminal_state"] = value
        with pytest.raises(ValidationError):
            _ = FinishProgressRequest.model_validate(malformed)
def test_revocation_before_command_is_rejected(tmp_path: Path) -> None:
    from datetime import timedelta

    provider, cfg, raw, proof = cancelled_runtime(tmp_path)
    record = proof["record"]
    assert is_json_object(record)
    revocation = record["revocation"]
    assert is_json_object(revocation)
    command = proof["command"]
    assert is_json_object(command)
    requested_at = command["requested_at"]
    assert isinstance(requested_at, str)
    earlier = format_instant(parse_instant(requested_at) - timedelta(seconds=1))
    payload_json = revocation["payload_json"]
    assert isinstance(payload_json, str)
    payload = strict_loads(payload_json, 16_384)
    assert is_json_object(payload)
    payload["revoked_at"] = earlier
    encoded = canonical_bytes(payload)
    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    revocation["revoked_at"] = earlier
    revocation["payload_json"] = encoded.decode("utf-8")
    revocation["payload_digest"] = digest
    revocation["revocation_id"] = "control-revocation:" + digest.removeprefix("sha256:")
    revocation["created_at"] = earlier
    proof["source_record_id"] = revocation["revocation_id"]
    proof["original_at"] = earlier
    raw["evidence_digest"] = digest
    result = finish_with_proof(provider, cfg, raw, proof)
    assert isinstance(result, FinishProgressResponse) and result.outcome == "conflict"
