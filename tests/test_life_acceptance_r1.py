"""R1 cross-surface acceptance. Real CLI subprocess and loopback HTTP only."""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sb.config import load_config
from sb.effect_values import JsonObject, JsonValue
from sb.life_inventory import inventory
from sb.life_restore import capture, materialize, preserve_current
from sb.store.ledger import Ledger
from sb.vault import init_vault
from tests import test_web
from tests.json_fixtures import parse_json, parse_object
from tests.life_test_support import json_int, json_object, json_rows, json_text
from tests.life_test_support import request as _request
from tests.test_life_contracts import NOW

FIXTURES = Path(__file__).parent / "fixtures" / "life-acceptance"
TOKEN = "fixture-admin-token-not-real-0123456789012345"
DEVICE = "fixture-device-token-not-real-0123456789012345"
TYPES = [
    "note_saved",
    "calendar_event",
    "mail_message",
    "call_recording_imported",
]


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    init_vault(root)
    return root


def _config_text(root: Path, sources: tuple[str, ...] = ("test-notes",)) -> str:
    lines = [
        f"vault_root = {json.dumps(str(root))}",
        "[life]",
        "life_events = true",
        "life_timeline = true",
        "obsidian_view = true",
        "life_briefing = true",
        'timezone = "Asia/Seoul"',
        "quiet_start = 0",
        "quiet_end = 0",
    ]
    for name in sources:
        lines.append(f"[life.sources.{name}]")
        lines.append("enabled = true")
        lines.append("allowed_types = " + json.dumps(TYPES))
        lines.append(f"[source_access.{name}]")
        lines.append('owner = "principal:owner"')
        lines.append("projects = []")
        lines.append('policy_revision = "test-v1"')
    lines.append("[web]")
    lines.append(f"token = {json.dumps(TOKEN)}")
    return "\n".join(lines) + "\n"


def _write_config(tmp_path: Path, root: Path, sources: tuple[str, ...] = ("test-notes",)) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(_config_text(root, sources))
    return path


