from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from typing import Final, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from sb.company_auto_settings import (
    POLICY_ISSUER,
    AutoInternalRejected,
    AutoInternalSettings,
    AutoPolicySigner,
    InternalAutoPolicyV1,
)
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_classifier import CLASSIFIER_VERSION
from sb.delegations import DelegationRejected, verify_signed_object
from sb.effect_values import JsonObject, canonical_bytes, format_instant, parse_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

POLICY_DOMAIN: Final = b"second-brain/company-policy-auto/v1\0"
AUTO_ID_DOMAIN: Final = b"second-brain/company-auto/v1\0"
ASSESSMENT_DOMAIN: Final = b"second-brain/company-auto-assessment/v1\0"
POLICY_DIGEST_DOMAIN: Final = b"second-brain/company-internal-policy/v1\0"
ALLOWED: Final[tuple[Literal["accept", "complete", "mark_processed"], ...]] = (
    "accept",
    "complete",
    "mark_processed",
)


class PolicyAutoReceiptV1(ClosedModel):
    schema_version: Literal[1]
    auto_request_id: str
    scope: FreshnessScope
    candidate_id: str
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_event_id: str
    policy_version: int = Field(ge=1)
    policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    classifier_version: str = Field(min_length=1, max_length=128)
    allowed_operations: list[Literal["accept", "complete", "mark_processed"]]
    issuer_principal_id: Literal["principal:company-internal-automation"]
    issued_at: str
    expires_at: str
    nonce: str
    command_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: str


def policy_digest(policy: InternalAutoPolicyV1) -> str:
    raw = hashlib.sha256(POLICY_DIGEST_DOMAIN + canonical_bytes(model_object(policy))).hexdigest()
    return "sha256:" + raw


def auto_request_id(
    scope: FreshnessScope, candidate_id: str, content_digest: str, digest: str
) -> str:
    body = {
        "scope": model_object(scope),
        "candidate_id": candidate_id,
        "content_digest": content_digest,
        "policy_digest": digest,
    }
    return "company-auto:v1:" + hashlib.sha256(AUTO_ID_DOMAIN + canonical_bytes(body)).hexdigest()


def assessment_digest(
    *,
    candidate_id: str,
    content_digest: str,
    policy_digest_value: str,
    classification: str,
    reason_codes: tuple[str, ...],
    payload: JsonObject | None,
    classifier_version: str = CLASSIFIER_VERSION,
) -> str:
    body: JsonObject = {
        "candidate_id": candidate_id,
        "classification": classification,
        "content_digest": content_digest,
        "policy_digest": policy_digest_value,
        "reason_codes": list(reason_codes),
        "typed_payload": payload,
        "classifier_version": classifier_version,
    }
    return "sha256:" + hashlib.sha256(ASSESSMENT_DOMAIN + canonical_bytes(body)).hexdigest()


def command_digest(command: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(command)).hexdigest()


def auto_command(
    *,
    scope: FreshnessScope,
    request_id: str,
    candidate_id: str,
    content_digest: str,
    policy_digest_value: str,
    assessment_digest_value: str,
    record_kind: str,
) -> JsonObject:
    return {
        "schema_version": 1,
        "action": "company.internal.record",
        "request_id": request_id,
        "scope": model_object(scope),
        "candidate_id": candidate_id,
        "content_digest": content_digest,
        "policy_digest": policy_digest_value,
        "assessment_digest": assessment_digest_value,
        "record_kind": record_kind,
    }


def sign_policy_receipt(
    signer: AutoPolicySigner,
    unsigned: PolicyAutoReceiptV1,
) -> PolicyAutoReceiptV1:
    if signer.principal_id != POLICY_ISSUER or unsigned.signature != "":
        raise AutoInternalRejected("POLICY_SIGNER_REJECTED")
    body = model_object(unsigned)
    unsigned_body = {key: value for key, value in body.items() if key != "signature"}
    raw = signer.private_key.sign(POLICY_DOMAIN + canonical_bytes(unsigned_body))
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signed = dict(unsigned_body)
    signed["signature"] = encoded
    return PolicyAutoReceiptV1.model_validate(signed)


def verify_policy_receipt(
    receipt: PolicyAutoReceiptV1,
    public_key: Ed25519PublicKey,
) -> None:
    if receipt.allowed_operations != list(ALLOWED) or receipt.nonce != receipt.auto_request_id:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    issued = parse_instant(receipt.issued_at)
    expires = parse_instant(receipt.expires_at)
    if expires - issued != timedelta(minutes=5):
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    try:
        verify_signed_object(
            model_object(receipt),
            public_key,
            POLICY_DOMAIN,
            "POLICY_RECEIPT_REJECTED",
        )
    except DelegationRejected as exc:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED") from exc


def receipt_expired(receipt: PolicyAutoReceiptV1, now_text: str) -> bool:
    return parse_instant(now_text) >= parse_instant(receipt.expires_at)


def build_unsigned_receipt(
    settings: AutoInternalSettings,
    *,
    scope: FreshnessScope,
    candidate_id: str,
    content_digest: str,
    source_event_id: str,
    assessment_digest_value: str,
    command_digest_value: str,
    issued_at: str,
) -> PolicyAutoReceiptV1:
    digest = policy_digest(settings.policy)
    request_id = auto_request_id(scope, candidate_id, content_digest, digest)
    try:
        expires = format_instant(parse_instant(issued_at) + timedelta(minutes=5))
    except ValueError as exc:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED") from exc
    try:
        return PolicyAutoReceiptV1(
            schema_version=1,
            auto_request_id=request_id,
            scope=scope,
            candidate_id=candidate_id,
            content_digest=content_digest,
            source_event_id=source_event_id,
            policy_version=settings.policy.policy_version,
            policy_digest=digest,
            assessment_digest=assessment_digest_value,
            classifier_version=CLASSIFIER_VERSION,
            allowed_operations=["accept", "complete", "mark_processed"],
            issuer_principal_id=POLICY_ISSUER,
            issued_at=issued_at,
            expires_at=expires,
            nonce=request_id,
            command_digest=command_digest_value,
            signature="",
        )
    except ValidationError as exc:
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED") from exc
