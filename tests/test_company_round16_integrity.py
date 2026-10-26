"""Synthetic Y/Z/AA assessment, effect inventory and cancellation regressions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import timedelta

import pytest

import sb.company_auto_engine as engine
import sb.company_internal_effects as effects
from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import FreshnessScope
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import contact_body, receive, trigger
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


@pytest.mark.parametrize("boundary", ["human_required", "assessment_commit", "issued"])
def test_y_classifier_version_restart_advances(tmp_path, monkeypatch, boundary):
    provider, settings, context = real_company_runtime(tmp_path)
    body = (
        "This mail has no actionable structured fields."
        if boundary == "human_required"
        else contact_body()
    )
    receive(provider.database, "round16:first", "round16:event", body)
    if boundary == "human_required":
        result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
        assert result.outcomes[0].classification == "human_required"
    else:

        def crash(*args, **kwargs):
            raise Crash()

        with monkeypatch.context() as fault:
            fault.setattr(
                provider if boundary == "assessment_commit" else engine,
                "publish_assessment" if boundary == "assessment_commit" else "_transition",
                crash,
            )
            with pytest.raises(Crash):
                engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    import sb.company_auto_policy as policy
    import sb.company_auto_readback as readback

    original_digest = engine.assessment_digest

    def current_digest(**kwargs):
        kwargs.setdefault("classifier_version", effects.CLASSIFIER_VERSION)
        return original_digest(**kwargs)

    monkeypatch.setattr(effects, "CLASSIFIER_VERSION", "mail-classifier:round16")
    monkeypatch.setattr(policy, "CLASSIFIER_VERSION", "mail-classifier:round16")
    monkeypatch.setattr(readback, "CLASSIFIER_VERSION", "mail-classifier:round16")
    monkeypatch.setattr(engine, "assessment_digest", current_digest)
    receive(
        provider.database,
        "round16:second",
        "round16:event2",
        contact_body("Bob", "bob@mail.internal"),
    )
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    if boundary == "issued":
        assert [(item.candidate_id, item.effect_count) for item in result.outcomes] == [
            ("round16:first", 1)
        ]
        result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert any(
        item.candidate_id == "round16:second" and item.effect_count == 1 for item in result.outcomes
    )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (
            (1 if boundary == "human_required" else 2),
        )
    assert readiness(provider, scope()).status == "ready"


@pytest.mark.parametrize(
    "damage", ["orphan_pair", "extra_record", "missing_record", "tampered_record"]
)
def test_z_exact_effect_record_inventory(tmp_path, damage):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round16:mail", "round16:source", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db, db:
        operation_id, digest = db.execute(
            "SELECT operation_id,effect_digest FROM company_internal_effects"
        ).fetchone()
        if damage in {"orphan_pair", "extra_record"}:
            row = list(db.execute("SELECT * FROM company_internal_records").fetchone())
            columns = [
                item[1] for item in db.execute("PRAGMA table_info(company_internal_records)")
            ]
            for column in ("record_id", "entity_key"):
                row[columns.index(column)] += ":extra"
            row[columns.index("source_slot")] = "zz_extra"
            if damage == "orphan_pair":
                orphan = list(db.execute("SELECT * FROM company_internal_effects").fetchone())
                cols = [
                    item[1] for item in db.execute("PRAGMA table_info(company_internal_effects)")
                ]
                for column in ("operation_id", "auto_request_id"):
                    orphan[cols.index(column)] += ":orphan"
                db.execute(
                    f"INSERT INTO company_internal_effects VALUES({','.join('?' for _ in orphan)})",
                    orphan,
                )
                row[columns.index("effect_operation_id")] = orphan[cols.index("operation_id")]
            db.execute(
                f"INSERT INTO company_internal_records VALUES({','.join('?' for _ in row)})", row
            )
        elif damage == "missing_record":
            db.execute("DROP TRIGGER company_internal_records_no_delete")
            db.execute("DELETE FROM company_internal_records")
        else:
            db.execute("DROP TRIGGER company_internal_records_no_update")
            db.execute("UPDATE company_internal_records SET payload_json='{}'")
    if damage != "orphan_pair":
        assert not effects.verify_internal_readback(
            provider.database, scope(), operation_id, digest
        )
    before = snapshot(provider)
    assert readiness(provider, scope()).status != "ready"
    with pytest.raises((AnchorRejected, ValueError)), provider.read_only_report(scope()):
        pass
    assert snapshot(provider) == before


@pytest.mark.parametrize("replacement", ["expired", "replaced", "crash_replaced"])
def test_aa_replaced_outbox_cancellation_releases_next_command(tmp_path, monkeypatch, replacement):
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
    request = signed_request(
        "accept",
        processor_arguments(proposal, owner_receipt(proposal, "approve")),
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
    )
    guard = provider.effect_guard
    late = False

    @contextmanager
    def expire_after_reserve(*args, **kwargs):
        nonlocal late
        with guard(*args, **kwargs):
            with closing(sqlite3.connect(provider.database)) as db, db:
                if replacement != "expired":
                    command = json.loads(
                        db.execute("SELECT command_json FROM company_handoff_outbox").fetchone()[0]
                    )
                    command["request_id"] = command["request_id"].rsplit(":", 1)[0] + ":2"
                    command["nonce"] = command["request_id"]
                    from sb.company_auto_policy import command_digest

                    db.execute(
                        "UPDATE company_handoff_outbox SET request_id=?,generation=2,command_json=?,command_digest=?",
                        (command["request_id"], json.dumps(command), command_digest(command)),
                    )
            late = True
            if replacement == "crash_replaced":
                raise Crash()
            yield

    with monkeypatch.context() as fault:
        fault.setattr(provider, "effect_guard", expire_after_reserve)
        with pytest.raises(Crash if replacement == "crash_replaced" else CompanyAuthorityRejected):
            run(
                cfg,
                request,
                now=NOW,
                clock=lambda: NOW + timedelta(days=2) if late else NOW,
                process_only=True,
                freshness_provider=provider,
            )
    if replacement == "crash_replaced":
        with pytest.raises(CompanyAuthorityRejected):
            run(
                cfg,
                request,
                now=NOW,
                clock=lambda: NOW,
                process_only=True,
                freshness_provider=provider,
            )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "cancelled")]
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (0,)
    assert readiness(provider, target).status == "ready"
    later = NOW + timedelta(days=3)
    next_proposal = first_proposal(
        run(
            cfg,
            signed_request("handoff", PAGE, at=later),
            now=later,
            handoff_only=True,
            freshness_provider=provider,
        )
    )
    next_request = signed_request(
        "accept",
        processor_arguments(next_proposal, owner_receipt(next_proposal, "approve", at=later)),
        PROCESSOR_KEY,
        "processor",
        PROCESSOR,
        at=later,
    )
    result = run(
        cfg,
        next_request,
        now=later,
        clock=lambda: later,
        process_only=True,
        freshness_provider=provider,
    )
    assert result["state"] == "accepted"


@pytest.mark.parametrize("changed", ["classification", "fields"])
def test_y_version_change_does_not_authorize_different_output(tmp_path, monkeypatch, changed):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "round16:changed", "round16:changed:event", contact_body())

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as fault:
        fault.setattr(provider, "publish_assessment", crash)
        with pytest.raises(Crash):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    classify = engine.classify_mail_candidate

    def different(candidate):
        original = classify(candidate)
        return replace(
            original,
            **(
                {
                    "classification": "human_required",
                    "reason_codes": ("changed",),
                    "record_kind": None,
                }
                if changed == "classification"
                else {"fields": {**original.fields, "name": "Mallory"}}
            ),
        )

    monkeypatch.setattr(effects, "CLASSIFIER_VERSION", "mail:changed")
    monkeypatch.setattr(engine, "classify_mail_candidate", different)
    with pytest.raises(AutoInternalRejected, match="ASSESSMENT_CONFLICT"):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        for table in (
            "company_internal_effects",
            "company_auto_policy_receipts",
            "company_candidate_execution_claims",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
