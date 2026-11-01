from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    FreshnessRegistry,
    GenesisInventory,
    RegistryScopePin,
    RegistryTpmPin,
    preview_genesis_checkpoint,
)
from sb.company_freshness import Checkpoint, FreshnessScope
from sb.company_freshness_anchor import NvAnchor

SIMULATED_ANCHOR_LABEL = "simulated anchor; not TPM readiness"


class SimulatedNvAnchor:
    label: str = SIMULATED_ANCHOR_LABEL

    def __init__(self, name: bytes, value: bytes) -> None:
        if len(value) != 32:
            raise ValueError("value")
        self._name: bytes = name
        self._value: bytes = value
        self.extend_count: int = 0

    def identity(self) -> str:
        return "sim-1"

    def public_name(self) -> bytes:
        return self._name

    def read_value(self) -> bytes:
        return self._value

    def extend(self, record_digest_raw: bytes) -> bytes:
        import hashlib

        self.extend_count += 1
        self._value = hashlib.sha256(self._value + record_digest_raw).digest()
        return self._value


def write_tree(root: Path) -> tuple[Path, Path, Path, Path]:
    database = root / "company.db"
    witness = root / "witness"
    witness.mkdir(mode=0o700)
    registry = root / "freshness-registry.json"
    lock = root / "registry.lock"
    lock.touch(mode=0o600)
    return database, registry, witness, lock


def write_registry(
    path: Path,
    *,
    registry_id: str,
    installation_id: str,
    anchor: NvAnchor,
    scope: FreshnessScope,
    genesis: Checkpoint,
) -> None:
    registry = FreshnessRegistry(
        schema_version=1,
        registry_id=registry_id,
        installation_id=installation_id,
        tpm=RegistryTpmPin(
            identity=anchor.identity(),
            public_name_hex=anchor.public_name().hex(),
            nv_handle="0x01804F43",
            name_alg="sha256",
            initial_value_hex=anchor.read_value().hex(),
        ),
        scopes=[
            RegistryScopePin(
                provider_instance_id=scope.provider_instance_id,
                workspace_id=scope.workspace_id,
                epoch=1,
                genesis_digest=genesis.intent_root,
            ),
        ],
    )
    _ = path.write_text(registry.model_dump_json(), encoding="utf-8")
    os.chmod(path, 0o644)


def empty_genesis(scope: FreshnessScope, binding: str) -> Checkpoint:
    return preview_genesis_checkpoint(
        scope,
        approval_policy_version=1,
        approval_binding_digest=binding,
        inventory=GenesisInventory(),
    )


def provider_for(
    root: Path,
    *,
    scope: FreshnessScope,
    binding: str,
    anchor: SimulatedNvAnchor,
    actor_store: Literal["jarvis", "second_brain"] = "second_brain",
) -> CompanyDbFreshnessProvider:
    database, registry, witness, lock = write_tree(root)
    genesis = empty_genesis(scope, binding)
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install-1",
        anchor=anchor,
        scope=scope,
        genesis=genesis,
    )
    from sb.company_freshness_migrations import apply_component_migration

    _ = apply_component_migration(database, "freshness", now="2026-10-16T00:00:00.000Z")
    from sb.company_db_freshness import bootstrap_company_scope

    _ = bootstrap_company_scope(
        database=database,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        scope=scope,
        approval_policy_version=1,
        approval_binding_digest=binding,
        inventory=GenesisInventory(),
        now="2026-10-16T00:00:00.000Z",
        caller_checkpoint=None,
    )
    return CompanyDbFreshnessProvider(
        database=database,
        actor_store=actor_store,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        clock=lambda: "2026-10-16T00:00:01.000Z",
    )
