from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier, Event

import pytest

from sb.company_auto_engine import (
    _entity_key,
    _loaded_candidate,
    _record_conflict,
    run_auto_internal,
)
from sb.company_auto_settings import AutoInternalRejected, SourceContext
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_internal_classifier import classify_mail_candidate
from sb.company_internal_effects import insert_effect, verify_internal_readback
from sb.effect_values import format_instant
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import SimulatedNvAnchor, empty_genesis, provider_for
from tests.company_internal_auto_support import (
    DELETION,
    NOW,
    WORKSPACE,
    contact_body,
    receive,
    trigger,
)
from tests.test_company_round8_integrity import request, rotate


@pytest.mark.parametrize("same_event", [False, True])
def test_two_candidate_preflights_cannot_share_a_winning_record(tmp_path: Path, same_event: bool):
    provider, _, context = real_company_runtime(tmp_path)
    scope = request(provider, None).scope
    for index in range(2):
        receive(
            provider.database,
            f"round9:mail:{index}",
            "round9:event" if same_event else f"round9:event:{index}",
            contact_body(),
        )
    barrier = Barrier(2)
    committed = Event()

    def worker(index):
        loaded = _loaded_candidate(provider.database, context, f"round9:mail:{index}")
        assert loaded is not None
        candidate, _ = loaded
        classified = classify_mail_candidate(candidate)
        assert classified.record_kind == "contact"
        fields = classified.fields
        # Both workers really pass the read-only preflight before either writes.
        assert not _record_conflict(provider.database, scope, candidate, "contact", fields)
        barrier.wait(timeout=10)
        if index == 1:
            assert committed.wait(timeout=10)
        kwargs = {
            "operation_id": f"round9:operation:{index}",
            "auto_request_id": f"round9:request:{index}",
            "candidate_id": candidate.candidate_id,
            "record_kind": "contact",
            "entity_key": _entity_key("contact", fields),
            "payload": fields,
            "source_event_id": candidate.source_event_id,
            "content_digest": candidate.content_digest,
            "deletion": DELETION,
            "created_at": format_instant(NOW),
            "forbidden_digests": (),
            "source_context": SourceContext(
                workspace_id=WORKSPACE,
                owner=context.owner,
                projects=list(context.projects),
                policy_revision=context.policy_revision,
                deletion_sequence=DELETION[0],
                deletion_set_root=DELETION[1],
            ),
        }
        try:
            with closing(sqlite3.connect(provider.database)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                digest = insert_effect(db, scope, **kwargs)
            if index == 0:
                # Same-candidate replay keeps the original effect and record.
                with closing(sqlite3.connect(provider.database)) as db, db:
                    assert insert_effect(db, scope, **kwargs) == digest
                assert verify_internal_readback(
                    provider.database, scope, kwargs["operation_id"], digest
                )
            return "committed"
        except AutoInternalRejected as exc:
            assert exc.code == "INTERNAL_RECORD_CONFLICT"
            return "rejected"
        finally:
            if index == 0:
                committed.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(worker, 0)
        second = workers.submit(worker, 1)
        assert first.result(timeout=20) == "committed"
        assert second.result(timeout=20) == "rejected"
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT candidate_id FROM company_internal_effects").fetchall() == [
            ("round9:mail:0",)
        ]
        assert db.execute(
            "SELECT source_candidate_id FROM company_internal_records"
        ).fetchall() == [("round9:mail:0",)]