def _cli(cfg: Path, *args: str) -> JsonValue:
    process = subprocess.run(
        [sys.executable, "-m", "sb.cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "SB_CONFIG": str(cfg)},
        timeout=60,
        check=False,
    )
    assert process.returncode == 0, (args, process.stdout, process.stderr)
    if not process.stdout.strip():
        return {}
    return parse_json(process.stdout)


def _object(cfg: Path, *args: str) -> JsonObject:
    return json_object(_cli(cfg, *args))


def _flag(value: JsonValue) -> bool:
    assert isinstance(value, bool)
    return value


def _values(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def _texts(value: JsonValue) -> list[str]:
    return [json_text(item) for item in _values(value)]


def _payload(name: str, **changes: str | float | bool | None | list[dict[str, str]]) -> JsonObject:
    document = parse_object((FIXTURES / name).read_text())
    merged: dict[str, JsonValue] = {**document}
    for key, value in changes.items():
        merged[key] = parse_json(json.dumps(value))
    return merged


def _import_file(cfg: Path, source: str, document: JsonObject, directory: Path) -> JsonObject:
    path = directory / f"{source}-{json_text(document['source_item_id'])}.json"
    path.write_text(json.dumps([document]))
    return _object(
        cfg,
        "life",
        "import",
        "--source",
        source,
        "--format",
        "life-json",
        "--raw-file",
        str(path),
    )


def _receipt_id(body: JsonObject) -> str:
    return json_text(json_rows(body["receipts"])[0]["event_id"])


def _event_ids(root: Path) -> list[str]:
    with Ledger(root) as ledger:
        rows = ledger.life_store().connection.execute(
            "SELECT event_id FROM life_events WHERE deleted=0 ORDER BY event_id"
        )
        return [json_text(row[0]) for row in rows]


def _receipt_states(root: Path) -> list[str]:
    with Ledger(root) as ledger:
        rows = ledger.life_store().connection.execute("SELECT state FROM life_receipts")
        return [json_text(row[0]) for row in rows]


def test_ac01_02_ten_resends_one_event_two_dates_two_events(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root)
    note = _payload("note.json")
    other = _payload("note-other-day.json")
    first = _import_file(cfg, "test-notes", note, tmp_path)
    first_id = _receipt_id(first)
    for _ in range(9):
        replay = _import_file(cfg, "test-notes", note, tmp_path)
        assert _receipt_id(replay) == first_id
    config = load_config(cfg)
    with test_web.running(config) as base:
        body: JsonObject | None = None
        for index in range(10):
            code, body = _request(
                base + "/api/life/v1/events:batch",
                method="POST",
                payload={
                    "source_id": "test-notes",
                    "items": [{"idempotency_key": "ac01-http", "payload": note}],
                },
            )
            assert code == 202, body
            receipt = json_rows(body["receipts"])[0]
            assert json_text(receipt["event_id"]) == first_id
            assert _flag(receipt["replayed"]) is (index > 0)
        assert body is not None
    second = _import_file(cfg, "test-notes", other, tmp_path)
    second_id = _receipt_id(second)
    assert second_id != first_id
    assert _event_ids(root) == sorted([first_id, second_id])
    timeline = _object(cfg, "life", "timeline", "--day", "2026-09-26")
    assert [json_text(row["event_id"]) for row in json_rows(timeline["events"])] == [first_id]
    later = _object(cfg, "life", "timeline", "--day", "2026-09-27")
    assert [json_text(row["event_id"]) for row in json_rows(later["events"])] == [second_id]


def test_ac03_planned_cancel_vs_recording_upload_not_confused(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root, ("test-notes", "test-calendar"))
    calendar = _payload("calendar-planned.json")
    recording = _payload("recording.json")
    imported = _import_file(cfg, "test-calendar", calendar, tmp_path)
    calendar_id = _receipt_id(imported)
    recorded = _import_file(cfg, "test-notes", recording, tmp_path)
    recording_id = _receipt_id(recorded)
    assert calendar_id != recording_id
    config = load_config(cfg)
    with test_web.running(config) as base:
        code, corrected = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": calendar_id,
                "expected_revision": 1,
                "replacement": "예정 취소됨-AC03",
                "reason": "사용자가 취소",
                "idempotency_key": "ac03-cancel",
                "event_status": "cancelled",
            },
        )
        assert code == 202, corrected
        code, timeline = _request(base + "/api/life/v1/timeline?day=2026-09-26")
        assert code == 200, timeline
    by_id = {json_text(row["event_id"]): row for row in json_rows(timeline["events"])}
    assert json_text(by_id[calendar_id]["event_status"]) == "cancelled"
    assert json_text(by_id[calendar_id]["event_type"]) == "calendar_event"
    assert json_text(by_id[recording_id]["event_status"]) == "occurred"
    assert json_text(by_id[recording_id]["event_type"]) == "call_recording_imported"
    assert json_text(by_id[recording_id]["body"]).startswith("녹음업로드-AC03")
    groups = [
        group
        for group in json_rows(timeline["groups"])
        if calendar_id in _texts(group["event_ids"])
    ]
    assert groups and recording_id not in _texts(groups[0]["event_ids"])
    assert len(_event_ids(root)) == 2


