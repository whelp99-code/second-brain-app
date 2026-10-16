"""Fixed authenticated trigger/report routes; no caller-selected credentials."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_approver_binding import decode_key
from sb.company_auto_engine import run_auto_internal
from sb.company_auto_report import AutoReportQuery, read_auto_report
from sb.company_auto_settings import (
    AutoInternalContext,
    AutoInternalSettings,
    AutoReportGrant,
    AutoTriggerGrant,
    bind_policy_signer,
)
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness import FreshnessScope, provider_from_config
from sb.company_freshness_anchor import require_trusted_file
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyMemoryAuthorityV1,
    verify_company_authority,
)
from sb.company_memory_cli_config import (
    CompanyCliConfigV1,
    company_database_path,
    company_trusted_keys,
    load_company_config,
)
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import JsonObject, JsonValue, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

POLICY_AUTO_KEY = Path("/run/sb-company-processor/credentials/policy-auto.key")
PROGRESS_PRINCIPAL = "principal:jarvis-company-progress"


class _Envelope(ClosedModel):
    authority: CompanyMemoryAuthorityV1
    arguments: JsonObject


def auto_settings(
    config: CompanyCliConfigV1, provider: CompanyDbFreshnessProvider
) -> AutoInternalSettings:
    if config.internal_auto_policy is None or config.policy_auto_key_id is None:
        raise CompanyAuthorityRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
    require_trusted_file(POLICY_AUTO_KEY, mode=0o600)
    raw = POLICY_AUTO_KEY.read_bytes()
    if len(raw) != 32:
        raise CompanyAuthorityRejected("COMPANY_CONFIG_INVALID")
    signer = bind_policy_signer(
        "principal:company-internal-automation",
        config.policy_auto_key_id,
        Ed25519PrivateKey.from_private_bytes(raw),
    )
    other_keys = list(company_trusted_keys(config.trusted_keys).values())
    other_ids = set(config.trusted_keys)
    if config.handoff_policy is not None:
        other_keys.extend(
            decode_key(encoded)
            for values in (
                config.handoff_policy.owner_approval_keys,
                config.handoff_policy.processor_keys,
            )
            for encoded in values.values()
        )
        other_ids.update(config.handoff_policy.owner_approval_keys)
        other_ids.update(config.handoff_policy.processor_keys)
    if signer.key_id in other_ids or any(
        key.public_bytes_raw() == signer.public_key.public_bytes_raw() for key in other_keys
    ):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_KEYS_NOT_SEPARATE")
    return AutoInternalSettings(
        config.provider_instance_id,
        provider.installation_id,
        config.internal_auto_policy,
        signer,
    )


def run_auto_route(
    action: str,
    config_path: Path,
    raw_request: bytes,
    now: datetime,
    *,
    provider: CompanyDbFreshnessProvider | None = None,
    clock: Callable[[], datetime] | None = None,
) -> JsonObject:
    require_trusted_file(config_path, mode=0o600)
    config = load_company_config(config_path)
    envelope = _Envelope.model_validate(strict_loads(raw_request, 1_048_576), strict=True)
    operation = "auto_process_internal" if action == "auto-internal" else "read_auto_report"
    if action not in {"auto-internal", "auto-report"} or envelope.authority.operation != operation:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    context = CompanyAuthorityContext(
        config.provider_instance_id,
        config.workspace_id,
        PROGRESS_PRINCIPAL,
        config.agent_id,
        config.session_id,
        tuple(config.projects),
        config.policy_revision,
        config.deletion_sequence,
        config.deletion_set_root,
    )
    _ = verify_company_authority(
        model_object(envelope.authority),
        envelope.arguments,
        company_trusted_keys(config.trusted_keys),
        context,
        now,
        key_scopes=config.key_scopes,
    )
    database = company_database_path(config)
    selected = (
        provider
        if provider is not None
        else provider_from_config(
            config.freshness_provider,
            company_database=database,
            actor_store="second_brain",
        )
    )
    if (
        not isinstance(selected, CompanyDbFreshnessProvider)
        or selected.actor_store != "second_brain"
    ):
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED")
    if action == "auto-report":
        query = AutoReportQuery.model_validate(envelope.arguments, strict=True)
        selected.verify_read_only_report(
            FreshnessScope(
                provider_instance_id=config.provider_instance_id,
                workspace_id=config.workspace_id,
            )
        )
        return model_object(
            read_auto_report(
                database,
                provider_instance_id=config.provider_instance_id,
                workspace_id=config.workspace_id,
                grant=AutoReportGrant(
                    schema_version=1,
                    operation="read_auto_report",
                    purpose="company_memory_auto_report",
                    principal_id=PROGRESS_PRINCIPAL,
                ),
                query=query,
            )
        )
    if envelope.arguments != {"limit": 100} or type(envelope.arguments["limit"]) is not int:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    checkpoint = local_checkpoint(database, config.workspace_id, None)
    if checkpoint is None:
        raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
    result = run_auto_internal(
        database,
        auto_settings(config, selected),
        AutoInternalContext(
            config.workspace_id,
            config.principal_id,
            tuple(config.projects),
            config.policy_revision,
            config.deletion_sequence,
            config.deletion_set_root,
            checkpoint,
            now,
            clock=clock if clock is not None else lambda: datetime.now(UTC),
        ),
        selected,
        AutoTriggerGrant(
            schema_version=1,
            operation="auto_process_internal",
            purpose="company_internal_auto_trigger",
            principal_id=PROGRESS_PRINCIPAL,
            limit=100,
            issued_at=envelope.authority.issued_at,
            expires_at=envelope.authority.expires_at,
        ),
    )
    outcomes: list[JsonValue] = [
        {
            "candidate_id": outcome.candidate_id,
            "classification": outcome.classification,
            "effect_count": outcome.effect_count,
            "receipt_ids": list(outcome.receipt_ids),
            "reason_codes": list(outcome.reason_codes),
            "uncertain": outcome.uncertain,
        }
        for outcome in result.outcomes
    ]
    return {"outcomes": outcomes, "checkpoint": model_object(result.checkpoint)}
