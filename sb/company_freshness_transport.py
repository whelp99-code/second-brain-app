"""Authenticate the fixed broker envelope without changing freshness wire."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, field_validator

from sb.company_freshness_models import (
    FinishProgressRequest,
    FreshnessScope,
    ReadFreshnessRequest,
    ReserveProgressRequest,
)
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyMemoryAuthorityV1,
    canonical_workspace_id,
    verify_company_authority,
)
from sb.company_memory_cli_config import CompanyCliConfigV1, company_trusted_keys
from sb.effect_values import JsonObject, JsonValue, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class _BrokerAuthorityEnvelope(ClosedModel):
    schema_version: Literal[1]
    authority: CompanyMemoryAuthorityV1

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: JsonValue) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
        return value


class FreshnessReadEnvelope(_BrokerAuthorityEnvelope):
    method: Literal["read_freshness"]
    request: ReadFreshnessRequest
    evidence: None


class FreshnessReserveEnvelope(_BrokerAuthorityEnvelope):
    method: Literal["reserve_progress"]
    request: ReserveProgressRequest
    evidence: None


class FreshnessFinishEnvelope(_BrokerAuthorityEnvelope):
    method: Literal["finish_progress"]
    request: FinishProgressRequest
    evidence: JsonObject


type FreshnessEnvelope = Annotated[
    FreshnessReadEnvelope | FreshnessReserveEnvelope | FreshnessFinishEnvelope,
    Field(discriminator="method"),
]
_ENVELOPE = TypeAdapter[FreshnessEnvelope](FreshnessEnvelope)


def authenticated_freshness_envelope(
    raw_request: bytes,
    config: CompanyCliConfigV1,
    now: datetime,
) -> FreshnessEnvelope:
    envelope = _ENVELOPE.validate_python(strict_loads(raw_request, 1_048_576), strict=True)
    _ = canonical_workspace_id(config.workspace_id)
    expected_scope = FreshnessScope(
        provider_instance_id=config.provider_instance_id,
        workspace_id=config.workspace_id,
    )
    if envelope.request.scope != expected_scope or envelope.authority.operation != envelope.method:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    context = CompanyAuthorityContext(
        config.provider_instance_id,
        config.workspace_id,
        "principal:jarvis-company-progress",
        config.agent_id,
        config.session_id,
        tuple(config.projects),
        config.policy_revision,
        config.deletion_sequence,
        config.deletion_set_root,
    )
    arguments: JsonObject = {
        "request": model_object(envelope.request),
        "evidence": envelope.evidence,
    }
    _ = verify_company_authority(
        model_object(envelope.authority),
        arguments,
        company_trusted_keys(config.trusted_keys),
        context,
        now,
        key_scopes=config.key_scopes,
    )
    return envelope