def test_ac04_kst_midnight_dst_fold_range_unknown_tz_no_loss_no_double(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root)
    documents = [
        _payload(
            "note.json",
            source_item_id="kst-midnight",
            body="자정포함-AC04",
            occurred_start="2026-09-26T00:00:00+09:00",
        ),
        _payload(
            "note.json",
            source_item_id="kst-next-midnight",
            body="다음자정제외-AC04",
            occurred_start="2026-09-27T00:00:00+09:00",
        ),
        _payload(
            "note.json",
            source_item_id="fold-edt",
            body="접힘EDT-AC04",
            timezone="America/New_York",
            occurred_start="2026-11-01T01:30:00-04:00",
        ),
        _payload(
            "note.json",
            source_item_id="fold-est",
            body="접힘EST-AC04",
            timezone="America/New_York",
            occurred_start="2026-11-01T01:30:00-05:00",
        ),
        _payload(
            "note.json",
            source_item_id="gap-offset",
            body="갭오프셋-AC04",
            timezone="America/New_York",
            occurred_start="2026-03-08T02:30:00-05:00",
        ),
        _payload(
            "note.json",
            source_item_id="range-span",
            body="범위시각-AC04",
            occurred_start="2026-09-26T22:00:00+09:00",
            occurred_end="2026-09-27T02:00:00+09:00",
        ),
        _payload(
            "note.json",
            source_item_id="unknown-time",
            body="시각불명-AC04",
            occurred_start=None,
            time_precision="unknown",
        ),
    ]
    imported = [_import_file(cfg, "test-notes", row, tmp_path) for row in documents]
    identities = {
        json_text(row["source_item_id"]): _receipt_id(result)
        for row, result in zip(documents, imported, strict=True)
    }
    assert len(set(identities.values())) == len(documents)
    day = _object(cfg, "life", "timeline", "--day", "2026-09-26")
    ids = [json_text(row["event_id"]) for row in json_rows(day["events"])]
    assert ids.count(identities["kst-midnight"]) == 1
    assert identities["kst-next-midnight"] not in ids
    assert ids.count(identities["range-span"]) == 1
    assert identities["unknown-time"] not in ids
    undated = [json_text(row["event_id"]) for row in json_rows(day["undated"])]
    assert undated.count(identities["unknown-time"]) == 1
    next_day = _object(cfg, "life", "timeline", "--day", "2026-09-27")
    next_ids = [json_text(row["event_id"]) for row in json_rows(next_day["events"])]
    assert next_ids.count(identities["kst-next-midnight"]) == 1
    assert identities["kst-midnight"] not in next_ids
    assert next_ids.count(identities["range-span"]) == 1
    fold = _object(
        cfg,
        "life",
        "timeline",
        "--day",
        "2026-11-01",
        "--data",
        json.dumps({"timezone": "America/New_York"}),
    )
    fold_rows = {json_text(row["event_id"]): row for row in json_rows(fold["events"])}
    assert json_text(fold_rows[identities["fold-edt"]]["occurred_start"]) == "2026-11-01T05:30:00+00:00"
    assert json_text(fold_rows[identities["fold-est"]]["occurred_start"]) == "2026-11-01T06:30:00+00:00"
    gap = _object(
        cfg,
        "life",
        "timeline",
        "--day",
        "2026-03-08",
        "--data",
        json.dumps({"timezone": "America/New_York"}),
    )
    gap_row = next(
        row for row in json_rows(gap["events"]) if json_text(row["event_id"]) == identities["gap-offset"]
    )
    assert json_text(gap_row["occurred_start"]) == "2026-03-08T07:30:00+00:00"
    config = load_config(cfg)
    with test_web.running(config) as base:
        assert _request(base + "/api/life/v1/timeline?day=2026-09-26&timezone=Not%2FAZone")[0] == 400
        code, evidence = _request(base + "/api/life/v1/evidence/" + identities["unknown-time"])
        assert code == 200 and "시각불명-AC04" in json_text(evidence["content"])
    assert len(_event_ids(root)) == len(documents)


