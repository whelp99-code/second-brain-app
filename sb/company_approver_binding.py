"""Company-only operator pins; request fields never choose an approver."""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from typing import Annotated, Final, Literal, Self

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_validator

from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

ID: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
DIGEST: Final = r"^sha256:[0-9a-f]{64}$"
type SafeInteger = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
type PositiveInteger = Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
type Identifier = Annotated[str, Field(pattern=ID)]
type Digest = Annotated[str, Field(pattern=DIGEST)]
BINDING_DOMAIN: Final = b"second-brain/company-approval-binding/v1\0"


class ApproverKeyPin(ClosedModel):
    key_id: Identifier
    algorithm: Literal["Ed25519"]
    purpose: Literal["decision"]
    public_key_fingerprint: Digest


class CompanyHandoffPolicy(ClosedModel):
    processor_principal_id: Identifier
    processor_keys: dict[str, str] = Field(min_length=1)
    owner_approval_keys: dict[str, str] = Field(min_length=1)
    approver_principal_id: Identifier
    approval_policy_version: PositiveInteger
    approver_keys: list[ApproverKeyPin] = Field(min_length=1)
    operator_approval_ref: Identifier

    @model_validator(mode="after")
    def pins_match_keys(self) -> Self:
        ids = [pin.key_id for pin in self.approver_keys]
        fingerprints = [pin.public_key_fingerprint for pin in self.approver_keys]
        if (
            ids != sorted(set(ids))
            or len(fingerprints) != len(set(fingerprints))
            or set(ids) != set(self.owner_approval_keys)
            or self.approver_principal_id == self.processor_principal_id
        ):
            raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")
        for pin in self.approver_keys:
            if public_key_fingerprint(decode_key(self.owner_approval_keys[pin.key_id])) != (
                pin.public_key_fingerprint
            ):
                raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")
        return self


def decode_key(encoded: str) -> Ed25519PublicKey:
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded) is None:
        raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")
    raw = base64.urlsafe_b64decode(encoded + "=")
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != encoded:
        raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")
    return Ed25519PublicKey.from_public_bytes(raw)


def public_key_fingerprint(key: Ed25519PublicKey) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest()
    )


def binding_document(context: CompanyAuthorityContext, policy: CompanyHandoffPolicy) -> JsonObject:
    if len({context.principal, policy.approver_principal_id, policy.processor_principal_id}) != 3:
        raise CompanyAuthorityRejected("COMPANY_APPROVAL_INVALID")
    return {
        "provider_instance_id": context.provider,
        "workspace_id": context.workspace_id,
        "owner": context.principal,
        "processor_principal_id": policy.processor_principal_id,
        "approver_principal_id": policy.approver_principal_id,
        "approval_policy_version": policy.approval_policy_version,
        "wire_revision": 2,
        "approver_keys": [model_object(pin) for pin in policy.approver_keys],
    }


def binding_digest(context: CompanyAuthorityContext, policy: CompanyHandoffPolicy) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            BINDING_DOMAIN + canonical_bytes(binding_document(context, policy)),
        ).hexdigest()
    )


def validate_candidate_id(value: str) -> str:
    if (
        not 1 <= len(value) <= 2048
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    return value
