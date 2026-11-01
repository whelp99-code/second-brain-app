"""Synthetic old-writer publication fixtures; never rewrite a published journal."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

import sb.company_db_freshness as freshness
from sb.company_db_freshness_hash import operation_id_for
from sb.company_db_freshness_models import GenesisInventory
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_genesis import owned_genesis_receipts
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import (
    FinishProgressRequest,
    FreshnessScope,
    ReserveProgressRequest,
)
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import company_request_digest
from sb.company_memory_cli_config import load_company_config
from sb.company_memory_handoff import enroll_policy
from sb.company_processor_finish import PendingFinish, save_pending_finish
from sb.effect_values import format_instant
from tests.company_db_freshness_support import (
    SimulatedNvAnchor,
    provider_for,
    write_registry,
    write_tree,
)
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
)
from tests.test_company_candidate_handoff import CONTEXT, setup_config

BINDING = "sha256:" + "11" * 32
SCOPE = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
CANDIDATE = "legacy:original"


def writer_format(monkeypatch, mode, kind):
    digest = freshness.record_digest

    def emit(**kwargs):
        record = kwargs["record"]
        key = (
            "default_transition_receipts"
            if kwargs["phase"] == "bootstrap"
            else "default_transition_authority"
        )
        if kwargs["phase"] in {"bootstrap", "finish"} and (
            mode == "missing" or kwargs["phase"] == kind
        ):
            if mode == "missing":
                record.pop(key, None)
            elif mode == "empty":
                record[key] = [] if kwargs["phase"] == "bootstrap" else False
            elif mode == "mismatch":
                record[key] = (
                    ["not:an:anchored:receipt"] if kwargs["phase"] == "bootstrap" else "true"
                )
        return digest(**kwargs)

    # Change the synthetic writer BEFORE its first digest/witness/NV publication.
    monkeypatch.setattr(freshness, "record_digest", emit)


def transition(database, operation, candidate=CANDIDATE):
    with closing(CompanyMemoryStore(database)) as store:
        return store.execute(
            workspace_id=WORKSPACE,
            request_digest=company_request_digest(operation, {"candidate_id": candidate}),
            operation=operation,
            arguments={"candidate_id": candidate},
            current=ACCESS,
            deletion=DELETION,
            now=NOW,
        )


def runtime(tmp_path, kind, operation, monkeypatch, mode="missing"):
    writer_format(monkeypatch, mode, kind)
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    if kind == "bootstrap":
        database, registry, witness, lock = write_tree(tmp_path)
        with closing(CompanyMemoryStore(database)):
            pass
        apply_component_migration(database, "freshness")
        receive(database, CANDIDATE, "legacy:event", contact_body())
        receipt = transition(database, operation)
        with closing(sqlite3.connect(database)) as db:
            receipts, terminals = owned_genesis_receipts(db, SCOPE)
        inventory = GenesisInventory(
            second_brain_receipts=receipts, second_brain_terminals=terminals
        )
        checkpoint = freshness.preview_genesis_checkpoint(
            SCOPE,
            approval_policy_version=1,
            approval_binding_digest=BINDING,
            inventory=inventory,
        )
        write_registry(
            registry,
            registry_id="company-freshness:linux:v1",
            installation_id="install-1",
            anchor=anchor,
            scope=SCOPE,
            genesis=checkpoint,
        )
        freshness.bootstrap_company_scope(
            database=database,
            registry_path=registry,
            witness_dir=witness,
            lock_path=lock,
            anchor=anchor,
            registry_id="company-freshness:linux:v1",
            scope=SCOPE,
            approval_policy_version=1,
            approval_binding_digest=BINDING,
            inventory=inventory,
            now=format_instant(NOW),
        )
        provider = freshness.CompanyDbFreshnessProvider(
            database=database,
            actor_store="second_brain",
            registry_path=registry,
            witness_dir=witness,
            lock_path=lock,
            anchor=anchor,
            registry_id="company-freshness:linux:v1",
        )
    else:
        provider = provider_for(tmp_path, scope=SCOPE, binding=BINDING, anchor=anchor)
        receive(provider.database, CANDIDATE, "legacy:event", contact_body())
        with closing(sqlite3.connect(provider.database)) as db:
            raw = db.execute("SELECT checkpoint_json FROM company_freshness_scopes").fetchone()[0]
        from sb.company_freshness_models import Checkpoint

        head = Checkpoint.model_validate_json(raw, strict=True)
        event = company_request_digest(operation, {"candidate_id": CANDIDATE})
        operation_id = operation_id_for(
            SCOPE, request_id="legacy:request", command_digest=BINDING, operation=operation
        )
        reservation = provider.reserve_progress(
            ReserveProgressRequest(
                schema_version=2,
                scope=SCOPE,
                operation=operation,
                operation_id=operation_id,
                event_digest=event,
                expected_checkpoint=head,
                challenge="legacy:reserve",
            )
        )
        assert reservation.outcome == "reserved"
        receipt = transition(provider.database, operation)
        with closing(sqlite3.connect(provider.database)) as db, db:
            save_pending_finish(
                db,
                WORKSPACE,
                event,
                PendingFinish(
                    operation=operation,
                    operation_id=operation_id,
                    reservation=reservation,
                ),
            )
        finished = provider.finish_progress(
            FinishProgressRequest(
                schema_version=2,
                scope=SCOPE,
                operation_id=operation_id,
                reservation_id=reservation.reservation_id,
                expected_checkpoint=reservation.checkpoint,
                evidence_digest=receipt.receipt_digest,
                terminal_state="accepted" if operation == "accept" else "rejected",
                challenge="legacy:finish",
            )
        )
        assert finished.outcome == "recorded"
    with closing(sqlite3.connect(provider.database)) as db:
        records = db.execute("SELECT phase,record_json FROM company_freshness_log").fetchall()
    if mode == "missing":
        assert all("default_transition_" not in raw for _, raw in records)
    return provider, receipt


def snapshot(provider):
    return (
        provider.database.read_bytes(),
        provider.anchor.read_value(),
        (provider.witness_dir / "frames.jsonl").read_bytes(),
    )


def audit(provider):
    before = snapshot(provider)
    with provider.read_only_report(SCOPE) as db:
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (1,)
    assert snapshot(provider) == before


def enroll(tmp_path, provider):
    root = tmp_path / "enrollment"
    root.mkdir()
    config = load_company_config(setup_config(root))
    with closing(sqlite3.connect(provider.database)) as db, db:
        enroll_policy(
            db,
            replace(CONTEXT, provider=PROVIDER, workspace_id=WORKSPACE),
            config.handoff_policy,
            {},
            NOW,
        )


@pytest.mark.parametrize("kind", ["bootstrap", "finish"])
@pytest.mark.parametrize("operation", ["accept", "reject"])
def test_missing_fields_old_anchor_survives_exact_false_audit_and_enrollment(
    tmp_path, monkeypatch, kind, operation
):
    provider, _ = runtime(tmp_path, kind, operation, monkeypatch)
    # read_only_report -> _audit_snapshot -> verify_owned_genesis(exact=False).
    audit(provider)
    history = (provider.anchor.read_value(), (provider.witness_dir / "frames.jsonl").read_bytes())
    enroll(tmp_path, provider)
    audit(provider)
    assert history == (
        provider.anchor.read_value(),
        (provider.witness_dir / "frames.jsonl").read_bytes(),
    )


@pytest.mark.parametrize("kind", ["bootstrap", "finish"])
@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize("mode", ["empty", "mismatch"])
def test_explicit_authority_is_never_replaced_by_missing_field_rule(
    tmp_path, monkeypatch, kind, operation, mode
):
    provider, _ = runtime(tmp_path, kind, operation, monkeypatch, mode)
    before = snapshot(provider)
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(SCOPE):
        pass
    assert snapshot(provider) == before
    enroll(tmp_path, provider)
    before = snapshot(provider)
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(SCOPE):
        pass
    assert snapshot(provider) == before


@pytest.mark.parametrize("kind", ["bootstrap", "finish"])
@pytest.mark.parametrize("damage", ["extra_receipt", "changed_request", "changed_receipt"])
def test_missing_fields_never_authorize_unanchored_or_forged_receipts(
    tmp_path, monkeypatch, kind, damage
):
    provider, receipt = runtime(tmp_path, kind, "accept", monkeypatch)
    if damage == "extra_receipt":
        receive(
            provider.database,
            "legacy:injected",
            "legacy:injected:event",
            contact_body("Grace", "grace@mail.internal"),
        )
        transition(provider.database, "accept", "legacy:injected")
    else:
        with closing(sqlite3.connect(provider.database)) as db, db:
            column = "request_digest" if damage == "changed_request" else "receipt_digest"
            db.execute(
                f"UPDATE company_memory_receipts SET {column}=? WHERE receipt_id=?",
                ("sha256:" + "ff" * 32, receipt.receipt_id),
            )
    enroll(tmp_path, provider)
    before = snapshot(provider)
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(SCOPE):
        pass
    assert snapshot(provider) == before


@pytest.mark.parametrize("operation", ["accept", "reject"])
def test_old_missing_flags_never_bypass_signed_human_decisions(tmp_path, monkeypatch, operation):
    from tests.test_company_round12_integrity import test_human_decision_damage_is_not_ready

    writer_format(monkeypatch, "missing", "finish")
    test_human_decision_damage_is_not_ready(tmp_path, operation, "signature")