def test_ac05_three_source_group_keeps_three_citations_and_namesake_split(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    sources = ("test-notes", "test-calendar", "test-mail")
    cfg = _write_config(tmp_path, root, sources)
    shared = {"entity_id": "meetings:standup-r1", "kind": "event", "label": "스탠드업"}
    ada = {"entity_id": "people:ada", "kind": "person", "label": "Ada"}
    other = {"entity_id": "people:ada-other", "kind": "person", "label": "Ada"}
    rows = [
        ("test-notes", "note_saved", "note-ac05", [shared, ada]),
        ("test-calendar", "calendar_event", "cal-ac05", [shared, ada]),
        ("test-mail", "mail_message", "mail-ac05", [shared, other]),
    ]
    for source, event_type, item_id, entities in rows:
        _import_file(
            cfg,
            source,
            _payload(
                "note.json",
                source_item_id=item_id,
                event_type=event_type,
                title="세출처-AC05" if event_type != "mail_message" else "동명이인-AC05",
                body=item_id,
                entities=entities,
                event_status="occurred" if event_type != "calendar_event" else "planned",
            ),
            tmp_path,
        )
    timeline = _object(cfg, "life", "timeline", "--day", "2026-09-26")
    grouped = [group for group in json_rows(timeline["groups"]) if len(_texts(group["event_ids"])) == 3]
    assert len(grouped) == 1, timeline["groups"]
    citations = json_rows(grouped[0]["citations"])
    assert {json_text(row["source_item_id"]) for row in citations} == {"note-ac05", "cal-ac05", "mail-ac05"}
    assert {json_text(row["source_id"]) for row in citations} == set(sources)
    assert len(citations) == 3
    config = load_config(cfg)
    with test_web.running(config) as base:
        code, manifest = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200, manifest
    people = [
        row
        for row in json_rows(manifest["files"])
        if json_text(row["path"]).startswith("Auto/People/")
    ]
    assert len(people) >= 2
    namesake = [json_text(row["content"]) for row in people if "동명이인-AC05" in json_text(row["content"])]
    shared_pages = [json_text(row["content"]) for row in people if "세출처-AC05" in json_text(row["content"])]
    assert namesake and shared_pages
    assert all("세출처-AC05" not in page for page in namesake)
    assert all("동명이인-AC05" not in page for page in shared_pages)


def test_ac09_correction_reflected_in_search_timeline_briefing_relations_manifest_same_revision(
    tmp_path: Path,
) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root)
    document = _payload(
        "note.json",
        source_item_id="ac09",
        body="원래본문-AC09",
        title="정정대상-AC09",
        entities=[{"entity_id": "people:ada", "kind": "person", "label": "Ada"}],
    )
    imported = _import_file(cfg, "test-notes", document, tmp_path)
    event_id = _receipt_id(imported)
    _cli(
        cfg,
        "life",
        "relation-put",
        "--data",
        json.dumps(
            {
                "from_id": event_id,
                "to_id": "people:ada",
                "kind": "participated_in",
                "evidence_event_ids": [event_id],
                "idempotency_key": "ac09-rel-1",
            }
        ),
    )
    _cli(cfg, "life", "briefing-generate", "--day", "2026-09-26", "--slot", "morning")
    config = load_config(cfg)
    with test_web.running(config) as base:
        code, corrected = _request(
            base + "/api/life/v1/corrections",
            method="POST",
            payload={
                "event_id": event_id,
                "expected_revision": 1,
                "replacement": "정정반영-AC09",
                "reason": "사용자가 정정",
                "idempotency_key": "ac09-correct",
            },
        )
        assert code == 202, corrected
        code, manifest = _request(base + "/api/life/v1/views/obsidian/manifest?day=2026-09-26")
        assert code == 200, manifest
    timeline = _object(cfg, "life", "timeline", "--day", "2026-09-26")
    first_event = json_rows(timeline["events"])[0]
    revision = json_int(first_event["revision"])
    assert revision == 2
    assert json_text(first_event["body"]).startswith("정정반영-AC09")
    page = next(
        row
        for row in json_rows(manifest["files"])
        if json_text(row["path"]) == f"Auto/Events/{event_id}.md"
    )
    content = json_text(page["content"])
    assert "sb_revision: 2" in content
    assert "정정반영-AC09" in content
    assert "원래본문-AC09" not in content
    stale = _object(cfg, "life", "relations")
    assert all(
        json_int(ref["revision"]) == revision
        for row in json_rows(stale["items"])
        for ref in json_rows(row["evidence"])
    )
    hits = _values(_cli(cfg, "search", "정정반영-AC09", "--json"))
    assert any(event_id in json.dumps(hit) for hit in hits)
    old = _values(_cli(cfg, "search", "원래본문-AC09", "--json"))
    assert old == []
    _cli(cfg, "life", "briefing-generate", "--day", "2026-09-26", "--slot", "morning")
    briefings = _object(cfg, "life", "briefings")
    evidence = [
        ref
        for row in json_rows(briefings["items"])
        for ref in json_rows(json_object(row["body"])["evidence"])
    ]
    assert evidence and {json_int(ref["revision"]) for ref in evidence} == {revision}
    _cli(
        cfg,
        "life",
        "relation-put",
        "--data",
        json.dumps(
            {
                "from_id": event_id,
                "to_id": "people:ada",
                "kind": "participated_in",
                "evidence_event_ids": [event_id],
                "idempotency_key": "ac09-rel-2",
            }
        ),
    )
    current = _object(cfg, "life", "relations")
    assert json_rows(current["items"])
    assert {
        json_int(ref["revision"])
        for row in json_rows(current["items"])
        for ref in json_rows(row["evidence"])
    } == {revision}