def damage_cache(database, damage):
    with closing(sqlite3.connect(database)) as db, db:
        triggers = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('company_freshness_epochs_no_update','company_freshness_epochs_no_delete')"
        ).fetchall()
        db.execute("DROP TRIGGER company_freshness_epochs_no_update")
        db.execute("DROP TRIGGER company_freshness_epochs_no_delete")
        if damage == "missing_epoch":
            db.execute("DELETE FROM company_freshness_epochs")
        elif damage == "extra_epoch":
            db.execute(
                "INSERT INTO company_freshness_epochs SELECT provider_instance_id,workspace_id,"
                "epoch+1,previous_epoch,previous_checkpoint_digest,genesis_json,"
                "registry_binding_digest,created_at FROM company_freshness_epochs"
            )
        elif damage == "extra_scope_epoch":
            db.execute(
                "INSERT INTO company_freshness_epochs SELECT provider_instance_id,'extra',"
                "epoch,previous_epoch,previous_checkpoint_digest,genesis_json,"
                "registry_binding_digest,created_at FROM company_freshness_epochs"
            )
        elif damage.startswith("epoch_"):
            field = damage.removeprefix("epoch_")
            value = {
                "previous_epoch": 1,
                "previous_checkpoint_digest": "sha256:" + "ee" * 32,
                "genesis_json": "{}",
                "registry_binding_digest": "sha256:" + "ee" * 32,
                "created_at": "2026-10-16T09:00:00.000Z",
            }[field]
            db.execute(f"UPDATE company_freshness_epochs SET {field}=?", (value,))
        elif damage == "missing_scope":
            db.execute("DELETE FROM company_freshness_scopes")
        elif damage == "scope_epoch":
            db.execute("UPDATE company_freshness_scopes SET epoch=2")
        elif damage == "scope_sequence":
            db.execute("UPDATE company_freshness_scopes SET last_global_sequence=1")
        elif damage == "scope_initialized_at":
            db.execute("UPDATE company_freshness_scopes SET initialized_at='forged'")
        else:
            raise AssertionError(damage)
        for (sql,) in triggers:
            db.execute(sql)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_epoch",
        "extra_epoch",
        "extra_scope_epoch",
        "epoch_previous_epoch",
        "epoch_previous_checkpoint_digest",
        "epoch_genesis_json",
        "epoch_registry_binding_digest",
        "epoch_created_at",
        "missing_scope",
        "scope_epoch",
        "scope_sequence",
        "scope_initialized_at",
    ],
)
def test_epoch_and_scope_cache_damage_fails_before_publication(tmp_path: Path, damage: str):
    provider, _, context = real_company_runtime(tmp_path)
    damage_cache(provider.database, damage)
    witness = provider.witness_dir / "frames.jsonl"
    before = witness.read_bytes(), provider.anchor.read_value()
    with closing(sqlite3.connect(provider.database)) as db:
        journal = db.execute("SELECT * FROM company_freshness_log").fetchall()
    response = provider.read_freshness(request(provider, context.observed_checkpoint))
    assert response.status != "ready" and response.checkpoint is None
    rotate(provider)
    with pytest.raises(AnchorRejected):
        provider.install_auto_policy_pin(request(provider, None).scope)
    assert (witness.read_bytes(), provider.anchor.read_value()) == before
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT * FROM company_freshness_log").fetchall() == journal


@pytest.mark.parametrize("boundary", ["append_witness_frame", "save_checkpoint"])
def test_intact_epoch_inventory_allows_pending_publication_resume(
    tmp_path: Path, monkeypatch, boundary
):
    provider, settings, context = real_company_runtime(tmp_path)
    rotate(provider)

    def fail(*args):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

    with monkeypatch.context() as fault:
        fault.setattr("sb.company_db_freshness." + boundary, fail)
        with pytest.raises(AnchorRejected):
            provider.install_auto_policy_pin(request(provider, None).scope)
    recovered = provider.install_auto_policy_pin(request(provider, None).scope)
    assert provider.read_freshness(request(provider, recovered)).status == "ready"
    receive(provider.database, "round9:normal", "round9:normal-event", contact_body())
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].classification == "auto_internal"
    assert provider.read_freshness(request(provider, result.checkpoint)).status == "ready"


@pytest.mark.parametrize("boundary", ["append_witness_frame", "_upsert_scope"])
def test_unpublished_bootstrap_epoch_is_not_an_extra_row(tmp_path: Path, monkeypatch, boundary):
    scope = FreshnessScope(provider_instance_id="round9:provider", workspace_id="round9:workspace")
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    binding = "sha256:" + "11" * 32

    def fail(*args):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

    with monkeypatch.context() as fault:
        fault.setattr("sb.company_db_freshness." + boundary, fail)
        with pytest.raises(AnchorRejected):
            provider_for(tmp_path, scope=scope, binding=binding, anchor=anchor)
    provider = CompanyDbFreshnessProvider(
        database=tmp_path / "company.db",
        actor_store="second_brain",
        registry_path=tmp_path / "freshness-registry.json",
        witness_dir=tmp_path / "witness",
        lock_path=tmp_path / "registry.lock",
        anchor=anchor,
        registry_id="company-freshness:linux:v1",
    )
    expected = empty_genesis(scope, binding)
    read = ReadFreshnessRequest(
        schema_version=2,
        scope=scope,
        installation_id="install-1",
        challenge="round9:bootstrap-resume",
        observed_checkpoint=expected,
    )
    assert provider.read_freshness(read).status == "ready"
    nv = anchor.read_value()
    assert provider.read_freshness(read).status == "ready"
    assert anchor.read_value() == nv
