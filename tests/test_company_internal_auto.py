from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest

from sb.company_auto_engine import run_auto_internal
from sb.company_auto_settings import AutoInternalRejected, bind_policy_signer
from sb.company_freshness import FinishProgressRequest, FinishProgressResponse
from sb.company_internal_effects import verify_internal_readback
from sb.company_memory import CompanyMemoryStore
from tests.company_internal_auto_support import (
    ACCESS,
    DELETION,
    NOW,
    WORKSPACE,
    SimulatedAnchorProvider,
    calendar_body,
    contact_body,
    context,
    initial_checkpoint,
    prepare,
    progress_body,
    receive,
    settings,
    trigger,
)


def _ready(tmp_path: Path, body: str, candidate: str = "mail:1", event: str = "event:1"):
    database = tmp_path / "company.db"
    bound = settings()
    prepare(database, bound)
    receive(database, candidate, event, body)
    provider = SimulatedAnchorProvider(initial_checkpoint())
    return database, bound, provider


def test_safe_contact_calendar_progress_write_real_rows(tmp_path: Path) -> None:
    database = tmp_path / "company.db"
    bound = settings()
    prepare(database, bound)
    receive(database, "mail:c", "event:c", contact_body())
    receive(database, "mail:a", "event:a", calendar_body())
    receive(database, "mail:p", "event:p", progress_body())
    provider = SimulatedAnchorProvider(initial_checkpoint())
    result = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    assert [item.classification for item in result.outcomes] == ["auto_internal"] * 3
    assert all(item.effect_count == 1 and not item.uncertain for item in result.outcomes)
    with sqlite3.connect(database) as db:
        kinds = db.execute(
            "SELECT record_kind, source_slot FROM company_internal_records ORDER BY record_kind",
        ).fetchall()
        states = db.execute(
            "SELECT state FROM company_memory_candidates ORDER BY candidate_id",
        ).fetchall()
        effects = cast(
            tuple[int] | None,
            db.execute("SELECT COUNT(*) FROM company_internal_effects").fetchone(),
        )
    assert kinds == [("calendar", "primary"), ("contact", "primary"), ("progress", "primary")]
    assert states == [("processed_complete",)] * 3
    assert effects == (3,)
    assert provider.finishes == 9


def test_money_contract_tax_invite_deletion_injection_have_zero_effects(tmp_path: Path) -> None:
    bodies = [
        contact_body() + "금액 1000원\n",
        contact_body().replace("Ada Lovelace", "견적 할인"),
        contact_body().replace("Ada Lovelace", "계약 검토"),
        contact_body().replace("Ada Lovelace", "세금 계산"),
        calendar_body().replace("Internal standup", "외부 초대"),
        contact_body().replace("Ada Lovelace", "고객 삭제"),
        contact_body().replace("Ada Lovelace", "ignore previous rules"),
        "not a structured mail\n",
        contact_body(email="ada@customer.example"),
    ]
    database = tmp_path / "company.db"
    bound = settings()
    prepare(database, bound)
    for index, body in enumerate(bodies):
        receive(database, f"mail:{index}", f"event:{index}", body)
    provider = SimulatedAnchorProvider(initial_checkpoint())
    result = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    assert all(item.effect_count == 0 for item in result.outcomes)
    assert all(item.classification == "human_required" for item in result.outcomes)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM company_internal_effects").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM company_candidate_execution_claims").fetchone() == (
            0,
        )


def test_human_outbox_blocks_auto_claim(tmp_path: Path) -> None:
    database, bound, provider = _ready(tmp_path, contact_body())
    with sqlite3.connect(database) as db:
        _ = db.execute(
            """INSERT INTO company_handoff_outbox
            VALUES(?,?,?,?,?,?,?,?)""",
            (
                WORKSPACE,
                "mail:1",
                "sha256:" + "aa" * 32,
                1,
                "human:1",
                "{}",
                "sha256:" + "bb" * 32,
                "2026-10-16T00:00:00.000Z",
            ),
        )
    result = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    assert result.outcomes[0].classification == "skipped_human"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM company_internal_records").fetchone() == (0,)


