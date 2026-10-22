from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_approver_binding import public_key_fingerprint
from sb.company_db_freshness_models import FreshnessRegistry, RegistryApprovalRevocation
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory_cli import run
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes, format_instant, strict_loads
from sb.effect_write_values import model_object
from tests.test_company_candidate_handoff import (
    CONTEXT,
    OWNER_KEY,
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


@pytest.mark.parametrize("pending_reserve", [False, True])
def test_protected_revocation_survives_restored_original_human_config(
    tmp_path: Path,
    pending_reserve: bool,
) -> None:
    cfg, provider = human_runtime(tmp_path)
    original_config = cfg.read_bytes()
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    request = signed_request(
        "accept",
        processor_arguments(proposal, owner_receipt(proposal)),
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
    )
    if pending_reserve:
        provider.lose, provider.after = True, True
        with pytest.raises(ValueError):
            _ = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    checkpoint = local_checkpoint(provider.database, CONTEXT.workspace_id, None)
    assert checkpoint is not None
    scope = FreshnessScope(provider_instance_id=CONTEXT.provider, workspace_id=CONTEXT.workspace_id)
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    revoked = RegistryApprovalRevocation(
        scope=scope,
        source_record_id="operator:owner-key-revocation:1",
        original_at=format_instant(NOW),
        approval_policy_version=1,
        approval_binding_digest=checkpoint.approval_binding_digest,
        reason="key_revoked",
        revoked_key_fingerprints=[public_key_fingerprint(OWNER_KEY.public_key())],
    )
    registry = registry.model_copy(update={"approval_revocations": [revoked]})
    _ = provider.registry_path.write_bytes(canonical_bytes(model_object(registry)))
    with pytest.raises(AnchorRejected, match="COMPANY_APPROVAL_REVOKED"):
        _ = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    closed = provider.record_approval_revocations(scope)
    assert closed.operational_epoch == checkpoint.operational_epoch
    assert closed.approval_binding_digest == checkpoint.approval_binding_digest
    assert closed.revocation_sequence == checkpoint.revocation_sequence + 1
    anchored = provider.anchor.read_value()
    assert provider.record_approval_revocations(scope) == closed
    assert provider.anchor.read_value() == anchored
    removed = strict_loads(original_config, 65_536)
    assert isinstance(removed, dict)
    removed["handoff_policy"] = None
    _ = cfg.write_bytes(canonical_bytes(removed))
    _ = cfg.write_bytes(original_config)
    with pytest.raises((ValueError, AnchorRejected)):
        _ = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id=provider.installation_id,
            challenge="restored:old:approval",
            observed_checkpoint=closed,
        )
    )
    assert response.status == "mismatch"
    with closing(sqlite3.connect(provider.database)) as db:
        receipts: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE operation='accept'",
        ).fetchall()
        pending: list[tuple[int]] = db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE state='reserved'",
        ).fetchall()
    assert receipts == [(0,)]
    assert pending == [(int(pending_reserve),)]
