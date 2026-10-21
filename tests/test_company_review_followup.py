"""SB84 follow-up: fixture-only provider/anchor regressions."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import sb.company_freshness_operator as operator
import sb.company_processor_execution as execution
from sb.company_auto_engine import _candidate_ids, run_auto_internal
from sb.company_auto_report import read_auto_report
from sb.company_db_freshness import GenesisInventory, bootstrap_company_scope
from sb.company_db_freshness_models import FreshnessRegistry, GenesisEntry
from sb.company_freshness_anchor import AnchorRejected, nv_public_is_extend_only
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory import CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityContext, CompanyAuthorityRejected
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_db_freshness_support import (
    SimulatedNvAnchor,
    empty_genesis,
    write_registry,
    write_tree,
)
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    report_grant,
    trigger,
)
from tests.test_company_auto_report import query


def snapshot(provider):
    with closing(sqlite3.connect(provider.database)) as db:
        return (
            tuple(db.iterdump()),
            provider.anchor.read_value(),
            (provider.witness_dir / "frames.jsonl").read_bytes(),
        )


def test_projectless_candidates_do_not_starve_batch(tmp_path):
    provider, settings, context = real_company_runtime(tmp_path)
    for i in range(100):
        receive(provider.database, f"a:{i:03}", f"event:{i}", contact_body())
    receive(provider.database, "z:eligible", "event:z", contact_body())
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute(
            "UPDATE company_memory_candidates SET projects_json='[]' WHERE candidate_id LIKE 'a:%'"
        )
    assert _candidate_ids(provider.database, context, settings) == ("z:eligible",)


def test_uppercase_internal_domain_is_processed(tmp_path):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(
        provider.database,
        "mail:case",
        "event:case",
        contact_body().replace("mail.internal", "MAIL.INTERNAL"),
    )
    run_auto_internal(provider.database, settings, context, provider, trigger())
    page = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(),
    )
    assert page.contact_new == 1


def test_incremental_report_includes_earlier_assessment(tmp_path, monkeypatch):
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:uncertain", "event:u", contact_body())
    original = provider.finish_progress

    def fail_complete(request):
        if request.terminal_state == "completed":
            raise OSError("fixture readback unavailable")
        return original(request)

    monkeypatch.setattr(provider, "finish_progress", fail_complete)
    with pytest.raises((OSError, ValueError)):
        run_auto_internal(provider.database, settings, context, provider, trigger())
    with closing(sqlite3.connect(provider.database)) as db:
        sequence = db.execute(
            "SELECT MAX(global_sequence) FROM company_freshness_log WHERE phase='registry' AND json_extract(record_json,'$.kind')='internal_auto_assessment'"
        ).fetchone()[0]
    full = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(),
    )
    assert full.uncertain == 1
    incremental = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query().model_copy(update={"from_global_sequence": sequence}),
    )
    assert incremental.uncertain == 1
    assert len(incremental.rows) == 1


@pytest.mark.parametrize("extra", ["authwrite", "policywrite", "ppwrite"])
def test_nv_alternate_write_authority_is_rejected(extra):
    required = frozenset({"nt=extend", "policydelete", "written", "ownerwrite", "ownerread"})
    assert nv_public_is_extend_only(required)
    assert not nv_public_is_extend_only(required | {extra})


@pytest.mark.parametrize("missing", ["ownerwrite", "ownerread"])
def test_nv_owner_authorization_is_required(missing):
    required = frozenset({"nt=extend", "policydelete", "written", "ownerwrite", "ownerread"})
    assert not nv_public_is_extend_only(required - {missing})


@pytest.mark.parametrize(
    "instant", ["x" * 24, "2026-02-30T00:00:00.000Z", "2026-10-16T24:00:00.000Z"]
)
def test_genesis_rejects_invalid_original_time(instant):
    with pytest.raises(ValueError):
        GenesisEntry(
            source_record_id="fixture", source_digest="sha256:" + "ab" * 32, original_at=instant
        )


def test_duplicate_scope_pin_rejects_without_publication(tmp_path):
    from sb.company_freshness_migrations import apply_component_migration

    database, registry, witness, lock = write_tree(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    anchor = SimulatedNvAnchor(b"\x22" * 32, b"\x11" * 32)
    binding = "sha256:" + "11" * 32
    write_registry(
        registry,
        registry_id="company-freshness:linux:v1",
        installation_id="install-1",
        anchor=anchor,
        scope=scope,
        genesis=empty_genesis(scope, binding),
    )
    pins = FreshnessRegistry.model_validate_json(registry.read_bytes())
    registry.write_bytes(
        canonical_bytes(model_object(pins.model_copy(update={"scopes": pins.scopes * 2})))
    )
    apply_component_migration(database, "freshness")
    with closing(sqlite3.connect(database)) as db:
        before = tuple(db.iterdump())
    with pytest.raises(AnchorRejected):
        bootstrap_company_scope(
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
        )
    with closing(sqlite3.connect(database)) as db:
        assert tuple(db.iterdump()) == before
    assert anchor.extend_count == 0
    assert not (witness / "frames.jsonl").exists()


@pytest.mark.parametrize("mismatch", ["policy", "key"])
def test_operator_policy_pin_mismatch_has_no_writes(tmp_path, monkeypatch, mismatch):
    provider, settings, context = real_company_runtime(tmp_path)
    config_path = tmp_path / "operator-config"
    config_path.touch(mode=0o600)
    settings = (
        replace(settings, policy=settings.policy.model_copy(update={"policy_version": 2}))
        if mismatch == "policy"
        else replace(settings, signer=replace(settings.signer, key_id="policy-auto:other"))
    )
    monkeypatch.setattr(operator, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(operator, "require_trusted_file", lambda *a, **k: None)
    config = SimpleNamespace(
        provider_instance_id=PROVIDER, workspace_id=WORKSPACE, freshness_provider=None
    )
    monkeypatch.setattr(operator, "load_company_config", lambda _: config)
    monkeypatch.setattr(operator, "company_database_path", lambda _: provider.database)
    monkeypatch.setattr(operator, "provider_from_config", lambda *a, **k: provider)
    monkeypatch.setattr(operator, "auto_settings", lambda *a: settings)
    # Root-owned check is isolated by supplying a fixture stat result only for config.
    stat = Path.stat
    monkeypatch.setattr(
        Path,
        "stat",
        lambda p, **kw: SimpleNamespace(st_uid=0) if p == config_path else stat(p, **kw),
    )
    before = snapshot(provider)

    def forbidden_policy_write(*args, **kwargs):
        pytest.fail("registry mismatch reached immutable policy write")

    monkeypatch.setattr(operator, "install_auto_policy", forbidden_policy_write)
    with pytest.raises((AnchorRejected, ValueError)):
        operator.run_operator("auto-policy-install", config_path, b"", context.now)
    assert snapshot(provider) == before


def test_expiry_after_real_reserve_releases_only_new_unapplied_operation(tmp_path, monkeypatch):
    provider, _settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:expiry", "event:expiry", contact_body())
    digest = "sha256:" + "ab" * 32
    with closing(sqlite3.connect(provider.database)) as db, db:
        db.execute(
            "INSERT INTO company_handoff_outbox SELECT workspace_id,candidate_id,content_digest,1,'handoff:expiry','{}',content_digest,? FROM company_memory_candidates",
            (format_instant(context.now),),
        )
    calls = 0

    def authorize(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise CompanyAuthorityRejected("COMPANY_OWNER_APPROVAL_EXPIRED")

    monkeypatch.setattr(execution, "authorize_transition", authorize)
    authority_context = CompanyAuthorityContext(
        PROVIDER,
        WORKSPACE,
        context.owner,
        "agent",
        "session",
        context.projects,
        context.policy_revision,
        context.deletion_sequence,
        context.deletion_set_root,
    )
    with closing(CompanyMemoryStore(provider.database)) as store:
        with pytest.raises(CompanyAuthorityRejected, match="EXPIRED"):
            execution.execute_processor_transition(
                store,
                provider,
                context=authority_context,
                policy=None,
                owner_keys={},
                authority=SimpleNamespace(request_digest=digest),
                operation="accept",
                arguments={"candidate_id": "mail:expiry", "handoff_id": "handoff:expiry"},
                checkpoint=context.observed_checkpoint,
                now=context.now,
                clock=lambda: context.now,
            )
        assert store.db.execute(
            "SELECT state FROM company_memory_candidates WHERE candidate_id='mail:expiry'"
        ).fetchone() == ("candidate",)
        assert store.db.execute(
            "SELECT count(*) FROM company_processor_pending_finish"
        ).fetchone() == (0,)
        assert store.db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE operation='accept'"
        ).fetchone() == (0,)
        assert store.db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "cancelled")]
    checkpoint = local_checkpoint(provider.database, WORKSPACE, None)
    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE),
            installation_id=provider.installation_id,
            challenge="after-expiry",
            observed_checkpoint=checkpoint,
        )
    )
    assert response.status == "ready"


@pytest.mark.parametrize("boundary", ["witness", "extend", "checkpoint"])
def test_unapplied_cancellation_recovers_checkpoint(tmp_path, monkeypatch, boundary):
    import sb.company_db_freshness as freshness
    from sb.company_processor_progress import reserve_operation

    provider, _settings, context = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    digest = "sha256:" + "ab" * 32
    operation_id, reservation = reserve_operation(
        provider, scope, "accept", "request:cancel", digest, digest, context.observed_checkpoint
    )

    def fail(*args, **kwargs):
        raise AnchorRejected("fixture crash boundary")

    with monkeypatch.context() as fault:
        fault.setattr(
            freshness,
            {
                "witness": "append_witness_frame",
                "extend": "extend_if_needed",
                "checkpoint": "save_checkpoint",
            }[boundary],
            fail,
        )
        with provider.effect_guard(scope, operation_id, reservation), pytest.raises(AnchorRejected):
            provider.cancel_unapplied_under_guard(
                scope, operation_id, reservation, context.observed_checkpoint
            )
    assert local_checkpoint(provider.database, WORKSPACE, None) == context.observed_checkpoint
    recovered = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id=provider.installation_id,
            challenge="recover-cancel",
            observed_checkpoint=context.observed_checkpoint,
        )
    )
    assert recovered.status == "mismatch"
    after = local_checkpoint(provider.database, WORKSPACE, None)
    assert after is not None and after != context.observed_checkpoint
    ready = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id=provider.installation_id,
            challenge="verify-recovered-cancel",
            observed_checkpoint=after,
        )
    )
    assert ready.status == "ready"
    assert ready.checkpoint == after
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state,terminal_state FROM company_freshness_operations"
        ).fetchall() == [("finished", "cancelled")]
    # A different operation can advance after recovery; the cancelled identity cannot rerun.
    next_id, next_reservation = reserve_operation(
        provider, scope, "accept", "request:next", digest, digest, after
    )
    assert next_id != operation_id
    assert next_reservation.outcome == "reserved"


@pytest.mark.parametrize("unsafe", ["resumed", "pending", "complete"])
def test_unapplied_cancellation_refuses_uncertain_or_external_effect(tmp_path, unsafe):
    from sb.company_freshness_models import ReserveProgressRequest
    from sb.company_processor_finish import PendingFinish, save_pending_finish

    provider, _settings, context = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    digest = "sha256:" + "ab" * 32
    operation_id = "sha256:" + "cd" * 32
    reservation = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id,
            operation="complete" if unsafe == "complete" else "accept",
            expected_checkpoint=context.observed_checkpoint,
            event_digest=digest,
            challenge="reserve:uncertain",
        )
    )
    assert reservation.outcome == "reserved"
    if unsafe == "resumed":
        reservation = reservation.model_copy(update={"outcome": "already_reserved"})
    elif unsafe == "pending":
        with closing(sqlite3.connect(provider.database)) as db, db:
            save_pending_finish(
                db,
                WORKSPACE,
                digest,
                PendingFinish(
                    operation="accept", operation_id=operation_id, reservation=reservation
                ),
            )
    before = snapshot(provider)
    with pytest.raises(AnchorRejected), provider.effect_guard(scope, operation_id, reservation):
        provider.cancel_unapplied_under_guard(
            scope, operation_id, reservation, context.observed_checkpoint
        )
    assert snapshot(provider) == before
