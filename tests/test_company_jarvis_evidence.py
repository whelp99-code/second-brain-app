"""Use the original JARVIS approval signature and unsigned completion-v2 record."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sb.company_db_freshness import CompanyDbFreshnessProvider, JarvisSidecarEvidence
from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness_models import (
    Checkpoint,
    FinishProgressRequest,
    FreshnessScope,
    ReserveProgressRequest,
)
from sb.company_memory_cli import run
from sb.company_memory_cli_config import load_company_config
from sb.company_memory_handoff import CompanyControlRequest
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from tests.test_company_candidate_handoff import (
    CONTEXT,
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    signed_request,
)
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW


def complete_sidecar(
    provider: CompanyDbFreshnessProvider,
    request: ReserveProgressRequest,
    sidecar: JarvisSidecarEvidence,
    digest: str,
    checkpoint: Checkpoint,
    cfg: Path,
) -> Checkpoint:
    config = load_company_config(cfg)
    assert config.handoff_policy is not None
    reserved = provider.reserve_progress(request)
    assert reserved.outcome == "reserved"
    assert reserved.reservation_id is not None and reserved.checkpoint is not None
    terminal = "completed" if request.operation == "complete" else "approved"
    result = provider.finish_with_jarvis_sidecar(
        FinishProgressRequest(
            schema_version=2,
            scope=request.scope,
            operation_id=request.operation_id,
            reservation_id=reserved.reservation_id,
            expected_checkpoint=reserved.checkpoint,
            evidence_digest=digest,
            terminal_state=terminal,
            challenge="finish:" + request.operation_id,
        ),
        sidecar,
        context=CONTEXT,
        policy=config.handoff_policy,
    )
    assert result.outcome == "recorded"
    assert result.checkpoint is not None and result.checkpoint != checkpoint
    return result.checkpoint


def test_original_approval_and_completion_prove_human_mark_processed(tmp_path: Path) -> None:
    cfg, sb = human_runtime(tmp_path)
    jarvis = CompanyDbFreshnessProvider(
        database=sb.database,
        actor_store="jarvis",
        registry_path=sb.registry_path,
        witness_dir=sb.witness_dir,
        lock_path=sb.lock_path,
        anchor=sb.anchor,
        registry_id=sb.registry_id,
        clock=lambda: format_instant(NOW),
    )
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=sb,
        )
    )
    approval = owner_receipt(proposal)
    command_value = proposal["command"]
    assert isinstance(command_value, dict)
    command = CompanyControlRequest.model_validate_json(canonical_bytes(command_value), strict=True)
    digest = proposal["command_digest"]
    assert isinstance(digest, str)
    approval_digest = "sha256:" + hashlib.sha256(canonical_bytes(approval)).hexdigest()
    scope = FreshnessScope(provider_instance_id=CONTEXT.provider, workspace_id=CONTEXT.workspace_id)
    before = local_checkpoint(sb.database, CONTEXT.workspace_id, None)
    assert before is not None
    _ = complete_sidecar(
        jarvis,
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id_for(
                scope,
                request_id=command.request_id,
                command_digest=digest,
                operation="decide_approve",
            ),
            operation="decide_approve",
            expected_checkpoint=before,
            event_digest=approval_digest,
            challenge="original:decide",
        ),
        JarvisSidecarEvidence(
            schema_version=1,
            kind="representative_receipt",
            source_record_id="owner-receipt:1",
            original_at=format_instant(NOW),
            command=command,
            record=approval,
        ),
        approval_digest,
        before,
        cfg,
    )
    accepted = run(
        cfg,
        signed_request(
            "accept",
            processor_arguments(proposal, approval),
            PROCESSOR_KEY,
            "processor",
            PROCESSOR,
        ),
        now=NOW,
        process_only=True,
        freshness_provider=sb,
    )
    mark_request = signed_request(
        "mark_processed",
        processor_arguments(proposal),
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
    )
    with pytest.raises(ValueError, match="COMPANY_RECEIPT_EVIDENCE_ABSENT"):
        _ = run(cfg, mark_request, now=NOW, process_only=True, freshness_provider=sb)
    acceptance = accepted["receipt_digest"]
    assert isinstance(acceptance, str)
    accepted_head = local_checkpoint(sb.database, CONTEXT.workspace_id, None)
    assert accepted_head is not None
    effect_digest = "sha256:" + "ef" * 32
    completion: JsonObject = {
        "schema_version": 2,
        "state": "completed",
        "request_id": command.request_id,
        "command_digest": digest,
        "candidate_id": command.target.candidate_id,
        "content_digest": command.target.content_digest,
        "acceptance_receipt_digest": acceptance,
        "effect_digest": effect_digest,
    }
    _ = complete_sidecar(
        jarvis,
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id_for(
                scope,
                request_id=command.request_id,
                command_digest=digest,
                operation="complete",
            ),
            operation="complete",
            expected_checkpoint=accepted_head,
            event_digest=acceptance,
            challenge="original:complete",
        ),
        JarvisSidecarEvidence(
            schema_version=1,
            kind="completion",
            source_record_id="completion:" + command.request_id,
            original_at=format_instant(NOW),
            command=command,
            record=completion,
        ),
        effect_digest,
        accepted_head,
        cfg,
    )
    marked = run(cfg, mark_request, now=NOW, process_only=True, freshness_provider=sb)
    assert marked["state"] == "processed_complete"