def test_ac15_out_of_scope_title_node_edge_leak_zero(tmp_path: Path, monkeypatch) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root, ("src-visible", "src-hidden"))
    visible = _payload("note.json", source_item_id="visible-ac15", title="범위안제목-AC15", body="보임")
    hidden = _payload(
        "note.json",
        source_item_id="hidden-ac15",
        title="범위밖제목-AC15",
        body="숨김본문-AC15",
        entities=[{"entity_id": "people:hidden", "kind": "person", "label": "범위밖노드-AC15"}],
    )
    shown = _import_file(cfg, "src-visible", visible, tmp_path)
    concealed = _import_file(cfg, "src-hidden", hidden, tmp_path)
    hidden_id = _receipt_id(concealed)
    _cli(
        cfg,
        "life",
        "relation-put",
        "--source",
        "src-hidden",
        "--data",
        json.dumps(
            {
                "from_id": hidden_id,
                "to_id": "people:hidden",
                "kind": "participated_in",
                "evidence_event_ids": [hidden_id],
                "idempotency_key": "ac15-edge",
            }
        ),
    )
    monkeypatch.setenv("SB_WEB_TOKEN", TOKEN)
    monkeypatch.setenv("SB_FIXTURE_DEVICE_TOKEN", DEVICE)
    loaded = load_config(cfg)
    config = replace(
        loaded,
        source_path=None,
        raw={
            **loaded.raw,
            "life_devices": {
                "phone-visible": {
                    "token_env": "SB_FIXTURE_DEVICE_TOKEN",
                    "source_ids": ["src-visible"],
                    "can_write": False,
                    "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                    "revoked": False,
                }
            },
        },
    )
    with test_web.running(config) as base:
        surfaces = []
        for path in (
            "/api/life/v1/health",
            "/api/life/v1/timeline?day=2026-09-26",
            "/api/life/v1/views/obsidian/manifest?day=2026-09-26",
            "/api/life/v1/relations",
            "/api/life/v1/briefings?day=2026-09-26&slot=morning",
            "/api/life/v1/events/" + hidden_id,
            "/api/life/v1/evidence/" + hidden_id,
        ):
            surfaces.append(_request(base + path, token=DEVICE))
        assert surfaces[-1][0] in {403, 404}
        assert surfaces[-2][0] in {403, 404}
        rendered = json.dumps([body for _code, body in surfaces], ensure_ascii=False)
        assert "범위안제목-AC15" in rendered
        assert "범위밖제목-AC15" not in rendered
        assert "범위밖노드-AC15" not in rendered
        assert "숨김본문-AC15" not in rendered
        assert hidden_id not in rendered
        assert _receipt_id(shown) in rendered


def _kill(cfg: Path, mode: str, payload: Path) -> None:
    worker = FIXTURES / "crash_boundary.py"
    ready_r, ready_w = os.pipe()
    control_r, control_w = os.pipe()
    process = subprocess.Popen(
        [sys.executable, str(worker), mode, str(cfg), str(payload), str(ready_w), str(control_r)],
        pass_fds=(ready_w, control_r),
    )
    os.close(ready_w)
    os.close(control_r)
    try:
        assert os.read(ready_r, 16) == b"ready\n"
        os.kill(process.pid, signal.SIGKILL)
        assert process.wait(timeout=20) == -signal.SIGKILL
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=20)
        os.close(ready_r)
        os.close(control_w)


