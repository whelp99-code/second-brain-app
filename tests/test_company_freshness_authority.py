"""The broker's extra operations cannot borrow human or receive authority."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from sb.company_memory_authority import (
    CompanyAuthorityRejected,
    CompanyKeyScope,
    CompanyOperation,
    verify_company_authority,
)
from sb.effect_values import JsonObject, canonical_bytes, format_instant
from tests.test_company_memory_product import CONTEXT, KEY, KEY_ID, NOW, signed_authority

ARGUMENTS: JsonObject = {
    "request": {"schema_version": 2, "challenge": "freshness-challenge"},
    "evidence": None,
}


def test_freshness_signature_binds_separate_method_request_evidence_domain() -> None:
    # Given: a live, explicitly scoped broker key and signed request.
    claim = signed_authority("read_freshness", ARGUMENTS)
    scope = CompanyKeyScope(operations=["read_freshness"], source_systems=["mail"])
    expected = "sha256:" + hashlib.sha256(
        b"second-brain/company-freshness-request/v1\0" + canonical_bytes({
            "method": "read_freshness",
            "request": ARGUMENTS["request"],
            "evidence": None,
        }),
    ).hexdigest()

    # When: the existing authority verifier authenticates the broker envelope.
    verified, _ = verify_company_authority(
        claim, ARGUMENTS, {KEY_ID: KEY.public_key()}, CONTEXT, NOW,
        key_scopes={KEY_ID: scope},
    )

    # Then: the frozen outer digest includes method, request and evidence.
    assert verified.request_digest == expected


@pytest.mark.parametrize("operation", [
    "read_freshness", "reserve_progress", "finish_progress",
    "auto_process_internal", "read_auto_report",
])
def test_new_operation_requires_explicit_key_scope(operation: CompanyOperation) -> None:
    arguments: JsonObject = (
        ARGUMENTS
        if operation in {"read_freshness", "reserve_progress", "finish_progress"}
        else {"limit": 100}
    )
    claim = signed_authority(operation, arguments)
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_KEY_OPERATION_DENIED"):
        _ = verify_company_authority(
            claim, arguments, {KEY_ID: KEY.public_key()}, CONTEXT, NOW,
        )


def test_freshness_key_cannot_authorize_human_accept() -> None:
    arguments: JsonObject = {"candidate_id": "mail:candidate:1"}
    claim = signed_authority("accept", arguments)
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_KEY_OPERATION_DENIED"):
        _ = verify_company_authority(
            claim, arguments, {KEY_ID: KEY.public_key()}, CONTEXT, NOW,
            key_scopes={
                KEY_ID: CompanyKeyScope(operations=["read_freshness"], source_systems=["mail"]),
            },
        )


def test_freshness_evidence_tampering_invalidates_authority() -> None:
    claim = signed_authority("finish_progress", ARGUMENTS)
    tampered: JsonObject = {**ARGUMENTS, "evidence": {"effect_digest": "untrusted"}}
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_AUTHORITY_REQUIRED"):
        _ = verify_company_authority(
            claim, tampered, {KEY_ID: KEY.public_key()}, CONTEXT, NOW,
            key_scopes={
                KEY_ID: CompanyKeyScope(operations=["finish_progress"], source_systems=["mail"]),
            },
        )


def test_freshness_authority_cannot_exceed_sixty_seconds() -> None:
    claim = signed_authority("reserve_progress", ARGUMENTS, {
        "expires_at": format_instant(NOW + timedelta(seconds=61)),
    })
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_AUTHORITY_REQUIRED"):
        _ = verify_company_authority(
            claim, ARGUMENTS, {KEY_ID: KEY.public_key()}, CONTEXT, NOW,
            key_scopes={
                KEY_ID: CompanyKeyScope(operations=["reserve_progress"], source_systems=["mail"]),
            },
        )
