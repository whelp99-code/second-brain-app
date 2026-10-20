from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field

from sb.company_freshness_models import Checkpoint
from sb.effect_values import canonical_bytes, parse_instant
from sb.effect_write_models import ClosedModel

POLICY_ISSUER: Final = "principal:company-internal-automation"
TRIGGER_PURPOSE: Final = "company_internal_auto_trigger"
REPORT_PURPOSE: Final = "company_memory_auto_report"
AUTO_OPERATION: Final = "auto_process_internal"
REPORT_OPERATION: Final = "read_auto_report"
FIXED_TRIGGER_LIMIT: Final = 100


class AutoInternalRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code: str = code
        super().__init__(code)


class InternalAutoPolicyV1(ClosedModel):
    schema_version: Literal["company-internal-auto/v1"]
    policy_version: int = Field(ge=1, le=9_007_199_254_740_991)
    internal_email_suffixes: list[
        Annotated[
            str,
            Field(
                pattern=(
                    r"^[@.][a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
                )
            ),
        ]
    ] = Field(min_length=1)
    internal_assignees: list[str] = Field(min_length=1)
    allowed_kinds: list[Literal["contact", "calendar", "progress"]] = Field(min_length=1)


class AutoTriggerGrant(ClosedModel):
    schema_version: Literal[1]
    operation: Literal["auto_process_internal"]
    purpose: Literal["company_internal_auto_trigger"]
    principal_id: str = Field(min_length=1)
    limit: Literal[100]
    issued_at: str
    expires_at: str


class AutoReportGrant(ClosedModel):
    schema_version: Literal[1]
    operation: Literal["read_auto_report"]
    purpose: Literal["company_memory_auto_report"]
    principal_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class AutoPolicySigner:
    principal_id: Literal["principal:company-internal-automation"]
    key_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class AutoInternalSettings:
    provider_instance_id: str
    installation_id: str
    policy: InternalAutoPolicyV1
    signer: AutoPolicySigner
    revoked_policy_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AutoInternalContext:
    workspace_id: str
    owner: str
    projects: tuple[str, ...]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str
    observed_checkpoint: Checkpoint
    now: datetime
    clock: Callable[[], datetime] | None = None


def require_live_trigger(trigger: AutoTriggerGrant, now: datetime) -> None:
    try:
        issued = parse_instant(trigger.issued_at)
        expires = parse_instant(trigger.expires_at)
    except ValueError as exc:
        raise AutoInternalRejected("TRIGGER_REJECTED") from exc
    if (
        trigger.principal_id != "principal:jarvis-company-progress"
        or not issued <= now < expires
        or not timedelta(0) < expires - issued <= timedelta(seconds=60)
    ):
        raise AutoInternalRejected("TRIGGER_REJECTED")


class SourceContext(ClosedModel):
    workspace_id: str
    owner: str
    projects: list[str]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str


def source_context_digest(
    provider_instance_id: str,
    context: AutoInternalContext | SourceContext,
) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            b"second-brain/company-internal-source-context/v1\0"
            + canonical_bytes(
                {
                    "provider_instance_id": provider_instance_id,
                    "workspace_id": context.workspace_id,
                    "owner": context.owner,
                    "projects": list(context.projects),
                    "policy_revision": context.policy_revision,
                    "deletion_sequence": context.deletion_sequence,
                    "deletion_set_root": context.deletion_set_root,
                }
            ),
        ).hexdigest()
    )


def bind_policy_signer(
    principal_id: str,
    key_id: str,
    private_key: Ed25519PrivateKey,
) -> AutoPolicySigner:
    if principal_id != POLICY_ISSUER or not key_id.startswith("policy-auto:"):
        raise AutoInternalRejected("POLICY_SIGNER_REJECTED")
    if key_id.removeprefix("policy-auto:") == "":
        raise AutoInternalRejected("POLICY_SIGNER_REJECTED")
    public_key = private_key.public_key()
    return AutoPolicySigner(
        principal_id="principal:company-internal-automation",
        key_id=key_id,
        private_key=private_key,
        public_key=public_key,
    )


def policy_operation_allowed(operation: str) -> bool:
    match operation:
        case "accept" | "complete" | "mark_processed":
            return True
        case _:
            return False