def test_ac16_kill_before_receipt_publish_ack_resumes_without_loss_or_false_done(
    tmp_path: Path,
) -> None:
    note = FIXTURES / "note.json"
    receipt_root = _vault(tmp_path / "receipt")
    receipt_cfg = _write_config(tmp_path / "receipt", receipt_root)
    _kill(receipt_cfg, "before_receipt", note)
    assert _event_ids(receipt_root) == []
    assert _receipt_states(receipt_root) == []
    resumed = _import_file(receipt_cfg, "test-notes", parse_object(note.read_text()), tmp_path / "receipt")
    assert len(json_rows(resumed["receipts"])) == 1
    assert _event_ids(receipt_root) == [_receipt_id(resumed)]
    found = _values(_cli(receipt_cfg, "search", "열번재전송-AC01", "--json"))
    assert found

    publish_root = _vault(tmp_path / "publish")
    publish_cfg = _write_config(tmp_path / "publish", publish_root)
    _kill(publish_cfg, "before_publish", note)
    assert len(_event_ids(publish_root)) == 1
    assert _receipt_states(publish_root) == ["accepted"]
    assert not list((publish_root / "wiki").glob("life-event-*.md"))
    replay = _import_file(publish_cfg, "test-notes", parse_object(note.read_text()), tmp_path / "publish")
    assert len(_event_ids(publish_root)) == 1
    assert _receipt_id(replay) == _event_ids(publish_root)[0]
    assert list((publish_root / "wiki").glob("life-event-*.md"))
    assert set(_receipt_states(publish_root)) <= {"published", "searchable"}
    assert _values(_cli(publish_cfg, "search", "열번재전송-AC01", "--json"))

    ack_root = _vault(tmp_path / "ack")
    ack_cfg = _write_config(tmp_path / "ack", ack_root)
    imported = _import_file(ack_cfg, "test-notes", parse_object(note.read_text()), tmp_path / "ack")
    _kill(ack_cfg, "before_ack", note)
    database = sqlite3.connect(ack_root / ".sb" / "ledger.db")
    try:
        assert database.execute(
            "SELECT 1 FROM life_workflow_heads WHERE kind='view_ack'"
        ).fetchone() is None
    finally:
        database.close()
    manifest = _object(ack_cfg, "life", "manifest", "--day", "2026-09-26")
    ack_payload = json.dumps(
        {"generation": manifest["generation"], "day": "2026-09-26", "timezone": "Asia/Seoul"}
    )
    acked = _object(ack_cfg, "life", "view-ack", "--data", ack_payload)
    assert _flag(json_object(acked["body"])["applied"]) is True
    again = _object(ack_cfg, "life", "view-ack", "--data", ack_payload)
    assert json_text(again["object_id"]) == json_text(acked["object_id"])
    database = sqlite3.connect(ack_root / ".sb" / "ledger.db")
    try:
        assert database.execute(
            "SELECT COUNT(*) FROM life_workflow_heads WHERE kind='view_ack'"
        ).fetchone() == (1,)
    finally:
        database.close()
    assert _event_ids(ack_root) == [_receipt_id(imported)]


