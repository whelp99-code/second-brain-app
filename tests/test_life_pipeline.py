"""SB2: actual Vault/ledger/index integration, no model or writer mocks."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sb.config import Config
from sb.effect_values import JsonObject, JsonValue
from sb.life_contracts import LifeInputError
from sb.life_views import obsidian_manifest, timeline
from sb.pipeline import run_life_batch
from sb.search import SearchIndex
from sb.store.life import read_life_store
from sb.vault import init_vault
from tests.life_test_support import json_text
from tests.test_life_contracts import NOW, payload


def life_config(tmp_path: Path) -> tuple[Config, Path]:
    root = tmp_path / "vault"
    _ = init_vault(root)
    return Config(
        raw={
            "vault_root": str(root),
            "source_access": {
                "test-notes": {
                    "owner": "principal:owner",
                    "projects": [],
                    "policy_revision": "test-v1",
                }
            },
            "life": {
                "life_events": True,
                "life_timeline": True,
                "obsidian_view": True,
                "life_briefing": True,
                "sources": {
                    "test-notes": {
                        "enabled": True,
                        "allowed_types": ["note_saved", "calendar_event"],
                    }
                },
            },
        }
    ), root


def item(**changes: JsonValue) -> JsonObject:
    return {"idempotency_key": "request-1", "payload": payload(**changes)}


def test_capture_to_vault_search_and_obsidian(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    outcome, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert outcome.status == "ok", outcome
    assert len(receipts) == 1
    event_id = json_text(receipts[0]["event_id"])
    assert (root / "wiki" / ("life-event-" + event_id + ".md")).is_file()
    hits = SearchIndex(root).search("실제 메모", 10)
    assert any(event_id in hit.page_id for hit in hits)
    with read_life_store(root) as store:
        events = store.events(scopes=("principal:owner",), now=NOW)
        assert len(events) == 1
        assert timeline(events, "2026-09-26", "Asia/Seoul")["events"][0]["event_id"] == event_id
        view = obsidian_manifest(events, day="2026-09-26", timezone="Asia/Seoul")
        assert any(f["path"] == f"Auto/Events/{event_id}.md" for f in view["files"])
        assert store.evidence(event_id, scopes=("principal:owner",), now=NOW)


def test_replay_and_revision_republish_actual_search(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    first, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert first.exit_code == 0, first
    repeat, replay = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert repeat.exit_code == 0, repeat
    assert replay[0]["replayed"] and replay[0]["receipt_id"] == receipts[0]["receipt_id"]
    request = {
        "idempotency_key": "revision-2",
        "expected_revision": 1,
        "payload": payload(source_version="v2", body="교정된 새로운 내용"),
    }
    corrected, rows = run_life_batch(
        config, "test-notes", [request], now=NOW + timedelta(minutes=1)
    )
    assert corrected.exit_code == 0, corrected
    assert rows[0]["revision"] == 2
    assert SearchIndex(root).search("교정된 새로운 내용", 10)
    assert not SearchIndex(root).search("실제 메모", 10)


def test_feature_off_leaves_existing_vault_unchanged(tmp_path: Path) -> None:
    config, root = life_config(tmp_path)
    off = replace(config, raw={**config.raw, "life": {}})
    with pytest.raises(LifeInputError, match="DISABLED"):
        _ = run_life_batch(off, "test-notes", [item()], now=NOW)
    assert not list((root / "wiki").glob("life-event-*.md"))


def test_client_cannot_invent_scope_in_payload(tmp_path: Path) -> None:
    config, _ = life_config(tmp_path)
    with pytest.raises(LifeInputError):
        _ = run_life_batch(config, "test-notes", [item(scopes=["foreign"])], now=NOW)


def test_large_multibyte_note_preserves_raw_and_bounds_each_record(tmp_path: Path) -> None:
    from sb.memory_records import parse_page_records

    config, root = life_config(tmp_path)
    body = "긴 원본 한글 기록 " * 3000
    outcome, receipts = run_life_batch(config, "test-notes", [item(body=body)], now=NOW)
    assert outcome.exit_code == 0, outcome
    identity = json_text(receipts[0]["event_id"])
    path = root / "wiki" / ("life-event-" + identity + ".md")
    records = parse_page_records(path.read_bytes(), "wiki/life-event-" + identity)
    assert records and all(len(r.record_text.encode()) <= 4096 for r in records)
    with read_life_store(root) as store:
        assert body in store.get(identity, scopes=("principal:owner",), now=NOW).body


def test_unsupported_source_and_atomic_batch_validation(tmp_path: Path) -> None:
    config, _ = life_config(tmp_path)
    with pytest.raises(LifeInputError, match="NOT_ALLOWED"):
        _ = run_life_batch(config, "missing", [item()], now=NOW)
    with pytest.raises(LifeInputError):
        _ = run_life_batch(config, "test-notes", [item(), {"payload": {}}], now=NOW)


def test_managed_generation_preserves_events_and_corrected_search(tmp_path: Path) -> None:
    from sb.pipeline import run_life_forget
    from sb.runtime_access import read_root
    from tests.test_generation_runtime import generation_config

    base, active = generation_config(tmp_path / "managed")
    source, _ = life_config(tmp_path / "config-only")
    config = replace(
        base,
        raw={**base.raw, "life": source.raw["life"], "source_access": source.raw["source_access"]},
    )
    first, receipts = run_life_batch(config, "test-notes", [item()], now=NOW)
    assert first.exit_code == 0, first
    assert active.is_symlink()
    original_generation = active.resolve()
    identity = json_text(receipts[0]["event_id"])
    with read_root(config) as root, read_life_store(root) as store:
        assert len(store.events(scopes=("principal:owner",), now=NOW)) == 1
        assert SearchIndex(root).search("실제 메모", 10)
    corrected, _ = run_life_batch(
        config,
        "test-notes",
        [
            {
                "idempotency_key": "correct",
                "expected_revision": 1,
                "payload": payload(source_version="v2", body="관리형 정정 내용"),
            }
        ],
        now=NOW + timedelta(minutes=1),
    )
    assert corrected.exit_code == 0, corrected
    assert active.resolve() != original_generation
    with read_root(config) as root, read_life_store(root) as store:
        assert store.get(identity, scopes=("principal:owner",), now=NOW).revision == 2
        assert SearchIndex(root).search("관리형 정정 내용", 10)
        assert not SearchIndex(root).search("실제 메모", 10)
    withdrawn = run_life_forget(config, "test-notes", identity, 2, now=NOW)
    assert withdrawn.exit_code == 0, withdrawn
    with read_root(config) as root, read_life_store(root) as store:
        assert not store.events(scopes=("principal:owner",), now=NOW)
        assert not SearchIndex(root).search("관리형 정정 내용", 10)
