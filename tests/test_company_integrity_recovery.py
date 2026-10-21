from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
import sb.company_freshness_operator as operator
from sb.company_approver_binding import public_key_fingerprint
from sb.company_auto_policy import policy_digest
from sb.company_auto_settings import AutoInternalRejected
from sb.company_db_freshness_models import FreshnessRegistry
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import FreshnessScope
from sb.company_memory import CompanyMemoryError
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import WORKSPACE, contact_body, receive, trigger


@pytest.mark.parametrize("resumed,crash", [(False, False), (True, False), (False, True)])
def test_expired_during_accept_reserve_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resumed: bool, crash: bool
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    late = False
    reserve = provider.reserve_progress

    def delayed(request):
        nonlocal late
        result = reserve(request)
        if resumed:
            result = reserve(request)
        late = True
        return result

    monkeypatch.setattr(provider, "reserve_progress", delayed)
    build = engine.build_unsigned_receipt

    def aged(*args, **kwargs):
        kwargs["issued_at"] = format_instant(context.now - timedelta(minutes=4, seconds=59))
        return build(*args, **kwargs)

    monkeypatch.setattr(engine, "build_unsigned_receipt", aged)
    context = replace(
        context, clock=lambda: context.now + timedelta(seconds=2) if late else context.now
    )
    consume = freshness._consume_cancelled_auto_reserve
    if crash:

        def fail(*args):
            raise OSError("crash before cancellation publication")

        monkeypatch.setattr(freshness, "_consume_cancelled_auto_reserve", fail)
    with pytest.raises(
        OSError if crash else AutoInternalRejected,
        match="crash" if crash else "POLICY_RECEIPT_REJECTED",
    ):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    if crash:
        monkeypatch.setattr(freshness, "_consume_cancelled_auto_reserve", consume)
        request = freshness.ReadFreshnessRequest(
            schema_version=2,
            scope=FreshnessScope(
                provider_instance_id=settings.provider_instance_id, workspace_id=WORKSPACE
            ),
            installation_id=settings.installation_id,
            challenge="recover-cancel",
            observed_checkpoint=local_checkpoint(provider.database, WORKSPACE, None),
        )
        assert provider.read_freshness(request).status != "uncertain"
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            int(resumed),
        )
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == ([("reserved", None)] if resumed else [("finished", "cancelled")])
        assert db.execute("SELECT count(*) FROM company_memory_receipts").fetchone() == (0,)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=WORKSPACE
    )
    if not resumed:
        assert local_checkpoint(provider.database, WORKSPACE, None) == provider._head(scope)


@pytest.mark.parametrize("rotate", [False, True])
def test_accepted_workflow_remains_visible_after_policy_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rotate: bool
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    original = engine._transition

    def crash(*args, **kwargs):
        if args[7] == "complete":
            raise RuntimeError("crash after accept")
        return original(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(engine, "_transition", crash)
        with pytest.raises(RuntimeError):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    rotated = replace(
        settings,
        policy=settings.policy.model_copy(
            update={"policy_version": settings.policy.policy_version + 1}
        ),
    )
    assert engine._candidate_ids(provider.database, context, rotated) == ("mail:1",)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id, workspace_id=WORKSPACE
    )
    checkpoint = local_checkpoint(provider.database, WORKSPACE, None)
    blocked, after = engine._one(
        provider.database, rotated, context, provider, scope, "mail:1", checkpoint, trigger()
    )
    assert blocked.reason_codes == ("policy_changed",)
    assert blocked.effect_count == 0 and after == checkpoint
    if rotate:
        from sb.company_internal_effects import install_auto_policy

        registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
        old = registry.auto_policies[0]
        pin = old.model_copy(
            update={
                "revision": 2,
                "policy_digest": policy_digest(rotated.policy),
                "revoked_policy_digests": [old.policy_digest],
            }
        )
        provider.registry_path.write_bytes(
            canonical_bytes(model_object(registry.model_copy(update={"auto_policies": [pin]})))
        )
        provider.validate_auto_policy_pin(scope)
        with closing(sqlite3.connect(provider.database)) as db, db:
            install_auto_policy(db, rotated, WORKSPACE, context.now)
        provider.install_auto_policy_pin(scope)
        receive(provider.database, "mail:new", "event:new", contact_body())
        result = engine.run_auto_internal(provider.database, rotated, context, provider, trigger())
        assert [(row.candidate_id, row.classification) for row in result.outcomes] == [
            ("mail:new", "auto_internal"),
            ("mail:1", "blocked_policy"),
        ]
        with closing(sqlite3.connect(provider.database)) as db:
            assert db.execute(
                "SELECT state FROM company_memory_candidates WHERE candidate_id='mail:1'"
            ).fetchone() == ("accepted",)
            assert db.execute(
                "SELECT count(*) FROM company_auto_policy_receipts WHERE candidate_id='mail:1'"
            ).fetchone() == (1,)
            assert db.execute(
                "SELECT count(*) FROM company_internal_effects WHERE candidate_id='mail:1'"
            ).fetchone() == (0,)
        with pytest.raises(AnchorRejected):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
        return
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].effect_count == 1
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT state FROM company_memory_candidates").fetchone() == (
            "processed_complete",
        )


