"""Synthetic T/U/V/W/X original issuance and durable cancellation regressions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import TypeAdapter

import sb.company_auto_engine as engine
from sb.company_auto_authorization import require_auto_transaction
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_effects import candidate_result
from sb.company_memory import MemoryCandidate
from sb.company_memory_cli import run
from sb.effect_values import canonical_bytes
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import DELETION, contact_body, receive, trigger
from tests.test_company_candidate_handoff import (
    PAGE,
    PROCESSOR,
    PROCESSOR_KEY,
    first_proposal,
    owner_receipt,
    processor_arguments,
    signed_request,
)
from tests.test_company_db_human_integration import human_runtime
from tests.test_company_memory_product import NOW
from tests.test_company_round12_integrity import readiness
from tests.test_company_round14_integrity import Crash, scope, snapshot


def issued_runtime(tmp_path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:mail", "round15:event", contact_body())

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert readiness(provider, scope()).status == "ready"
    return provider, settings, context


@pytest.mark.parametrize(
    "damage", ["receipt_and_intent", "receipt", "claim_request", "claim_digest"]
)
def test_t_orphan_auto_claim_is_not_ready(tmp_path, monkeypatch, damage):
    provider, _, _ = issued_runtime(tmp_path, monkeypatch)
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage in {"receipt_and_intent", "receipt"}:
            db.execute("DROP TRIGGER company_auto_policy_receipts_no_delete")
            db.execute("DELETE FROM company_auto_policy_receipts")
        if damage in {"receipt_and_intent", "intent"}:
            db.execute("DELETE FROM company_internal_pending_reserve")
        if damage.startswith("claim_"):
            db.execute("DROP TRIGGER company_candidate_claims_no_update")
            if damage == "claim_request":
                db.execute(
                    "UPDATE company_candidate_execution_claims SET workflow_request_id='orphan:workflow'"
                )
            else:
                db.execute(
                    "UPDATE company_candidate_execution_claims SET content_digest=?",
                    ("sha256:" + "ab" * 32,),
                )
    before = snapshot(provider)
    assert readiness(provider, scope()).status != "ready"
    assert snapshot(provider) == before
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(scope()):
        pass
    assert snapshot(provider) == before


def test_u_guarded_policy_failure_cancels_and_next_batch_advances(tmp_path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:blocked", "round15:blocked:event", contact_body())
    check = provider.require_auto_policy_under_guard

    def reject_reserved(*args, **kwargs):
        with closing(sqlite3.connect(provider.database)) as db:
            reserved = db.execute(
                "SELECT 1 FROM company_freshness_operations WHERE state='reserved'"
            ).fetchone()
        if reserved:
            raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
        return check(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(provider, "require_auto_policy_under_guard", reject_reserved)
        with pytest.raises(AnchorRejected, match="COMPANY_POLICY_REGISTRATION_REQUIRED"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "cancelled")]
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (0,)
    assert readiness(provider, scope()).status == "ready"
    receive(provider.database, "round15:next", "round15:next:event", contact_body())
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert [(item.candidate_id, item.effect_count) for item in result.outcomes] == [
        ("round15:next", 1)
    ]
    assert (
        engine.run_auto_internal(provider.database, settings, context, provider, trigger()).outcomes
        == ()
    )


@pytest.mark.parametrize("damage", ["audit", "enrollment", "context", "binding"])
def test_v_enrollment_and_audit_are_inseparable(tmp_path, damage):
    _, provider = human_runtime(tmp_path)
    with closing(sqlite3.connect(provider.database)) as db:
        enrolled = json.loads(
            db.execute("SELECT context_json FROM company_handoff_enrollment").fetchone()[0]
        )
    target = FreshnessScope(
        provider_instance_id=enrolled["provider"], workspace_id=enrolled["workspace"]
    )
    assert readiness(provider, target).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db, db:
        if damage == "audit":
            db.execute("DROP TRIGGER company_approver_audit_no_delete")
            db.execute("DELETE FROM company_approver_enrollment_audit")
        elif damage == "enrollment":
            db.execute("DROP TRIGGER company_handoff_enrollment_no_delete")
            db.execute("DELETE FROM company_handoff_enrollment")
        elif damage == "context":
            db.execute("DROP TRIGGER company_handoff_enrollment_no_update")
            db.execute("UPDATE company_handoff_enrollment SET context_json='{}'")
        else:
            db.execute("DROP TRIGGER company_approver_audit_no_update")
            db.execute(
                "UPDATE company_approver_enrollment_audit SET evidence_json=json_set(evidence_json,'$.approval_binding_digest',?)",
                ("sha256:" + "aa" * 32,),
            )
    before = snapshot(provider)
    assert readiness(provider, target).status != "ready"
    assert snapshot(provider) == before


@pytest.mark.parametrize(
    "seconds,allowed", [(-1, False), (0, True), (299, True), (300, False), (301, False)]
)
def test_w_accept_receipt_half_open_validity(tmp_path, monkeypatch, seconds, allowed):
    provider, settings, context = issued_runtime(tmp_path, monkeypatch)
    with closing(sqlite3.connect(provider.database)) as db:
        intent = engine.pending_auto_reserve(db, scope())
        candidate = TypeAdapter(MemoryCandidate).validate_json(
            canonical_bytes(
                candidate_result(db, context.workspace_id, intent.candidate_id, DELETION)
            ),
            strict=True,
        )
        args = (
            db,
            scope(),
            settings,
            replace(context, now=context.now + timedelta(seconds=seconds)),
            candidate,
            intent.auto_request_id,
            intent.command_digest,
            "accept",
        )
        if allowed:
            require_auto_transaction(*args)
        else:
            with pytest.raises(AutoInternalRejected, match="POLICY_RECEIPT_REJECTED"):
                require_auto_transaction(*args)


@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize(
    "damage", ["orphan", "unconsumed", "outbox", "transition", "request", "candidate"]
)
def test_x_every_handoff_decision_has_authenticated_command_and_transition(
    tmp_path, operation, damage
):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    approval = owner_receipt(proposal, "approve" if operation == "accept" else "reject")
    args = processor_arguments(proposal, approval)
    if damage in {"orphan", "unconsumed"}:
        from sb.company_memory_authority import company_request_digest

        with closing(sqlite3.connect(provider.database)) as db, db:
            db.execute(
                "INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)",
                (
                    proposal["command"]["target"]["workspace_id"],
                    proposal["command"]["target"]["candidate_id"],
                    approval["request_id"],
                    approval["receipt_id"],
                    company_request_digest(operation, args),
                    approval["decision"],
                    canonical_bytes(approval).decode(),
                ),
            )
            if damage == "orphan":
                db.execute("DELETE FROM company_handoff_outbox")
    else:
        run(
            cfg,
            signed_request(operation, args, PROCESSOR_KEY, "processor", PROCESSOR),
            now=NOW,
            process_only=True,
            freshness_provider=provider,
        )
        with closing(sqlite3.connect(provider.database)) as db, db:
            if damage == "outbox":
                db.execute("DELETE FROM company_handoff_outbox")
            elif damage == "transition":
                db.execute("DELETE FROM company_memory_receipts WHERE operation=?", (operation,))
            elif damage == "request":
                db.execute("UPDATE company_handoff_decisions SET request_id='orphan:request'")
            else:
                # Extra decision unrelated to any transition: reverse receipt walks miss it.
                row = db.execute("SELECT * FROM company_handoff_decisions").fetchone()
                db.execute(
                    "INSERT INTO company_handoff_decisions VALUES(?,?,?,?,?,?,?)",
                    (row[0], "orphan:candidate", "orphan:request", "orphan:receipt", *row[4:]),
                )
    target = FreshnessScope(
        provider_instance_id=proposal["command"]["target"]["provider_instance_id"],
        workspace_id=proposal["command"]["target"]["workspace_id"],
    )
    before = snapshot(provider)
    assert readiness(provider, target).status != "ready"
    assert snapshot(provider) == before
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(target):
        pass


@pytest.mark.parametrize("unsafe", ["receipt", "effect", "proof_failure"])
def test_u_uncertain_or_nonzero_effect_cannot_cancel(tmp_path, monkeypatch, unsafe):
    import sb.company_db_freshness as freshness
    from sb.company_internal_effects import insert_memory_receipt
    from sb.effect_values import format_instant

    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:unsafe", "round15:unsafe:event", contact_body())
    check = provider.require_auto_policy_under_guard

    def reject_reserved(*args, **kwargs):
        with closing(sqlite3.connect(provider.database)) as db, db:
            reserved = db.execute(
                "SELECT 1 FROM company_freshness_operations WHERE state='reserved'"
            ).fetchone()
            if not reserved:
                return check(*args, **kwargs)
            if unsafe == "receipt":
                insert_memory_receipt(
                    db,
                    workspace_id=context.workspace_id,
                    request_digest="other:request",
                    operation="accept",
                    candidate_id="round15:unsafe",
                    result={},
                    created_at=format_instant(context.now),
                )
            elif unsafe == "effect":
                db.execute(
                    "INSERT INTO company_internal_effects VALUES(?,?,?,?,?,?,?,?)",
                    (
                        settings.provider_instance_id,
                        context.workspace_id,
                        "other:operation",
                        "other:auto",
                        "round15:unsafe",
                        "sha256:" + "ab" * 32,
                        "{}",
                        format_instant(context.now),
                    ),
                )
        raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")

    def cannot_prove(*args, **kwargs):
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")

    with monkeypatch.context() as fault:
        fault.setattr(provider, "require_auto_policy_under_guard", reject_reserved)
        if unsafe == "proof_failure":
            fault.setattr(freshness, "_verify_unapplied_cancellation", cannot_prove)
        with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("reserved", None)]
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            1,
        )
    if unsafe == "proof_failure":
        assert (
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
            .outcomes[0]
            .effect_count
            == 1
        )


def test_u_real_effect_is_preserved_when_mark_processed_policy_fails(tmp_path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:effect", "round15:effect:event", contact_body())
    check = provider.require_auto_policy_under_guard

    def reject_terminal(*args, **kwargs):
        with closing(sqlite3.connect(provider.database)) as db:
            reserved = db.execute(
                "SELECT 1 FROM company_freshness_operations WHERE operation='mark_processed' AND state='reserved'"
            ).fetchone()
        if reserved:
            raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")
        return check(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(provider, "require_auto_policy_under_guard", reject_terminal)
        with pytest.raises(AnchorRejected, match="COMPANY_POLICY_REGISTRATION_REQUIRED"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        assert db.execute(
            "SELECT state FROM company_freshness_operations WHERE operation='mark_processed'"
        ).fetchone() == ("reserved",)
        assert db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE terminal_state='cancelled'"
        ).fetchone() == (0,)
    assert (
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
        .outcomes[0]
        .effect_count
        == 1
    )


@pytest.mark.parametrize(
    "boundary", ["pre_reserve", "reserved", "accepted_sql", "accepted", "completed", "processed"]
)
def test_t_original_automatic_workflow_crash_prefixes_remain_auditable(
    tmp_path, monkeypatch, boundary
):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:crash", "round15:crash:event", contact_body())

    def crash(*args, **kwargs):
        raise Crash()

    finish = engine._finish
    reserve = engine._reserve

    def reserve_then_crash(*args, **kwargs):
        reserve(*args, **kwargs)
        raise Crash()

    def finish_then_crash(*args, **kwargs):
        pending = args[1]
        result = finish(*args, **kwargs)
        wanted = {"accepted": "accept", "completed": "complete", "processed": "mark_processed"}
        if pending.operation == wanted[boundary]:
            raise Crash()
        return result

    with monkeypatch.context() as fault:
        if boundary == "pre_reserve":
            fault.setattr(engine, "_transition", crash)
        elif boundary == "reserved":
            fault.setattr(engine, "_reserve", reserve_then_crash)
        else:
            fault.setattr(
                engine, "_finish", crash if boundary == "accepted_sql" else finish_then_crash
            )
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    expected = {
        "pre_reserve": "ready",
        "reserved": "uncertain",
        "accepted_sql": "uncertain",
        "accepted": "mismatch",
        "completed": "mismatch",
        "processed": "mismatch",
    }
    assert readiness(provider, scope()).status == expected[boundary]
    with provider.read_only_report(scope()):
        pass
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert all(
        item.classification in {"auto_internal", "already_complete"} for item in result.outcomes
    )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchone() == (
            "processed_complete",
        )
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)


@pytest.mark.parametrize("operation", ["accept", "reject"])
@pytest.mark.parametrize("finish_crash", [False, True])
def test_x_authenticated_decision_and_pending_transition_remain_auditable(
    tmp_path, monkeypatch, operation, finish_crash
):
    cfg, provider = human_runtime(tmp_path)
    proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE),
            now=NOW,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    target = FreshnessScope(
        provider_instance_id=proposal["command"]["target"]["provider_instance_id"],
        workspace_id=proposal["command"]["target"]["workspace_id"],
    )
    assert readiness(provider, target).status == "ready"
    approval = owner_receipt(proposal, "approve" if operation == "accept" else "reject")
    request = signed_request(
        operation, processor_arguments(proposal, approval), PROCESSOR_KEY, "processor", PROCESSOR
    )

    def crash(*args, **kwargs):
        raise Crash()

    if finish_crash:
        with monkeypatch.context() as fault:
            fault.setattr(provider, "finish_progress", crash)
            with pytest.raises(Crash):
                run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    else:
        run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert readiness(provider, target).status == ("uncertain" if finish_crash else "ready")
    with provider.read_only_report(target):
        pass
    result = run(cfg, request, now=NOW, process_only=True, freshness_provider=provider)
    assert result["state"] == ("accepted" if operation == "accept" else "rejected")


def test_u_actual_key_rotation_after_reserve_closes_old_attempt(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from sb.company_auto_settings import bind_policy_signer
    from sb.effect_write_values import model_object
    from tests.test_company_round12_integrity import changed_registry

    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round15:old-key", "round15:old-key:event", contact_body())
    guard = provider.effect_guard

    @contextmanager
    def rotate_under_guard(*args, **kwargs):
        with guard(*args, **kwargs):
            provider.registry_path.write_bytes(
                canonical_bytes(model_object(changed_registry(provider, "key")))
            )
            yield

    with monkeypatch.context() as fault:
        fault.setattr(provider, "effect_guard", rotate_under_guard)
        with pytest.raises(AnchorRejected, match="COMPANY_POLICY_REGISTRATION_REQUIRED"):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "cancelled")]
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
    provider.install_auto_policy_pin(scope())
    rotated = replace(
        settings,
        signer=bind_policy_signer(
            settings.signer.principal_id,
            "policy-auto:round12",
            Ed25519PrivateKey.from_private_bytes(b"\x61" * 32),
        ),
    )
    receive(provider.database, "round15:new-key", "round15:new-key:event", contact_body())
    result = engine.run_auto_internal(provider.database, rotated, context, provider, trigger())
    assert [(item.candidate_id, item.effect_count) for item in result.outcomes] == [
        ("round15:new-key", 1)
    ]
    assert (
        engine.run_auto_internal(provider.database, rotated, context, provider, trigger()).outcomes
        == ()
    )
