"""SB2 P02 persistence tests against the real current Ledger and CAS."""

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from sb.life_contracts import LifeInputError
from sb.store.ledger import Ledger
from sb.store.life import LifeStore
from tests.test_life_contracts import NOW, payload, policy


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LifeStore]:
    with Ledger(tmp_path) as ledger:
        yield ledger.life_store()


def test_ten_retries_create_one_event_and_one_receipt(store: LifeStore) -> None:
    receipts = [store.accept(payload(), policy(), key="request-1", now=NOW) for _ in range(10)]
    assert len({r.receipt_id for r in receipts}) == 1
    assert not receipts[0].replayed and all(r.replayed for r in receipts[1:])
    assert len(store.events(scopes=("owner:test",), now=NOW)) == 1


def test_idempotency_key_cannot_change_payload(store: LifeStore) -> None:
    _ = store.accept(payload(), policy(), key="request-1", now=NOW)
    with pytest.raises(LifeInputError, match="IDEMPOTENCY_CONFLICT"):
        _ = store.accept(payload(body="different"), policy(), key="request-1", now=NOW)


def test_same_source_version_cannot_silently_change_content(store: LifeStore) -> None:
    _ = store.accept(payload(), policy(), key="request-1", now=NOW)
    with pytest.raises(LifeInputError, match="SOURCE_VERSION_CONFLICT"):
        _ = store.accept(
            payload(body="different"), policy(), key="request-2", now=NOW, expected_revision=1
        )


def test_correction_is_append_only_with_compare_and_swap(store: LifeStore) -> None:
    old = store.accept(payload(), policy(), key="r1", now=NOW)
    new = store.accept(
        payload(source_version="v2", body="changed"),
        policy(),
        key="r2",
        now=NOW + timedelta(minutes=1),
        expected_revision=1,
    )
    assert old.event_id == new.event_id and new.revision == 2
    assert store.get(old.event_id, scopes=("owner:test",), now=NOW).body == "changed"
    assert store.history(old.event_id, scopes=("owner:test",), now=NOW)[0].body == "실제 메모"
    with pytest.raises(LifeInputError, match="REVISION_CONFLICT"):
        _ = store.accept(
            payload(source_version="v3"), policy(), key="r3", now=NOW, expected_revision=1
        )


def test_authority_cannot_be_relaxed_by_changing_operator_policy_mid_event(
    store: LifeStore,
) -> None:
    _ = store.accept(payload(), policy(), key="r1", now=NOW)
    with pytest.raises(LifeInputError, match="POLICY_CHANGED"):
        _ = store.accept(
            payload(source_version="v2"),
            replace(policy(), scopes=("other",)),
            key="r2",
            now=NOW,
            expected_revision=1,
        )


def test_scope_filter_happens_before_limit_and_hides_receipts(store: LifeStore) -> None:
    foreign = store.accept(
        payload(), replace(policy(), source_id="foreign", scopes=("other",)), key="r1", now=NOW
    )
    own = store.accept(payload(), policy(), key="r1", now=NOW)
    assert [e.event_id for e in store.events(scopes=("owner:test",), now=NOW, limit=1)] == [
        own.event_id
    ]
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        _ = store.get(foreign.event_id, scopes=("owner:test",), now=NOW)
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        _ = store.receipt(foreign.receipt_id, scopes=("owner:test",), now=NOW)


def test_original_is_retrievable_and_integrity_checked(store: LifeStore) -> None:
    accepted = store.accept(payload(), policy(), key="r1", now=NOW)
    raw = store.evidence(accepted.event_id, scopes=("owner:test",), now=NOW)
    event = store.get(accepted.event_id, scopes=("owner:test",), now=NOW)
    assert sha256(raw).hexdigest() == event.raw_digest