def test_ac18_21_delete_then_old_backup_restore_and_offline_client_reconnect_no_resurrection_pending_reported(
    tmp_path: Path, monkeypatch
) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root)
    document = _payload("note.json", source_item_id="ac18", body="삭제대상-AC18", title="삭제제목-AC18")
    imported = _import_file(cfg, "test-notes", document, tmp_path)
    event_id = _receipt_id(imported)
    _cli(cfg, "life", "briefing-generate", "--day", "2026-09-26", "--slot", "morning")
    old = capture(root)
    config = load_config(cfg)
    with test_web.running(config) as base:
        code, removed = _request(
            base + "/api/life/v1/withdrawals",
            method="POST",
            payload={"source_id": "test-notes", "event_id": event_id, "expected_revision": 1},
        )
        assert code == 202, removed
        assert _flag(removed["offline_copies_recalled"]) is False
        assert _flag(removed["physical_raw_erasure"]) is False
    with Ledger(root) as ledger:
        rows = inventory(ledger.life_store(), event_id, root=root)
    assert any(row["status"] == "pending" for row in rows)
    assert all(row["status"] in {"withdrawn", "pending"} for row in rows)
    candidate = tmp_path / "old-backup"
    candidate.mkdir()
    materialize(old, candidate, old_archive_has_life=True)
    preserve_current(root, candidate)
    with Ledger(candidate) as ledger:
        store = ledger.life_store()
        assert store.connection.execute(
            "SELECT deleted FROM life_events WHERE event_id=?", (event_id,)
        ).fetchone() == (1,)
        assert store.tombstones(scopes=("principal:owner",))
        assert store.events(scopes=("principal:owner",), now=NOW) == ()
    assert not (candidate / "wiki" / f"life-event-{event_id}.md").exists()
    monkeypatch.setenv("SB_WEB_TOKEN", TOKEN)
    monkeypatch.setenv("SB_FIXTURE_DEVICE_TOKEN", DEVICE)
    loaded = load_config(cfg)
    offline = replace(
        loaded,
        source_path=None,
        raw={
            **loaded.raw,
            "life_devices": {
                "phone-offline": {
                    "token_env": "SB_FIXTURE_DEVICE_TOKEN",
                    "source_ids": ["test-notes"],
                    "can_write": True,
                    "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                    "revoked": False,
                }
            },
        },
    )
    with test_web.running(offline) as base:
        code, replay = _request(
            base + "/api/life/v1/events:batch",
            method="POST",
            token=DEVICE,
            payload={
                "source_id": "test-notes",
                "items": [{"idempotency_key": "offline-resend", "payload": document}],
            },
        )
        assert code == 409 and json_text(replay["error"]) == "LIFE_EVENT_DELETED"
        code, timeline = _request(base + "/api/life/v1/timeline?day=2026-09-26", token=DEVICE)
        assert code == 200 and json_rows(timeline["events"]) == []
        assert _request(base + "/api/life/v1/evidence/" + event_id, token=DEVICE)[0] == 404
    assert _event_ids(root) == []


def test_device_token_expiry_and_revocation_blocks_every_surface(tmp_path: Path, monkeypatch) -> None:
    root = _vault(tmp_path)
    cfg = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_WEB_TOKEN", TOKEN)
    monkeypatch.setenv("SB_FIXTURE_DEVICE_TOKEN", DEVICE)
    reads = (
        "/api/life/v1/health",
        "/api/life/v1/timeline?day=2026-09-26",
        "/api/life/v1/views/obsidian/manifest?day=2026-09-26",
        "/api/life/v1/relations",
        "/api/life/v1/briefings?day=2026-09-26",
        "/api/life/v1/questions",
        "/api/life/v1/events/missing",
        "/api/life/v1/evidence/missing",
        "/api/life/v1/evidence-links/missing",
        "/api/life/v1/receipts/missing",
        "/api/search?q=secret",
        "/api/run",
    )
    posts = (
        "/api/life/v1/events:batch",
        "/api/life/v1/corrections",
        "/api/life/v1/withdrawals",
        "/api/run",
        "/api/remember",
    )
    for revoked, expires in ((False, NOW - timedelta(days=1)), (True, NOW + timedelta(days=30))):
        loaded = load_config(cfg)
        config = replace(
            loaded,
            source_path=None,
            raw={
                **loaded.raw,
                "life_devices": {
                    "phone-fixture": {
                        "token_env": "SB_FIXTURE_DEVICE_TOKEN",
                        "source_ids": ["test-notes"],
                        "can_write": True,
                        "expires_at": expires.isoformat(),
                        "revoked": revoked,
                    }
                },
            },
        )
        with test_web.running(config) as base:
            for path in reads:
                code, body = _request(base + path, token=DEVICE)
                assert code == 401, (path, code, body)
            for path in posts:
                code, body = _request(base + path, method="POST", token=DEVICE, payload={})
                assert code == 401, (path, code, body)
            code, body = _request(base + "/api/life/v1/health", token=TOKEN)
            assert code == 200, body
