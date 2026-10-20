from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest

import sb.company_auto_engine as auto_engine
from sb.company_auto_engine import _candidate_ids, run_auto_internal
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


@pytest.mark.parametrize("enrolled", [False, True])
def test_migrated_company_store_gates_only_enrolled_legacy_writer(
    tmp_path: Path, enrolled: bool
) -> None:
    database = tmp_path / "company.db"
    legacy_candidate(database)
    _ = apply_component_migration(database, "freshness")
    with closing(CompanyMemoryStore(database)) as store:
        assert store.db.execute("SELECT * FROM company_handoff_enrollment").fetchall() == []
        if enrolled:
            # Enrollment, not installing the freshness schema, protects legacy writes.
            store.db.execute(
                "INSERT INTO company_handoff_enrollment VALUES(?,?)", (WORKSPACE, "{}")
            )
            store.db.commit()
            before = store.db.execute("SELECT * FROM company_memory_candidates").fetchall()
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
            assert store.db.execute("SELECT * FROM company_memory_candidates").fetchall() == before
            assert store.db.execute("SELECT * FROM company_memory_receipts").fetchall() == []
        else:
            assert (
                store.accept(WORKSPACE, "legacy:1", ACCESS, DELETION, now=NOW).state == "accepted"
            )
            receipt = store.execute(
                workspace_id=WORKSPACE,
                request_digest=company_request_digest("accept", {"candidate_id": "legacy:1"}),
                operation="accept",
                arguments={"candidate_id": "legacy:1"},
                current=ACCESS,
                deletion=DELETION,
                now=NOW,
            )
            assert receipt.result["state"] == "accepted"
            assert store.db.execute(
                "SELECT operation,candidate_id FROM company_memory_receipts"
            ).fetchall() == [("accept", "legacy:1")]


def test_auto_cannot_take_over_accepted_candidate_without_original_auto_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    legacy_candidate(provider.database)
    with closing(sqlite3.connect(provider.database)) as db, db:
        _ = db.execute(
            "UPDATE company_memory_candidates SET state='accepted',accepted_at=?",
            (format_instant(NOW),),
        )
        before = db.execute("SELECT * FROM company_memory_candidates").fetchall()
    reserve = Mock(wraps=provider.reserve_progress)
    finish = Mock(wraps=provider.finish_progress)
    claim = Mock(wraps=auto_engine.claim_auto)
    monkeypatch.setattr(provider, "reserve_progress", reserve)
    monkeypatch.setattr(provider, "finish_progress", finish)
    monkeypatch.setattr(auto_engine, "claim_auto", claim)
    # Human-owned accepted rows are excluded before LIMIT, not assessed as skipped.
    assert _candidate_ids(provider.database, context, settings) == ()
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes == ()
    assert result.checkpoint == context.observed_checkpoint
    reserve.assert_not_called()
    finish.assert_not_called()
    claim.assert_not_called()
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_memory_candidates").fetchall() == before
        for table in (
            "company_internal_effects",
            "company_internal_records",
            "company_auto_policy_receipts",
            "company_memory_receipts",
            "company_candidate_execution_claims",
            "company_auto_assessments",
            "company_freshness_operations",
            "company_internal_pending_reserve",
            "company_internal_pending_finish",
        ):
            assert db.execute(f"SELECT * FROM {table}").fetchall() == [], table


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
