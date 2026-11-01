from __future__ import annotations

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    build_unsigned_receipt,
    policy_digest,
    sign_policy_receipt,
    verify_policy_receipt,
)
from sb.company_auto_settings import (
    AutoInternalRejected,
    bind_policy_signer,
    policy_operation_allowed,
)
from sb.company_freshness import FreshnessScope
from sb.company_memory_handoff import CommandApprovalReceipt
from sb.effect_values import format_instant
from tests.company_internal_auto_support import NOW, PROVIDER, WORKSPACE, settings


def test_policy_receipt_is_not_a_command_approval() -> None:
    bound = settings()
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    unsigned = build_unsigned_receipt(
        bound,
        scope=scope,
        candidate_id="mail:1",
        content_digest="sha256:" + "ab" * 32,
        source_event_id="event:1",
        assessment_digest_value="sha256:" + "cd" * 32,
        command_digest_value="sha256:" + "ef" * 32,
        issued_at=format_instant(NOW),
    )
    receipt = sign_policy_receipt(bound.signer, unsigned)
    verify_policy_receipt(receipt, bound.signer.public_key)
    with pytest.raises(ValidationError):
        _ = CommandApprovalReceipt.model_validate(receipt.model_dump())
    assert receipt.issuer_principal_id == "principal:company-internal-automation"
    assert policy_operation_allowed("delete") is False
    assert policy_operation_allowed("decide_approve") is False
    assert policy_operation_allowed("accept") is True


def test_owner_key_id_is_rejected() -> None:
    with pytest.raises(AutoInternalRejected):
        _ = bind_policy_signer("principal:owner", "owner:1", Ed25519PrivateKey.generate())


def test_same_identity_reuses_request_id_when_clock_changes() -> None:
    bound = settings()
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    first = build_unsigned_receipt(
        bound,
        scope=scope,
        candidate_id="mail:1",
        content_digest="sha256:" + "ab" * 32,
        source_event_id="event:1",
        assessment_digest_value="sha256:" + "cd" * 32,
        command_digest_value="sha256:" + "ef" * 32,
        issued_at=format_instant(NOW),
    )
    later = build_unsigned_receipt(
        bound,
        scope=scope,
        candidate_id="mail:1",
        content_digest="sha256:" + "ab" * 32,
        source_event_id="event:1",
        assessment_digest_value="sha256:" + "cd" * 32,
        command_digest_value="sha256:" + "ef" * 32,
        issued_at=format_instant(NOW + timedelta(minutes=10)),
    )
    assert first.auto_request_id == later.auto_request_id
    assert first.expires_at != later.expires_at
    assert policy_digest(bound.policy).startswith("sha256:")


def test_receipt_round_trip_rejects_wrong_key() -> None:
    bound = settings()
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    receipt = sign_policy_receipt(
        bound.signer,
        build_unsigned_receipt(
            bound,
            scope=scope,
            candidate_id="mail:1",
            content_digest="sha256:" + "ab" * 32,
            source_event_id="event:1",
            assessment_digest_value="sha256:" + "cd" * 32,
            command_digest_value="sha256:" + "ef" * 32,
            issued_at=format_instant(NOW),
        ),
    )
    other = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(AutoInternalRejected):
        verify_policy_receipt(receipt, other)
    assert PolicyAutoReceiptV1.model_validate(receipt.model_dump()) == receipt