@pytest.mark.parametrize(
    "table",
    [
        "company_freshness_epochs",
        "company_freshness_scopes",
        "company_freshness_log",
        "company_freshness_publication",
        "company_freshness_operations",
        "company_freshness_evidence",
    ],
)
def test_marked_partial_restore_is_rejected(tmp_path: Path, table: str) -> None:
    database = tmp_path / "company.db"
    apply_component_migration(database, "freshness")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(f"DROP TABLE {table}")
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        apply_component_migration(database, "freshness")


@pytest.mark.parametrize("invalid", ["revision", "key_revocation", "valid"])
def test_operator_rejects_invalid_pin_before_policy_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    provider, settings, context = real_company_runtime(tmp_path)
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    old = registry.auto_policies[0]
    changed = replace(
        settings,
        policy=settings.policy.model_copy(
            update={"policy_version": settings.policy.policy_version + 1}
        ),
    )
    updates = {
        "policy_digest": policy_digest(changed.policy),
        "revoked_policy_digests": [old.policy_digest],
    }
    if invalid == "valid":
        updates["revision"] = 2
    if invalid == "key_revocation":
        key = Ed25519PrivateKey.from_private_bytes(b"x" * 32)
        changed = replace(
            changed, signer=replace(changed.signer, private_key=key, public_key=key.public_key())
        )
        updates.update(
            revision=2,
            public_key=base64.urlsafe_b64encode(key.public_key().public_bytes_raw())
            .rstrip(b"=")
            .decode(),
            public_key_fingerprint=public_key_fingerprint(key.public_key()),
        )
    pin = old.model_copy(update=updates)
    provider.registry_path.write_bytes(
        canonical_bytes(model_object(registry.model_copy(update={"auto_policies": [pin]})))
    )
    config = SimpleNamespace(
        provider_instance_id=settings.provider_instance_id,
        workspace_id=WORKSPACE,
        freshness_provider=None,
    )
    monkeypatch.setattr(operator, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(operator, "require_trusted_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(operator, "load_company_config", lambda _: config)
    monkeypatch.setattr(operator, "company_database_path", lambda _: provider.database)
    monkeypatch.setattr(operator, "provider_from_config", lambda *args, **kwargs: provider)
    monkeypatch.setattr(operator, "auto_settings", lambda *args: changed)
    if invalid == "valid":
        result = operator.run_operator(
            "auto-policy-install",
            SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=0)),
            b"",
            context.now,
        )
        assert result["policy_digest"] == policy_digest(changed.policy)
        receive(provider.database, "mail:new", "event:new", contact_body())
        outcome = engine.run_auto_internal(provider.database, changed, context, provider, trigger())
        assert outcome.outcomes[0].effect_count == 1
        return
    with pytest.raises(AnchorRejected, match="COMPANY_POLICY_REGISTRATION_REQUIRED"):
        operator.run_operator(
            "auto-policy-install",
            SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=0)),
            b"",
            context.now,
        )
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute("SELECT policy_digest FROM company_auto_policies").fetchall() == [
            (old.policy_digest,)
        ]


@pytest.mark.parametrize(
    "evidence",
    [
        "company_memory_receipts",
        "company_processor_pending_finish",
        "company_internal_pending_finish",
        "company_internal_effects",
    ],
)
def test_cancellation_refuses_applied_or_pending_evidence(evidence: str) -> None:
    scope = FreshnessScope(provider_instance_id="fixture-provider", workspace_id=WORKSPACE)
    original = SimpleNamespace(
        actor_store="second_brain",
        operation="accept",
        operation_id="op",
        reservation_id="reserve",
        event_digest="event",
    )
    record = {
        "operation_id": "op",
        "reservation_id": "reserve",
        "event_digest": "event",
        "terminal_state": "cancelled",
        "original_at": "2026-10-16T08:00:00.000Z",
    }
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE TABLE company_memory_receipts(workspace_id, request_digest)")
        db.execute("CREATE TABLE company_processor_pending_finish(workspace_id, request_digest)")
        if evidence == "company_internal_effects":
            db.execute(f"CREATE TABLE {evidence}(provider_instance_id, workspace_id, operation_id)")
            db.execute(
                f"INSERT INTO {evidence} VALUES(?,?,?)",
                (scope.provider_instance_id, WORKSPACE, "op"),
            )
        else:
            db.execute(f"CREATE TABLE IF NOT EXISTS {evidence}(workspace_id, request_digest)")
            db.execute(f"INSERT INTO {evidence} VALUES(?,?)", (WORKSPACE, "event"))
        with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            freshness._verify_unapplied_cancellation(db, scope, original, record)
