"""Regression evidence for SB #84; simulated anchors are not TPM readiness."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

import sb.company_db_freshness as freshness
import sb.company_freshness_anchor as anchor
from sb.company_auto_engine import _candidate_ids, run_auto_internal
from sb.company_auto_report import read_auto_report
from sb.company_auto_settings import AutoInternalRejected, InternalAutoPolicyV1
from sb.company_db_freshness_models import FreshnessRegistry
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import FreshnessScope, ReadFreshnessRequest
from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_memory_cli import run
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_values import model_object
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    contact_body,
    policy,
    receive,
    report_grant,
    trigger,
)
from tests.test_company_auto_report import query
from tests.test_company_candidate_handoff import (
    PROCESSOR,
    PROCESSOR_KEY,
    enroll,
    first_proposal,
    handoff,
    owner_receipt,
    processor_arguments,
    setup_config,
    signed_request,
    states,
)
from tests.test_company_memory import DELETION, NOW, SCOPE, execute
from tests.test_company_memory import receive as memory_receive
from tests.test_company_processor_progress import ObservedProvider


@pytest.mark.parametrize("component", ["freshness", "internal_auto"])
def test_migration_alone_does_not_gate_default_transitions(tmp_path: Path, component: str) -> None:
    database = tmp_path / "company.db"
    with closing(CompanyMemoryStore(database)) as store:
        memory_receive(store)
        memory_receive(store, candidate="mail:reject")
    apply_component_migration(database, "freshness", now=format_instant(NOW))
    if component == "internal_auto":
        apply_component_migration(database, component, now=format_instant(NOW))
    with closing(CompanyMemoryStore(database)) as store:
        assert execute(store, "accept").result["state"] == "accepted"
        assert execute(store, "mark_processed").result["state"] == "processed_complete"
        assert store.reject(WORKSPACE, "mail:reject", SCOPE, DELETION, now=NOW).state == "rejected"
        store.db.execute("INSERT INTO company_handoff_enrollment VALUES(?,?)", (WORKSPACE, "{}"))
        store.db.commit()
        memory_receive(store, candidate="mail:enrolled")
        with pytest.raises(CompanyMemoryError, match="COMPANY_OWNER_APPROVAL_REQUIRED"):
            store.accept(WORKSPACE, "mail:enrolled", SCOPE, DELETION, now=NOW)


@pytest.mark.parametrize(
    "suffix",
    ["", "internal", "mail.internal", "@", ".", "@-bad.test", ".internal ", "@a..test", "@a/test"],
)
def test_email_suffix_must_have_a_domain_boundary(suffix: str) -> None:
    body = model_object(policy())
    body["internal_email_suffixes"] = [suffix]
    with pytest.raises(ValueError):
        InternalAutoPolicyV1.model_validate(body)


@pytest.mark.parametrize("suffix", [".internal", "@mail.internal", ".sub-domain.internal"])
def test_domain_bound_email_suffixes_remain_supported(suffix: str) -> None:
    body = model_object(policy())
    body["internal_email_suffixes"] = [suffix]
    assert InternalAutoPolicyV1.model_validate(body).internal_email_suffixes == [suffix]


@pytest.mark.parametrize(
    "blocked", ["human", "outbox", "decision", "accepted", "stale_sequence", "stale_root"]
)
def test_blocked_candidates_cannot_starve_current_batch(tmp_path: Path, blocked: str) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    for i in range(100):
        receive(provider.database, f"a:{i:03}", f"event:{i:03}", contact_body())
    receive(provider.database, "z:eligible", "event:eligible", contact_body())
    with closing(sqlite3.connect(provider.database)) as db, db:
        if blocked == "human":
            db.execute(
                """INSERT INTO company_candidate_execution_claims
                SELECT ?,workspace_id,candidate_id,content_digest,'human',candidate_id,?
                FROM company_memory_candidates WHERE candidate_id LIKE 'a:%'""",
                (PROVIDER, format_instant(context.now)),
            )
        elif blocked == "outbox":
            db.execute(
                """INSERT INTO company_handoff_outbox
                SELECT workspace_id,candidate_id,content_digest,1,candidate_id,'{}',content_digest,?
                FROM company_memory_candidates WHERE candidate_id LIKE 'a:%'""",
                (format_instant(context.now),),
            )
        elif blocked == "decision":
            db.execute(
                """INSERT INTO company_handoff_decisions
                SELECT workspace_id,candidate_id,candidate_id,candidate_id,content_digest,'approve','{}'
                FROM company_memory_candidates WHERE candidate_id LIKE 'a:%'"""
            )
        else:
            assignments = {
                "accepted": "state='accepted'",
                "stale_sequence": "deletion_sequence=1",
                "stale_root": "deletion_set_root='sha256:" + "ee" * 32 + "'",
            }
            db.execute(
                f"UPDATE company_memory_candidates SET {assignments[blocked]} WHERE candidate_id LIKE 'a:%'"
            )
    assert _candidate_ids(provider.database, context, settings) == ("z:eligible",)
    if blocked == "decision":
        # Synthetic decisions without commands/signatures/transitions are corrupt,
        # not authenticated human ownership. Selection still excludes them, but
        # the provider must reject this restored snapshot before any batch write.
        before = provider.database.read_bytes()
        with pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
            run_auto_internal(provider.database, settings, context, provider, trigger())
        assert provider.database.read_bytes() == before
        return
    result = run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result is not None
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT state FROM company_memory_candidates WHERE candidate_id='z:eligible'"
        ).fetchone() == ("processed_complete",)
        assert db.execute(
            "SELECT count(*) FROM company_auto_assessments WHERE candidate_id LIKE 'a:%'"
        ).fetchone() == (0,)


def test_shared_source_event_does_not_attribute_another_candidates_record(tmp_path: Path) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:first", "event:shared", contact_body())
    run_auto_internal(provider.database, settings, context, provider, trigger())
    receive(provider.database, "mail:second", "event:shared", contact_body())
    run_auto_internal(provider.database, settings, context, provider, trigger())
    report = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(),
    )
    rows = {row.candidate_id: row for row in report.rows}
    assert rows["mail:first"].record_kind == "contact"
    assert rows["mail:second"].classification == "human_required"
    assert rows["mail:second"].record_kind is None


@pytest.mark.parametrize("cursor", ["not-base64!", "e30"])
def test_invalid_report_cursor_keeps_permanent_rejection(tmp_path: Path, cursor: str) -> None:
    provider, _, _ = real_company_runtime(tmp_path)
    with pytest.raises(AutoInternalRejected, match="^REPORT_REJECTED$"):
        read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=query(cursor=cursor),
        )


@pytest.mark.parametrize("field", ["scope", "epoch", "from_sequence", "requested_to"])
def test_cursor_binding_errors_are_not_freshness_outages(tmp_path: Path, field: str) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    for i in range(2):
        receive(
            provider.database, f"human:{i}", f"event:{i}", "Contract payment requires approval."
        )
    run_auto_internal(provider.database, settings, context, provider, trigger())
    page = read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query(limit=1),
    )
    assert page.next_cursor is not None
    token = page.next_cursor
    body = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    if field == "scope":
        body[field]["workspace_id"] = "other-workspace"
    else:
        body[field] += 1
    changed = base64.urlsafe_b64encode(canonical_bytes(body)).rstrip(b"=").decode()
    with pytest.raises(AutoInternalRejected, match="^REPORT_REJECTED$"):
        read_auto_report(
            provider,
            provider_instance_id=PROVIDER,
            workspace_id=WORKSPACE,
            grant=report_grant(),
            query=query(limit=1, cursor=changed),
        )


@pytest.mark.parametrize("failure", ["short", "zero", "error"])
def test_witness_partial_write_does_not_poison_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    witness = tmp_path / "witness"
    witness.mkdir(mode=0o700)
    anchor.append_witness_frame(witness, {"sequence": 1})
    original = (witness / "frames.jsonl").read_bytes()
    write = os.write
    calls = 0

    def partial(fd: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return write(fd, payload[:3])
        if failure == "zero":
            return 0
        if failure == "error":
            raise OSError("simulated disk pressure")
        return write(fd, payload)

    with monkeypatch.context() as fault:
        fault.setattr(anchor.os, "write", partial)
        if failure == "short":
            anchor.append_witness_frame(witness, {"sequence": 2})
        else:
            with pytest.raises((OSError, AnchorRejected)):
                anchor.append_witness_frame(witness, {"sequence": 2})
            assert (witness / "frames.jsonl").read_bytes() == original
    assert anchor.read_witness_frames(witness) == (
        [{"sequence": 1}, {"sequence": 2}] if failure == "short" else [{"sequence": 1}]
    )
    anchor.append_witness_frame(witness, {"sequence": 3})
    assert anchor.read_witness_frames(witness)[-1] == {"sequence": 3}


@pytest.mark.parametrize("boundary", ["witness", "extend", "publication"])
def test_policy_checkpoint_recovers_with_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    provider, _, context = real_company_runtime(tmp_path)
    scope = FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)
    registry = FreshnessRegistry.model_validate_json(provider.registry_path.read_bytes())
    pin = registry.auto_policies[0].model_copy(update={"revision": 2})
    provider.registry_path.write_bytes(
        canonical_bytes(model_object(registry.model_copy(update={"auto_policies": [pin]})))
    )
    before = local_checkpoint(provider.database, WORKSPACE, None)
    assert before == context.observed_checkpoint

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

    with monkeypatch.context() as fault:
        name = {
            "witness": "append_witness_frame",
            "extend": "extend_if_needed",
            "publication": "save_checkpoint",
        }[boundary]
        fault.setattr(freshness, name, fail)
        with pytest.raises(AnchorRejected):
            provider.install_auto_policy_pin(scope)
    assert local_checkpoint(provider.database, WORKSPACE, None) == before
    # Read-only reports neither repair nor accept a pending publication.
    with (
        pytest.raises(AnchorRejected, match="COMPANY_PROGRESS_UNCERTAIN"),
        provider.read_only_report(scope),
    ):
        pass
    assert local_checkpoint(provider.database, WORKSPACE, None) == before
    response = provider.read_freshness(
        ReadFreshnessRequest(
            schema_version=2,
            scope=scope,
            installation_id=provider.installation_id,
            challenge="recover-policy",
            observed_checkpoint=before,
        )
    )
    assert response.status == "mismatch"
    after = local_checkpoint(provider.database, WORKSPACE, None)
    assert after is not None
    assert after != before
    assert local_checkpoint(provider.database, WORKSPACE, None) == after
    assert provider.install_auto_policy_pin(scope) == after


def test_approval_expiring_during_reserve_has_no_sql_effect(tmp_path: Path) -> None:
    config = setup_config(tmp_path)
    enroll(config)
    proposal = first_proposal(handoff(config))
    approval = owner_receipt(proposal)
    provider = ObservedProvider(config)
    from tests.test_company_memory_product import NOW as approval_now

    times = iter([approval_now, approval_now + timedelta(minutes=10)])
    with pytest.raises(CompanyAuthorityRejected):
        run(
            config,
            signed_request(
                "accept",
                processor_arguments(proposal, approval),
                PROCESSOR_KEY,
                "processor",
                PROCESSOR,
            ),
            process_only=True,
            freshness_provider=provider,
            clock=lambda: next(times),
        )
    assert provider.events == ["reserve"]
    assert len(provider.reservations) == 1
    assert provider.finishes == []
    assert states(config) == provider.before
    with closing(sqlite3.connect(config.parent / "company" / "company.db")) as db:
        assert db.execute("SELECT count(*) FROM company_handoff_decisions").fetchone() == (0,)
        assert db.execute(
            "SELECT count(*) FROM company_memory_receipts WHERE operation='accept'"
        ).fetchone() == (0,)
