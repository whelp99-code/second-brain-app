"""Forget tombstones a CAS blob only when no live or legacy reference remains."""

from datetime import timedelta

from sb.config import TomlValue
from sb.effect_values import JsonObject, JsonValue
from sb.life_attachments import inline
from sb.pipeline import run_life_batch, run_life_maintenance
from sb.store.ledger import Ledger
from tests.life_test_support import config_table, json_int, json_object
from tests.test_life_contracts import NOW, payload, policy
from tests.test_life_pipeline import item, life_config


def _attach(body: str, name: str, blob: bytes) -> JsonObject:
    attachment = json_object(inline(name + ".txt", "text/plain", blob))
    attachments: list[JsonValue] = [attachment]
    return payload(source_item_id=name, body=body, attachments=attachments)


def test_forget_last_reference_tombstones_raw_and_attachments(tmp_path):
    blob = b"attachment-bytes"
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accepted = store.accept(_attach("memo", "only", blob), policy(), key="r1", now=NOW)
        event = store.get(accepted.event_id, scopes=("owner:test",), now=NOW)
        attachment = event.attachments[0].sha256
        store.forget(accepted.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
        assert store.cas.is_tombstoned(event.raw_digest)
        assert store.cas.is_tombstoned(attachment)
        assert (tmp_path / "raw" / event.raw_digest[:2] / event.raw_digest).is_file()
        assert not store.cas.exists(event.raw_digest)


def test_shared_blob_with_live_reference_is_kept(tmp_path):
    blob = b"shared-attachment"
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        first = store.accept(_attach("one", "a", blob), policy(), key="a", now=NOW)
        second = store.accept(_attach("two", "b", blob), policy(), key="b", now=NOW)
        shared = store.get(first.event_id, scopes=("owner:test",), now=NOW).attachments[0].sha256
        assert shared == store.get(second.event_id, scopes=("owner:test",), now=NOW).attachments[0].sha256
        store.forget(first.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
        assert not store.cas.is_tombstoned(shared)
        assert store.cas.exists(shared)
        store.forget(second.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
        assert store.cas.is_tombstoned(shared)


def test_legacy_source_item_reference_blocks_tombstone(tmp_path):
    with Ledger(tmp_path) as ledger:
        store = ledger.life_store()
        accepted = store.accept(payload(), policy(), key="r1", now=NOW)
        event = store.get(accepted.event_id, scopes=("owner:test",), now=NOW)
        with ledger.transaction():
            store.connection.execute(
                "INSERT INTO source_item VALUES(?,?,?,?,?,?)",
                ("legacy", "legacy/item", "v1", event.raw_digest, "run", "run"),
            )
        store.forget(accepted.event_id, scopes=("owner:test",), expected_revision=1, now=NOW)
        assert not store.cas.is_tombstoned(event.raw_digest)
        assert store.cas.exists(event.raw_digest)


def test_maintenance_reports_physical_erasure_counts(tmp_path):
    config, root = life_config(tmp_path)
    life = {key: value for key, value in config_table(config.raw["life"]).items()}
    note: dict[str, TomlValue] = {"enabled": True, "retention_days": 1}
    sources: dict[str, TomlValue] = {"test-notes": note}
    life["sources"] = sources
    raw: dict[str, TomlValue] = {key: value for key, value in config.raw.items()}
    raw["life"] = life
    config = type(config)(raw=raw)
    before = NOW - timedelta(days=3)
    outcome, receipts = run_life_batch(
        config, "test-notes", [item(body="만료된원본")], now=before
    )
    assert outcome.exit_code == 0, outcome
    with Ledger(root) as ledger:
        store = ledger.life_store()
        event = store.get(receipts[0]["event_id"], scopes=("principal:owner",), now=before)
        digest = event.raw_digest
        store.connection.execute("DELETE FROM source_item WHERE content_hash=?", (digest,))
        store.connection.commit()
    result, state = run_life_maintenance(
        config, source_ids=("test-notes",), scopes=("principal:owner",), now=NOW
    )
    assert result.exit_code == 0, result
    assert state["expired_events"] == 1
    assert json_int(state["physical_erasure_tombstoned"]) >= 1
    assert state["physical_erasure_retained_shared"] == 0
    assert state["shared_raw_physically_erased"] is False
    with Ledger(root) as ledger:
        store = ledger.life_store()
        assert store.cas.is_tombstoned(digest)
        assert (root / "raw" / digest[:2] / digest).is_file()
