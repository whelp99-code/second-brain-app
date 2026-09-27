"""Real generation/CAS/ledger/Vault/search integration, synthetic source records."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from sb.config import Config
from sb.life_config import parse_settings
from sb.life_contracts import LifeError, digest, stable_event_id
from sb.life_store import read_life_store
from sb.pipeline import run_life_operation
from sb.runtime_access import read_root
from sb.search import SearchIndex
from tests.test_generation_runtime import _config
from tests.test_life_contracts import NOW, payload, settings_raw


def life_config(tmp_path):
    base, root = _config(tmp_path)
    config = replace(base, raw={**base.raw, **settings_raw()})
    return config, root, parse_settings(config.raw).owner()


def send(config, principal, event=None, key="capture-1"):
    return run_life_operation(
        config,
        "capture",
        {"idempotency_key": key, "events": [event or payload(body="Alpha contract context")]},
        principal,
        now=NOW,
    )


def search(config, term):
    with read_root(config) as root:
        return SearchIndex(root, registry_path=root.parent / "absent-registry.sqlite").search(
            term, scope="active"
        )


def test_capture_is_durable_but_not_falsely_searchable(tmp_path):
    config, root, principal = life_config(tmp_path)
    result = send(config, principal)
    assert root.is_symlink() and result["receipt_id"]
    with read_root(config) as pinned, read_life_store(pinned) as store:
        receipt = store.receipt(
            result["receipt_id"], principal, parse_settings(config.raw).policies
        )
        event = store.events(principal, parse_settings(config.raw).policies)[0]
        assert receipt["events"][0]["state"] == "accepted"
        assert (pinned / "raw" / event.raw_hash[:2] / event.raw_hash).is_file()
        assert not (pinned / "wiki" / f"life-{event.event_id}.md").exists()
    assert not search(config, "Alpha")


def test_real_publish_then_correction_changes_search_and_records(tmp_path):
    config, root, principal = life_config(tmp_path)
    first = send(config, principal)
    processed = run_life_operation(config, "run", {}, principal, now=NOW)
    assert processed["processed"] == 1
    hits = search(config, "Alpha")
    assert hits and hits[0].page_id.startswith("wiki/life-")
    event_id = stable_event_id("phone", "capture:1")
    old_generation = root.resolve()
    changed = run_life_operation(
        config,
        "correct",
        {
            "idempotency_key": "correct-1",
            "event_id": event_id,
            "expected_revision": 1,
            "reason": "user clarification",
            "changes": {"body": "Omega confirmed context", "event_status": "occurred"},
        },
        principal,
        now=NOW + timedelta(hours=1),
    )
    assert changed["receipt_id"] != first["receipt_id"] and root.resolve() != old_generation
    assert not search(config, "Alpha")
    assert search(config, "Omega")
    with read_root(config) as pinned, read_life_store(pinned) as store:
        event = store.current(event_id)
        assert event.revision == 2 and event.event_status == "occurred"
        assert len(store.history(event_id)) == 2
        assert (
            store.connection.execute(
                "SELECT count(*) FROM life_evidence_links WHERE revision=2"
            ).fetchone()[0]
            > 0
        )


def test_delete_blocks_current_search_and_reingress(tmp_path):
    config, root, principal = life_config(tmp_path)
    send(config, principal)
    run_life_operation(config, "run", {}, principal, now=NOW)
    event_id = stable_event_id("phone", "capture:1")
    deleted = run_life_operation(
        config,
        "forget",
        {
            "idempotency_key": "forget-1",
            "event_id": event_id,
            "expected_revision": 1,
            "reason": "owner request",
        },
        principal,
        now=NOW,
    )
    assert deleted["raw_deletion"] == "logically_blocked_not_physical_purge"
    assert not search(config, "Alpha")
    generation = root.resolve()
    with pytest.raises(LifeError):
        send(config, principal, key="reingress")
    assert root.resolve() == generation
    with (
        read_root(config) as pinned,
        read_life_store(pinned) as store,
        pytest.raises(LifeError, match="LIFE_EVENT_NOT_FOUND"),
    ):
        store.current(event_id)


def test_failed_batch_never_activates_partial_generation(tmp_path):
    config, root, principal = life_config(tmp_path)
    send(config, principal)
    generation = root.resolve()
    with pytest.raises(LifeError):
        run_life_operation(
            config,
            "capture",
            {
                "idempotency_key": "invalid-batch",
                "events": [payload(source_item_id="new-item"), payload(source_id="forbidden")],
            },
            principal,
            now=NOW,
        )
    assert root.resolve() == generation
    with read_root(config) as pinned, read_life_store(pinned) as store:
        assert len(store.events(principal, parse_settings(config.raw).policies)) == 1


def test_replay_survives_new_generation(tmp_path):
    config, _root, principal = life_config(tmp_path)
    a = send(config, principal)
    run_life_operation(config, "run", {}, principal, now=NOW)
    b = send(config, principal)
    assert a["receipt_id"] == b["receipt_id"] and b["replayed"]
    with read_root(config) as pinned, read_life_store(pinned) as store:
        assert len(store.events(principal, parse_settings(config.raw).policies)) == 1


def test_invalid_revision_does_not_activate_new_snapshot(tmp_path):
    config, root, principal = life_config(tmp_path)
    send(config, principal)
    generation = root.resolve()
    with pytest.raises(LifeError, match="LIFE_REVISION_CONFLICT"):
        run_life_operation(
            config,
            "correct",
            {
                "idempotency_key": "bad-correction",
                "event_id": stable_event_id("phone", "capture:1"),
                "expected_revision": 9,
                "reason": "invalid revision",
                "changes": {"body": "unexpected"},
            },
            principal,
            now=NOW,
        )
    assert root.resolve() == generation


def test_mutable_root_is_explicitly_rejected_without_side_effects(tmp_path):
    from sb.vault import init_vault

    root = tmp_path / "mutable"
    init_vault(root)
    config = Config(raw={"vault_root": str(root), **settings_raw()})
    principal = parse_settings(config.raw).owner()
    before = {
        str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    with pytest.raises(LifeError, match="LIFE_MANAGED_GENERATION_REQUIRED"):
        send(config, principal)
    after = {
        str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert before == after


def test_feature_default_off_preserves_original_vault(tmp_path):
    config, root = _config(tmp_path)
    principal = parse_settings(settings_raw()).owner()
    before = root.resolve()
    with pytest.raises(LifeError, match="LIFE_FEATURE_DISABLED"):
        send(config, principal)
    assert root.resolve() == before and not root.is_symlink()
