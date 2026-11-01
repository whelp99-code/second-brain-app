"""Kakao export lines are messages with provisional, replay-stable identity."""

from __future__ import annotations

import json
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef
from sb.life_exports import export_parts
from sb.life_ingest import complete_exports, prepare_exports
from sb.life_json import LifePayload
from sb.store.ledger import Ledger
from tests.test_life_contracts import NOW
from tests.test_life_pipeline import life_config

FIXTURES = Path(__file__).parent / "fixtures" / "life-exports"


class _Always:
    source_id = "test-notes"
    supports_life_events = True
    life_format = "kakao-export"
    life_timezone = "Asia/Seoul"

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        _ = cursor
        digest = sha256(self.raw).hexdigest()
        meta: ItemMeta = {"relative_path": "kakao.txt"}
        yield SourceRef(self.source_id, "kakao.txt", digest), self.raw, meta

    def next_cursor(self) -> str:
        return json.dumps({"kakao.txt": sha256(self.raw).hexdigest()}, separators=(",", ":"))


def _source_item_id(event: LifePayload) -> str:
    value = event["source_item_id"]
    assert isinstance(value, str)
    return value


def test_kakao_lines_become_messages_with_provisional_identity() -> None:
    raw = (FIXTURES / "kakao.txt").read_bytes()
    events, quarantined = export_parts("kakao-export", raw, "kakao.txt")
    digest = sha256(raw).hexdigest()
    assert quarantined == ()
    assert [event["source_item_id"] for event in events] == [
        f"kakao:{digest}:4",
        f"kakao:{digest}:5",
    ]
    assert [event["body"] for event in events] == ["내일 회의", "알겠다"]
    assert all(event["event_type"] == "note_saved" for event in events)


def test_same_export_twice_is_replay_not_duplicate(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    raw = (FIXTURES / "kakao.txt").read_bytes()
    adapter = _Always(raw)
    with Ledger(root) as ledger:
        first = prepare_exports(config, ledger, adapter, run_id="r1", now=NOW, maximum=10)
        complete_exports(ledger, adapter, first, config=config, now=NOW)
        second = prepare_exports(config, ledger, adapter, run_id="r2", now=NOW, maximum=10)
        events = ledger.life_store().events(scopes=("principal:owner",), now=NOW)
    assert first.errors == 0 and len(events) == 2
    assert len(second.events) == 2
    assert all(event.revision == 1 for event in events)
    exported, _quarantined = export_parts("kakao-export", raw, "kakao.txt")
    assert {event.source_item_id for event in events} == {_source_item_id(event) for event in exported}


def test_malformed_line_quarantined_others_accepted(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    raw = (FIXTURES / "kakao-malformed.txt").read_bytes()
    adapter = _Always(raw)
    with Ledger(root) as ledger:
        result = prepare_exports(config, ledger, adapter, run_id="r1", now=NOW, maximum=10)
        complete_exports(ledger, adapter, result, config=config, now=NOW)
        bodies = [
            event.body
            for event in ledger.life_store().events(scopes=("principal:owner",), now=NOW)
        ]
    assert sorted(bodies) == ["다른 정상 메시지", "정상 메시지"]
    assert result.accepted == 2 and result.quarantined == 1
    assert result.received == result.accepted + result.quarantined + result.retrying
    assert result.quarantine["kakao.txt"]["attachment_state"] == "quarantined"
