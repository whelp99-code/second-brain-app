"""SB#84: pinned report cuts, schema guards and irreversible publication safety."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sb.company_auto_engine as engine
import sb.company_db_freshness as freshness
from sb.company_auto_report import AutoReportPage, AutoReportQuery, read_auto_report
from sb.company_auto_settings import AutoInternalRejected, AutoInternalSettings
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness_migrations import apply_component_migration
from sb.company_freshness_models import (
    FinishProgressResponse,
    FreshnessScope,
    ReadFreshnessRequest,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_memory import CompanyMemoryError
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes, format_instant
from tests.company_db_auto_support import real_company_runtime
from tests.company_internal_auto_support import (
    PROVIDER,
    WORKSPACE,
    contact_body,
    receive,
    report_grant,
    trigger,
)
from tests.test_company_auto_report import query
from tests.test_company_db_cancellation import cancelled_runtime, finish_with_proof


def report(
    provider: CompanyDbFreshnessProvider, request: AutoReportQuery | None = None
) -> AutoReportPage:
    return read_auto_report(
        provider,
        provider_instance_id=PROVIDER,
        workspace_id=WORKSPACE,
        grant=report_grant(),
        query=query() if request is None else request,
    )


def read_request(
    provider: CompanyDbFreshnessProvider, settings: AutoInternalSettings
) -> ReadFreshnessRequest:
    return ReadFreshnessRequest(
        schema_version=2,
        scope=FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE),
        installation_id=settings.installation_id,
        challenge="six-integrity-read",
        observed_checkpoint=local_checkpoint(provider.database, WORKSPACE, None),
    )


def test_cancelled_accept_is_in_incremental_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    cut = None
    late = False
    reserve = provider.reserve_progress
    build = engine.build_unsigned_receipt

    def delayed(request):
        nonlocal cut, late
        cut = report(provider).head_sequence
        result = reserve(request)
        late = True
        return result

    def aged(*args, **kwargs):
        kwargs["issued_at"] = format_instant(context.now - timedelta(minutes=4, seconds=59))
        return build(*args, **kwargs)

    monkeypatch.setattr(provider, "reserve_progress", delayed)
    monkeypatch.setattr(engine, "build_unsigned_receipt", aged)
    context = replace(
        context, clock=lambda: context.now + timedelta(seconds=2) if late else context.now
    )
    with pytest.raises(AutoInternalRejected, match="POLICY_RECEIPT_REJECTED"):
        engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert cut is not None
    page = report(provider, query().model_copy(update={"from_global_sequence": cut}))
    assert [(row.candidate_id, row.state) for row in page.rows] == [("mail:1", "cancelled")]
    assert page.rows[0].global_sequence > cut
    assert page.uncertain == 0 and page.contact_new == 0
    pinned = report(provider, query().model_copy(update={"to_global_sequence": cut}))
    assert pinned.rows[0].state == "candidate"


def test_cursor_cannot_expand_requested_upper_bound(tmp_path: Path) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    for index in range(2):
        receive(provider.database, f"mail:{index}", f"event:{index}", "Contract payment.")
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    first = report(provider, query(limit=1))
    assert first.next_cursor is not None
    decoded = json.loads(
        base64.urlsafe_b64decode(first.next_cursor + "=" * (-len(first.next_cursor) % 4))
    )
    upper = first.head_sequence - 1
    decoded["requested_to"] = upper
    forged = base64.urlsafe_b64encode(canonical_bytes(decoded)).rstrip(b"=").decode()
    with pytest.raises(AutoInternalRejected, match="REPORT_REJECTED"):
        report(
            provider,
            AutoReportQuery(
                from_global_sequence=0, to_global_sequence=upper, limit=1, cursor=forged
            ),
        )


_GUARDS = [
    "company_freshness_one_reserved",
    *[
        f"company_freshness_{table}_no_{action}"
        for table in ("epochs", "log", "evidence", "publication")
        for action in ("update", "delete")
    ],
    "company_freshness_operation_identity",
    "company_freshness_operation_finish_once",
]


@pytest.mark.parametrize("guard", _GUARDS)
@pytest.mark.parametrize("replace_guard", [False, True])
def test_marked_migration_checks_guard_definition(
    tmp_path: Path, guard: str, replace_guard: bool
) -> None:
    database = tmp_path / "company.db"
    apply_component_migration(database, "freshness")
    kind = "INDEX" if guard.endswith("one_reserved") else "TRIGGER"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(f"DROP {kind} {guard}")
        if replace_guard:
            if kind == "INDEX":
                db.execute(f"CREATE INDEX {guard} ON company_freshness_operations(workspace_id)")
            else:
                db.execute(
                    f"CREATE TRIGGER {guard} BEFORE UPDATE ON company_freshness_operations BEGIN SELECT 1; END"
                )
    with pytest.raises(CompanyMemoryError, match="COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED"):
        apply_component_migration(database, "freshness")


def test_cancellation_source_reuse_is_rejected_before_irreversible_publication(
    tmp_path: Path,
) -> None:
    provider, cfg, first, proof = cancelled_runtime(tmp_path)
    finished = finish_with_proof(provider, cfg, first, proof)
    assert isinstance(finished, FinishProgressResponse) and finished.checkpoint is not None
    assert finished.outcome == "recorded"
    scope = finished.scope
    command_digest = "sha256:" + hashlib.sha256(canonical_bytes(proof["command"])).hexdigest()
    operation = operation_id_for(
        scope,
        request_id=proof["command"]["request_id"],
        command_digest=command_digest,
        operation="decide_reject",
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation,
            operation="decide_reject",
            expected_checkpoint=finished.checkpoint,
            event_digest=command_digest,
            challenge="reuse-reserve",
        )
    )
    assert isinstance(reserved, ReserveProgressResponse) and reserved.outcome == "reserved"
    duplicate = {
        **first,
        "operation_id": operation,
        "reservation_id": reserved.reservation_id,
        "expected_checkpoint": reserved.checkpoint.model_dump(mode="json"),
    }
    nv = provider.anchor.read_value()
    witness = (provider.witness_dir / "frames.jsonl").read_bytes()
    with closing(sqlite3.connect(provider.database)) as db:
        count = db.execute("SELECT count(*) FROM company_freshness_log").fetchone()
    for _ in range(2):
        result = finish_with_proof(provider, cfg, duplicate, proof)
        assert isinstance(result, FinishProgressResponse) and result.outcome == "conflict"
        assert provider.anchor.read_value() == nv
        assert (provider.witness_dir / "frames.jsonl").read_bytes() == witness
        with closing(sqlite3.connect(provider.database)) as db:
            assert db.execute("SELECT count(*) FROM company_freshness_log").fetchone() == count
        provider._recover()


@pytest.mark.parametrize("crash", [False, True])
@pytest.mark.parametrize("same_payload", [False, True])
def test_stale_preflight_conflict_does_not_leave_reserved_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash: bool, same_payload: bool
) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:winner", "event:winner", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    receive(
        provider.database,
        "mail:loser",
        "event:loser",
        contact_body(name="Ada Lovelace" if same_payload else "Different Name"),
    )
    # Replay the preflight observation made before the other writer committed.
    with monkeypatch.context() as stale:
        stale.setattr(engine, "_record_conflict", lambda *args: False)
        if crash:

            def fail(*args):
                raise OSError("crash after cancellation NV extend")

            stale.setattr(freshness, "_consume_cancelled_auto_reserve", fail)
        with pytest.raises(
            OSError if crash else AutoInternalRejected,
            match="crash" if crash else "INTERNAL_RECORD_CONFLICT",
        ):
            engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    if crash:
        with pytest.raises(AutoInternalRejected, match="COMPANY_FRESHNESS_REQUIRED"):
            report(provider)
        # Recovery advances the local checkpoint; the pre-recovery observation
        # must not be accepted as ready in that same read.
        assert provider.read_freshness(read_request(provider, settings)).status == "mismatch"
    assert provider.read_freshness(read_request(provider, settings)).status == "ready"
    with closing(sqlite3.connect(provider.database)) as db:
        assert db.execute(
            "SELECT count(*) FROM company_freshness_operations WHERE state='reserved'"
        ).fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM company_internal_pending_reserve").fetchone() == (
            0,
        )
        assert db.execute("SELECT count(*) FROM company_internal_effects").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM company_internal_records").fetchone() == (1,)
    assert provider.read_freshness(read_request(provider, settings)).status == "ready"
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert result.outcomes[0].classification == "human_required"
    receive(
        provider.database,
        "mail:unrelated",
        "event:unrelated",
        contact_body(email="other@mail.internal"),
    )
    result = engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    assert sum(item.effect_count for item in result.outcomes) == 1


@pytest.mark.parametrize(
    "damage", ["missing", "root", "operation_id", "evidence_json", "created_at", "extra"]
)
def test_partial_evidence_restore_cannot_be_ready(tmp_path: Path, damage: str) -> None:
    provider, settings, context = real_company_runtime(tmp_path)
    receive(provider.database, "mail:1", "event:1", contact_body())
    engine.run_auto_internal(provider.database, settings, context, provider, trigger())
    request = read_request(provider, settings)
    assert provider.read_freshness(request).status == "ready"
    nv = provider.anchor.read_value()
    with closing(sqlite3.connect(provider.database)) as db, db:
        action = "delete" if damage == "missing" else "update"
        trigger_name = f"company_freshness_evidence_no_{action}"
        trigger_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (trigger_name,)
        ).fetchone()[0]
        db.execute(f"DROP TRIGGER {trigger_name}")
        if damage == "missing":
            changed = db.execute(
                "DELETE FROM company_freshness_evidence WHERE store='second_brain' AND stream='receipt' AND sequence=1"
            )
        elif damage == "extra":
            changed = db.execute("""INSERT INTO company_freshness_evidence
                SELECT provider_instance_id,workspace_id,store,stream,999,root,previous_root,
                operation_id,'extra-source',source_digest,evidence_json,created_at
                FROM company_freshness_evidence
                WHERE store='second_brain' AND stream='receipt' AND sequence=1""")
        else:
            value = "{}" if damage == "evidence_json" else "tampered"
            changed = db.execute(
                f"UPDATE company_freshness_evidence SET {damage}=? WHERE store='second_brain' AND stream='receipt' AND sequence=1",
                (value,),
            )
        assert changed.rowcount == 1
        db.execute(trigger_sql)
    response = provider.read_freshness(request)
    assert response.status != "ready" and response.checkpoint is None
    with pytest.raises(AutoInternalRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        report(provider)
    assert provider.anchor.read_value() == nv
