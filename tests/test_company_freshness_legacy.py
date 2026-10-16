from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_db_freshness import (
    CompanyDbFreshnessProvider,
    GenesisInventory,
    bootstrap_company_scope,
    preview_genesis_checkpoint,
)
from sb.company_freshness_genesis import owned_genesis_receipts
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import company_request_digest
from sb.effect_values import format_instant
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import SimulatedNvAnchor, write_registry, write_tree
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    trigger,
)


def legacy_candidate(database: Path) -> None:
    receive(database, "legacy:1", "event:legacy:1", contact_body())


def test_migrated_company_store_refuses_unprotected_legacy_writer(tmp_path: Path) -> None:
    database = tmp_path / "company.db"
    legacy_candidate(database)
    _ = apply_component_migration(database, "freshness")
    with closing(CompanyMemoryStore(database)) as store:
        with pytest.raises(CompanyMemoryError, match="COMPANY_OWNER_APPROVAL_REQUIRED"):
            _ = store.accept(WORKSPACE, "legacy:1", ACCESS, DELETION, now=NOW)
        with pytest.raises(CompanyMemoryError, match="COMPANY_OWNER_APPROVAL_REQUIRED"):
            _ = store.execute(
                workspace_id=WORKSPACE,
                request_digest=company_request_digest("accept", {"candidate_id": "legacy:1"}),
                operation="accept",
                arguments={"candidate_id": "legacy:1"},
                current=ACCESS,
                deletion=DELETION,
                now=NOW,
            )


def test_auto_cannot_take_over_accepted_candidate_without_original_auto_receipt(
    tmp_path: Path,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    legacy_candidate(provider.database)
    with closing(sqlite3.connect(provider.database)) as db, db:
        _ = db.execute(
            "UPDATE company_memory_candidates SET state='accepted',accepted_at=?",
            (format_instant(NOW),),
        )
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].classification == "skipped_human"
    with closing(sqlite3.connect(provider.database)) as db:
        rows: list[tuple[int, int]] = db.execute(
            """SELECT (SELECT count(*) FROM company_internal_effects),
            (SELECT count(*) FROM company_auto_policy_receipts)""",
        ).fetchall()
    assert rows == [(0, 0)]


def test_bootstrap_verifies_and_retains_original_sb_inventory(tmp_path: Path) -> None:
    database, registry, witness, lock = write_tree(tmp_path)
    legacy_candidate(database)
    with closing(CompanyMemoryStore(database)) as store:
        _ = store.execute(
            workspace_id=WORKSPACE,
            request_digest=company_request_digest("accept", {"candidate_id": "legacy:1"}),
            operation="accept",
            arguments={"candidate_id": "legacy:1"},
            current=ACCESS,
            deletion=DELETION,
            now=NOW,
        )
    _ = apply_component_migration(database, "freshness")
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    binding = "sha256:" + "11" * 32
    empty = GenesisInventory()
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install:legacy",
        anchor=anchor,
        scope=scope,
        genesis=preview_genesis_checkpoint(
            scope,
            approval_policy_version=1,
            approval_binding_digest=binding,
            inventory=empty,
        ),
    )
    with pytest.raises(ValueError, match="COMPANY_RECEIPT_EVIDENCE_ABSENT"):
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
            inventory=empty,
            now=format_instant(NOW),
        )
    assert anchor.extend_count == 0
    with closing(sqlite3.connect(database)) as db:
        receipts, terminals = owned_genesis_receipts(db, scope)
    inventory = GenesisInventory(second_brain_receipts=receipts, second_brain_terminals=terminals)
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install:legacy",
        anchor=anchor,
        scope=scope,
        genesis=preview_genesis_checkpoint(
            scope,
            approval_policy_version=1,
            approval_binding_digest=binding,
            inventory=inventory,
        ),
    )
    checkpoint = bootstrap_company_scope(
        database=database,
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
        scope=scope,
        approval_policy_version=1,
        approval_binding_digest=binding,
        inventory=inventory,
        now=format_instant(NOW),
    )
    assert checkpoint.stores.second_brain.receipt_sequence == 1
    with closing(sqlite3.connect(database)) as db, db:
        _ = db.execute("DELETE FROM company_memory_receipts WHERE operation='accept'")
    provider = CompanyDbFreshnessProvider(
        database=database,
        actor_store="second_brain",
        registry_path=registry,
        witness_dir=witness,
        lock_path=lock,
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
    )
    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id="install:legacy",
            challenge="legacy:lost:receipt",
            observed_checkpoint=checkpoint,
        )
    )
    assert response.status != "ready"
    assert response.checkpoint is None
