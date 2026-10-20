"""Explicit local operator routes, never exposed by the signed broker envelope."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

from sb.company_approver_binding import binding_digest
from sb.company_auto_cli import auto_settings
from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    GenesisInventory,
    bootstrap_company_scope,
)
from sb.company_freshness import FreshnessScope, provider_from_config
from sb.company_freshness_anchor import require_trusted_file
from sb.company_freshness_migrations import apply_component_migration
from sb.company_internal_effects import install_auto_policy
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.company_memory_cli_config import company_database_path, load_company_config
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import JsonObject, format_instant
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

BOOTSTRAP_MANIFEST = Path("/etc/second-brain-company/bootstrap-manifest.json")


class BootstrapManifest(ClosedModel):
    schema_version: Literal[1]
    scope: FreshnessScope
    inventory: GenesisInventory
    all_company_writers_upgraded: Literal[True]
    source_inventories_verified: Literal[True]


def run_operator(
    action: str,
    config_path: Path,
    raw_request: bytes,
    now: datetime,
) -> JsonObject:
    if os.geteuid() != 0 or raw_request.strip():
        raise CompanyAuthorityRejected("COMPANY_OPERATOR_REQUIRED")
    require_trusted_file(config_path, mode=0o600)
    if config_path.stat().st_uid != 0:
        raise CompanyAuthorityRejected("COMPANY_OPERATOR_REQUIRED")
    config = load_company_config(config_path)
    database = company_database_path(config)
    if action == "freshness-migrate":
        freshness = apply_component_migration(database, "freshness", now=format_instant(now))
        internal = apply_component_migration(database, "internal_auto", now=format_instant(now))
        return {"freshness_checksum": freshness, "internal_auto_checksum": internal}
    selected = provider_from_config(
        config.freshness_provider,
        company_database=database,
        actor_store="second_brain",
    )
    if not isinstance(selected, CompanyDbFreshnessProvider):
        raise CompanyAuthorityRejected("COMPANY_FRESHNESS_REQUIRED")
    scope = FreshnessScope(
        provider_instance_id=config.provider_instance_id,
        workspace_id=config.workspace_id,
    )
    if action == "freshness-revoke":
        return {"checkpoint": model_object(selected.record_approval_revocations(scope))}
    if action == "auto-policy-install":
        settings = auto_settings(config, selected)
        before = local_checkpoint(database, config.workspace_id, None)
        if before is None:
            raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
        with closing(sqlite3.connect(database)) as db, db:
            digest = install_auto_policy(db, settings, config.workspace_id, now)
        after = selected.install_auto_policy_pin(scope)
        return {"policy_digest": digest, "checkpoint": model_object(after)}
    if action != "freshness-bootstrap" or config.handoff_policy is None:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    require_trusted_file(BOOTSTRAP_MANIFEST, mode=0o644)
    if BOOTSTRAP_MANIFEST.stat().st_uid != 0:
        raise CompanyAuthorityRejected("COMPANY_OPERATOR_REQUIRED")
    manifest = BootstrapManifest.model_validate_json(BOOTSTRAP_MANIFEST.read_bytes(), strict=True)
    if manifest.scope != scope:
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
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
    checkpoint = bootstrap_company_scope(
        database=database,
        registry_path=selected.registry_path,
        witness_dir=selected.witness_dir,
        lock_path=selected.lock_path,
        anchor=selected.anchor,
        registry_id=selected.registry_id,
        scope=scope,
        approval_policy_version=config.handoff_policy.approval_policy_version,
        approval_binding_digest=binding_digest(context, config.handoff_policy),
        inventory=manifest.inventory,
        now=format_instant(now),
    )
    return {"checkpoint": model_object(checkpoint)}