def test_delete_is_monotonic_and_blocks_replay(store: LifeStore) -> None:
    accepted = store.accept(payload(), policy(), key="r1", now=NOW)
    store.forget(accepted.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
    assert store.events(scopes=("owner:test",), now=NOW) == ()
    with pytest.raises(LifeInputError, match="DELETED"):
        _ = store.accept(payload(), policy(), key="r1", now=NOW)
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        _ = store.evidence(accepted.event_id, scopes=("owner:test",), now=NOW)
    assert store.tombstones(scopes=("owner:test",))[0]["event_id"] == accepted.event_id


def test_revision_rows_are_immutable_at_sql_boundary(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        _ = ledger.life_store().accept(payload(), policy(), key="r1", now=NOW)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            _ = ledger.life_store().connection.execute(
                "UPDATE life_event_revisions SET body_json='{}'"
            )


def test_reopen_preserves_receipt_and_cas(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        first = ledger.life_store().accept(payload(), policy(), key="r1", now=NOW)
    with Ledger(tmp_path) as ledger:
        second = ledger.life_store().accept(payload(), policy(), key="r1", now=NOW)
        assert second.receipt_id == first.receipt_id and second.replayed
        assert ledger.life_store().evidence(second.event_id, scopes=("owner:test",), now=NOW)


def test_outer_ledger_transaction_rolls_back_life_records(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        with pytest.raises(RuntimeError), ledger.transaction():
            _ = store.accept(payload(), policy(), key="r1", now=NOW)
            raise RuntimeError("synthetic rollback")
        assert store.events(scopes=("owner:test",), now=NOW) == ()


def test_backup_preserves_life_rows_and_delete_intent(tmp_path: Path) -> None:
    root = tmp_path / "original"
    with Ledger(root) as ledger:
        store = ledger.life_store()
        accepted = store.accept(payload(), policy(), key="r1", now=NOW)
        store.forget(accepted.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
        target = sqlite3.connect(tmp_path / "copy.db")
        ledger.life_store().connection.backup(target)
        target.close()
    with sqlite3.connect(tmp_path / "copy.db") as restored:
        assert restored.execute("SELECT deleted FROM life_events").fetchone() == (1,)
        assert restored.execute("SELECT count(*) FROM life_tombstones").fetchone() == (1,)


def test_receipt_state_advances_accepted_published_searchable_only_with_proof(store: LifeStore) -> None:
    accepted = store.accept(payload(), policy(), key="r1", now=NOW)
    assert accepted.state == "accepted"
    assert not store.receipt_is_searchable(accepted.receipt_id)
    with pytest.raises(LifeInputError, match="PROOF_REQUIRED"):
        _ = store.advance_receipt(accepted.receipt_id, "published", proof="")
    with pytest.raises(LifeInputError, match="STATE_INVALID"):
        _ = store.advance_receipt(accepted.receipt_id, "searchable", proof="index-1")
    published = store.advance_receipt(accepted.receipt_id, "published", proof="commit-sha")
    assert published.state == "published"
    assert store.receipt_proof(accepted.receipt_id) == "commit-sha"
    assert not store.receipt_is_searchable(accepted.receipt_id)
    searchable = store.advance_receipt(accepted.receipt_id, "searchable", proof="index-gen")
    assert searchable.state == "searchable"
    assert store.receipt_is_searchable(accepted.receipt_id)
    assert store.receipt(accepted.receipt_id, scopes=("owner:test",), now=NOW).state == "searchable"


def test_unknown_receipt_state_is_not_searchable(store: LifeStore) -> None:
    accepted = store.accept(payload(), policy(), key="r1", now=NOW)
    _ = store.connection.execute(
        "UPDATE life_receipts SET state=?,proof=? WHERE receipt_id=?",
        ("processing", "not-a-search-proof", accepted.receipt_id),
    )
    assert store.receipt(
        accepted.receipt_id, scopes=("owner:test",), now=NOW
    ).state == "processing"
    assert not store.receipt_is_searchable(accepted.receipt_id)


def test_transition_rule_enforced_on_revision_two(store: LifeStore) -> None:
    accepted = store.accept(
        payload(event_status="occurred", evidence_level="observed"), policy(), key="r1", now=NOW
    )
    with pytest.raises(LifeInputError, match="TRANSITION_FORBIDDEN"):
        _ = store.accept(
            payload(source_version="v2", event_status="planned", evidence_level="observed"),
            policy(),
            key="r2",
            now=NOW + timedelta(minutes=1),
            expected_revision=1,
        )
    corrected = store.accept(
        payload(
            source_version="v3",
            event_status="cancelled",
            evidence_level="user_asserted",
        ),
        policy(),
        key="r3",
        now=NOW + timedelta(minutes=2),
        expected_revision=1,
    )
    assert corrected.revision == 2
    assert store.get(accepted.event_id, scopes=("owner:test",), now=NOW).event_status == "cancelled"


def test_backup_preserves_receipt_state(tmp_path: Path) -> None:
    root = tmp_path / "original"
    with Ledger(root) as ledger:
        store = ledger.life_store()
        accepted = store.accept(payload(), policy(), key="r1", now=NOW)
        _ = store.advance_receipt(accepted.receipt_id, "published", proof="commit-sha")
        target = sqlite3.connect(tmp_path / "copy.db")
        store.connection.backup(target)
        target.close()
    with sqlite3.connect(tmp_path / "copy.db") as restored:
        assert restored.execute(
            "SELECT state,proof FROM life_receipts"
        ).fetchone() == ("published", "commit-sha")
        assert restored.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("2",)


def test_schema_v1_upgrade_preserves_receipt_identity(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    with Ledger(root) as ledger:
        store = ledger.life_store()
        accepted = store.accept(payload(), policy(), key="r1", now=NOW)
        with ledger.transaction():
            _ = store.connection.execute("ALTER TABLE life_receipts DROP COLUMN proof")
            _ = store.connection.execute("ALTER TABLE life_receipts DROP COLUMN state")
            _ = store.connection.execute(
                "UPDATE schema_meta SET value='1' WHERE key='life_schema_version'"
            )

    with Ledger(root) as ledger:
        upgraded = ledger.life_store()
        receipt = upgraded.receipt(accepted.receipt_id, scopes=("owner:test",), now=NOW)
        replayed = upgraded.accept(payload(), policy(), key="r1", now=NOW)
        assert receipt.receipt_id == replayed.receipt_id == accepted.receipt_id
        assert receipt.state == replayed.state == "accepted"
        assert replayed.replayed is True
        assert upgraded.receipt_proof(accepted.receipt_id) == ""
        assert upgraded.connection.execute(
            "SELECT value FROM schema_meta WHERE key='life_schema_version'"
        ).fetchone() == ("2",)


def test_retention_expiry_is_not_a_current_memory(store: LifeStore) -> None:
    accepted = store.accept(payload(), replace(policy(), retention_days=1), key="r1", now=NOW)
    assert store.events(scopes=("owner:test",), now=NOW + timedelta(days=2)) == ()
    with pytest.raises(LifeInputError, match="NOT_FOUND"):
        _ = store.get(accepted.event_id, scopes=("owner:test",), now=NOW + timedelta(days=2))