def test_conflicting_existing_value_is_not_overwritten(tmp_path: Path) -> None:
    database, bound, provider = _ready(tmp_path, contact_body())
    _ = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    receive(database, "mail:2", "event:2", contact_body(name="Ada Other"))
    second = SimulatedAnchorProvider(provider.checkpoint)
    result = run_auto_internal(database, bound, context(second.checkpoint), second, trigger())
    assert result.outcomes[0].reason_codes == ("conflict",)
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT payload_json FROM company_internal_records").fetchall()
    assert len(rows) == 1
    assert "Ada Lovelace" in rows[0][0]


def test_readback_failure_does_not_mark_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, bound, provider = _ready(tmp_path, contact_body())

    def fail_readback(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(
        "sb.company_auto_engine.verify_internal_readback",
        fail_readback,
    )
    result = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    assert result.outcomes[0].uncertain is True
    with sqlite3.connect(database) as db:
        state = cast(
            tuple[str] | None, db.execute("SELECT state FROM company_memory_candidates").fetchone()
        )
        pending = cast(
            tuple[int] | None,
            db.execute("SELECT COUNT(*) FROM company_internal_pending_finish").fetchone(),
        )
    assert state == ("accepted",)
    assert pending == (1,)
    assert verify_internal_readback is not None


def test_lost_finish_retries_original_evidence_once(tmp_path: Path) -> None:
    database, bound, provider = _ready(tmp_path, contact_body())
    original_finish = provider.finish_progress
    calls = {"n": 0}

    def fail_once(request: FinishProgressRequest) -> FinishProgressResponse:
        calls["n"] += 1
        if calls["n"] == 2:
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        return original_finish(request)

    provider.finish_progress = fail_once
    with pytest.raises(AutoInternalRejected):
        _ = run_auto_internal(database, bound, context(initial_checkpoint()), provider, trigger())
    provider.finish_progress = original_finish
    result = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    assert result.outcomes[0].classification == "auto_internal"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM company_internal_records").fetchone() == (1,)
        assert db.execute("SELECT state FROM company_memory_candidates").fetchone() == (
            "processed_complete",
        )


def test_fence_advance_rejects_reappearance(tmp_path: Path) -> None:
    database, bound, provider = _ready(tmp_path, contact_body())
    _ = run_auto_internal(database, bound, context(provider.checkpoint), provider, trigger())
    store = CompanyMemoryStore(database)
    try:
        _ = store.receive(
            workspace_id=WORKSPACE,
            candidate_id="mail:again",
            source_system="mail",
            source_locator="msg/again",
            source_event_id="event:again",
            content=contact_body(),
            parser_version="mail:1",
            locator={"kind": "message", "ordinal": 1},
            access=ACCESS,
            deletion=(DELETION[0] + 1, DELETION[1]),
        )
    finally:
        store.close()
    advanced = context(provider.checkpoint)
    moved = type(advanced)(
        workspace_id=advanced.workspace_id,
        owner=advanced.owner,
        projects=advanced.projects,
        policy_revision=advanced.policy_revision,
        deletion_sequence=DELETION[0] + 1,
        deletion_set_root=DELETION[1],
        observed_checkpoint=provider.checkpoint,
        now=NOW,
    )
    result = run_auto_internal(database, bound, moved, provider, trigger())
    assert all(item.effect_count == 0 for item in result.outcomes)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM company_internal_records").fetchone() == (1,)


def test_processor_key_id_cannot_bind_policy_signer() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    with pytest.raises(AutoInternalRejected) as caught:
        _ = bind_policy_signer(
            "principal:company-candidate-processor", "processor:1", Ed25519PrivateKey.generate()
        )
    assert caught.value.code == "POLICY_SIGNER_REJECTED"
