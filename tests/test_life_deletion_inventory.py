"""Forget withdraws every managed copy or reports it still pending."""

from sb.life_inventory import COPY_KINDS, inventory
from sb.pipeline import run_life_batch, run_life_forget
from sb.store.ledger import Ledger
from sb.store.life_journal import LifeJournal
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import item, life_config

SCOPES = ("principal:owner",)


def test_inventory_lists_every_copy_kind_for_event(tmp_path):
    config, root = life_config(tmp_path)
    outcome, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert outcome.exit_code == 0, outcome
    event_id = receipts[0]["event_id"]
    with Ledger(root) as ledger:
        store = ledger.life_store()
        event = store.get(event_id, scopes=SCOPES, now=NOW)
        journal = LifeJournal(store)
        journal.put(
            "briefing",
            "briefing:test",
            {"slot": "morning"},
            events=(event,),
            now=NOW,
        )
        journal.put(
            "delivery",
            "delivery:test",
            {"state": "prepared"},
            events=(event,),
            now=NOW,
        )
        rows = inventory(store, event_id, root=root)
    assert [row["kind"] for row in rows] == list(COPY_KINDS)
    assert {row["status"] for row in rows} <= {"live", "withdrawn", "pending"}
    by_kind = {row["kind"]: row["status"] for row in rows}
    assert by_kind["wiki_page"] == "live"
    assert by_kind["revision"] == "live"
    assert by_kind["briefing_snapshot"] == "live"
    assert by_kind["delivery_notification"] == "live"


def test_forget_withdraws_or_marks_pending_each_copy(tmp_path):
    config, root = life_config(tmp_path)
    _, receipts = run_life_batch(config, "test-notes", [item(body="삭제대상기억")], now=NOW)
    event_id = receipts[0]["event_id"]
    with Ledger(root) as ledger:
        store = ledger.life_store()
        event = store.get(event_id, scopes=SCOPES, now=NOW)
        LifeJournal(store).put(
            "briefing", "briefing:test", {"slot": "morning"}, events=(event,), now=NOW
        )
    outcome = run_life_forget(config, "test-notes", event_id, 1, now=NOW)
    assert outcome.exit_code == 0, outcome
    with Ledger(root) as ledger:
        rows = inventory(ledger.life_store(), event_id, root=root)
    assert [row["kind"] for row in rows] == list(COPY_KINDS)
    assert all(row["status"] in {"withdrawn", "pending"} for row in rows)
    by_kind = {row["kind"]: row["status"] for row in rows}
    assert by_kind["wiki_page"] == "withdrawn"
    assert by_kind["revision"] == "withdrawn"
    assert by_kind["briefing_snapshot"] == "pending"
    assert by_kind["cas_raw"] == "pending"
