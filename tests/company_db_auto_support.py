"""The actual DB provider and actual automatic engine share one company DB."""

from __future__ import annotations

import base64
import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_approver_binding import public_key_fingerprint
from sb.company_auto_policy import policy_digest
from sb.company_auto_settings import (
    AutoInternalContext,
    AutoInternalSettings,
    source_context_digest,
)
from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    GenesisInventory,
    bootstrap_company_scope,
)
from sb.company_db_freshness_models import FreshnessRegistry, RegistryAutoPolicyPin
from sb.company_freshness import FreshnessScope
from sb.company_freshness_migrations import apply_component_migration
from sb.company_internal_effects import install_auto_policy
from sb.company_memory import CompanyMemoryStore
from sb.effect_values import canonical_bytes
from sb.effect_write_values import model_object
from tests.company_db_freshness_support import (
    SimulatedNvAnchor,
    empty_genesis,
    write_registry,
    write_tree,
)
from tests.company_internal_auto_support import NOW, PROVIDER, WORKSPACE, context, settings


def real_company_runtime(
    root: Path,
) -> tuple[CompanyDbFreshnessProvider, AutoInternalSettings, AutoInternalContext]:
    database, registry, witness, lock = write_tree(root)
    with closing(CompanyMemoryStore(database)):
        pass
    _ = apply_component_migration(database, "freshness")
    _ = apply_component_migration(database, "internal_auto")
    bound = settings()
    with closing(sqlite3.connect(database)) as db, db:
        _ = install_auto_policy(db, bound, WORKSPACE, NOW)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    genesis = empty_genesis(scope, "sha256:" + "11" * 32)
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id=bound.installation_id,
        anchor=anchor,
        scope=scope,
        genesis=genesis,
    )
    registered = FreshnessRegistry.model_validate_json(registry.read_bytes())
    registered = registered.model_copy(
        update={
            "scopes": [
                registered.scopes[0].model_copy(
                    update={
                        "source_deletion_sequence": context(genesis).deletion_sequence,
                        "source_deletion_root": context(genesis).deletion_set_root,
                        "source_context_digest": source_context_digest(PROVIDER, context(genesis)),
                    }
                )
            ]
        }
    )
    _ = registry.write_bytes(canonical_bytes(model_object(registered)))
    _ = bootstrap_company_scope(
        database=database,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        scope=scope,
        approval_policy_version=1,
        approval_binding_digest="sha256:" + "11" * 32,
        inventory=GenesisInventory(),
        now="2026-10-16T08:00:00.000Z",
    )
    provider = CompanyDbFreshnessProvider(
        database=database,
        actor_store="second_brain",
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
    )
    registered = FreshnessRegistry.model_validate_json(registry.read_text())
    registered = registered.model_copy(
        update={
            "auto_policies": [
                RegistryAutoPolicyPin(
                    scope=scope,
                    revision=1,
                    policy_digest=policy_digest(bound.policy),
                    key_id=bound.signer.key_id,
                    public_key_fingerprint=public_key_fingerprint(bound.signer.public_key),
                    public_key=base64.urlsafe_b64encode(bound.signer.public_key.public_bytes_raw())
                    .rstrip(b"=")
                    .decode(),
                    revoked_policy_digests=[],
                    revoked_key_fingerprints=[],
                )
            ]
        }
    )
    _ = registry.write_bytes(canonical_bytes(model_object(registered)))
    active = provider.install_auto_policy_pin(scope)
    return provider, bound, context(active)
