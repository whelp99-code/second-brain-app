"""One authenticated, bounded freshness invocation on the installed company DB."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sb.company_db_freshness import CompanyDbFreshnessProvider, JarvisSidecarEvidence
from sb.company_freshness import provider_from_config
from sb.company_freshness_anchor import require_trusted_file
from sb.company_freshness_transport import (
    FreshnessReadEnvelope,
    FreshnessReserveEnvelope,
    authenticated_freshness_envelope,
)
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.company_memory_cli_config import company_database_path, load_company_config
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_values import model_object


def run_freshness(
    config_path: Path,
    raw_request: bytes,
    now: datetime,
    *,
    provider: CompanyDbFreshnessProvider | None = None,
) -> JsonObject:
    require_trusted_file(config_path, mode=0o600)
    config = load_company_config(config_path)
    envelope = authenticated_freshness_envelope(raw_request, config, now)
    selected = (
        provider
        if provider is not None
        else provider_from_config(
            config.freshness_provider,
            company_database=company_database_path(config),
            actor_store="jarvis",
        )
    )
    if isinstance(envelope, FreshnessReadEnvelope):
        return model_object(selected.read_freshness(envelope.request))
    if isinstance(envelope, FreshnessReserveEnvelope):
        return model_object(selected.reserve_progress(envelope.request))
    if not isinstance(selected, CompanyDbFreshnessProvider):
        return model_object(selected.finish_progress(envelope.request))
    if selected.actor_store != "jarvis" or config.handoff_policy is None:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    sidecar = JarvisSidecarEvidence.model_validate_json(
        canonical_bytes(envelope.evidence),
        strict=True,
    )
    context = CompanyAuthorityContext(
        config.provider_instance_id,
        config.workspace_id,
        config.principal_id,
        config.agent_id,
        config.session_id,
        tuple(config.projects),
        config.policy_revision,
        config.deletion_sequence,
        config.deletion_set_root,
    )
    return model_object(
        selected.finish_with_jarvis_sidecar(
            envelope.request,
            sidecar,
            context=context,
            policy=config.handoff_policy,
        )
    )
