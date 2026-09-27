"""Real explicit imports, source cursor safety, CLI and conservative restore gates."""

from __future__ import annotations

import json

import pytest

from sb.cli import main
from sb.connectors.records_life import LifeExportAdapter, calendar_events, parse_export
from sb.life_config import parse_settings
from sb.life_contracts import LifeError, canonical, digest, stable_event_id
from sb.life_restore_guard import contains_life_state
from sb.life_store import read_life_store
from sb.ops import OperationError, restore_backup
from sb.pipeline import run_life_operation
from sb.runtime_access import read_root
from tests.test_life_contracts import NOW, payload
from tests.test_life_pipeline import life_config, send

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:meeting-1
DTSTART;TZID=Asia/Seoul:20260926T100000
DTEND;TZID=Asia/Seoul:20260926T110000
DTSTAMP:20260925T010000Z
SUMMARY:고객 미팅
DESCRIPTION:확인할 안건
END:VEVENT
END:VCALENDAR
"""


def test_calendar_plan_cancellation_and_stable_occurrence():
    planned = calendar_events(ICS, "phone", "Asia/Seoul")[0]
    cancelled = calendar_events(
        ICS.replace("SUMMARY:", "STATUS:CANCELLED\nSUMMARY:"), "phone", "Asia/Seoul"
    )[0]
    assert planned["event_status"] == "planned" and cancelled["event_status"] == "cancelled"
    assert planned["source_item_id"] == cancelled["source_item_id"]
    assert planned["source_version"] != cancelled["source_version"]
    assert planned["occurred_start"] == "2026-09-26T01:00:00.000000Z"
    recurrence = ICS.replace(
        "UID:meeting-1", "UID:meeting-1\nRECURRENCE-ID;TZID=Asia/Seoul:20260925T100000"
    )
    assert (
        calendar_events(recurrence, "phone", "Asia/Seoul")[0]["source_item_id"]
        != planned["source_item_id"]
    )


def test_calendar_all_day_and_unfolded_text():
    raw = ICS.replace("DTSTART;TZID=Asia/Seoul:20260926T100000", "DTSTART;VALUE=DATE:20260926")
    raw = raw.replace("DTEND;TZID=Asia/Seoul:20260926T110000", "DTEND;VALUE=DATE:20260927")
    raw = raw.replace("SUMMARY:고객 미팅", "SUMMARY:고객\n 미팅")
    event = calendar_events(raw, "phone", "Asia/Seoul")[0]
    assert event["time_precision"] == "day" and event["title"] == "고객미팅"


@pytest.mark.parametrize("insert", ["RRULE:FREQ=DAILY", "RDATE:20260927T010000Z", "DURATION:PT1H"])
def test_unexpanded_calendar_fails_instead_of_silently_dropping_occurrences(insert):
    with pytest.raises(LifeError, match="LIFE_CALENDAR_EXPANDED_OCCURRENCES_REQUIRED"):
        calendar_events(
            ICS.replace("UID:meeting-1", "UID:meeting-1\n" + insert), "phone", "Asia/Seoul"
        )


def test_unknown_json_fields_and_spoofed_sources_are_rejected():
    with pytest.raises(LifeError):
        parse_export(b'{"schema_version":1,"events":[],"run":"rm"}', "json", "phone", "Asia/Seoul")
    with pytest.raises(LifeError, match="LIFE_SOURCE_MISMATCH"):
        parse_export(
            canonical({"schema_version": 1, "events": [payload(source_id="other")]}).encode(),
            "json",
            "phone",
            "Asia/Seoul",
        )


def test_file_adapter_preserves_raw_and_cursor_detects_same_size_change(tmp_path):
    path = tmp_path / "calendar.ics"
    path.write_text(ICS)
    adapter = LifeExportAdapter(tmp_path, "phone")
    rows = list(adapter.scan(None))
    assert len(rows) == 1 and rows[0][1] == ICS.encode()
    cursor = adapter.next_cursor()
    assert list(adapter.scan(cursor)) == []
    path.write_text(ICS.replace("meeting-1", "meeting-2"))
    rows = list(adapter.scan(cursor))
    assert len(rows) == 1
    assert rows[0][0].source_version != digest(ICS)


def test_adapter_symlink_is_not_ingested(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (source / "escape.json").symlink_to(outside)
    rows = list(LifeExportAdapter(source, "phone").scan(None))
    assert all(not row[1] for row in rows)


def test_import_original_is_preserved_and_capture_receipt_replays(tmp_path):
    config, _, principal = life_config(tmp_path)
    data = {
        "source_id": "phone",
        "source_document_id": "calendar.ics",
        "format": "ics",
        "content": ICS,
    }
    result = run_life_operation(config, "import", data, principal, now=NOW)
    replay = run_life_operation(config, "import", data, principal, now=NOW)
    assert result["receipt_id"] == replay["receipt_id"] and replay["replayed"]
    with read_root(config) as root, read_life_store(root) as store:
        assert (root / "raw" / digest(ICS)[:2] / digest(ICS)).read_bytes() == ICS.encode()
        assert (
            store.connection.execute("SELECT count(*) FROM life_import_evidence").fetchone()[0] == 1
        )
        assert len(store.events(principal, parse_settings(config.raw).policies)) == 1


def test_changed_calendar_requires_explicit_expected_revision(tmp_path):
    config, root, principal = life_config(tmp_path)
    data = {
        "source_id": "phone",
        "source_document_id": "calendar.ics",
        "format": "ics",
        "content": ICS,
    }
    run_life_operation(config, "import", data, principal, now=NOW)
    updated = {**data, "content": ICS.replace("SUMMARY:", "STATUS:CANCELLED\nSUMMARY:")}
    before = root.resolve()
    with pytest.raises(LifeError, match="LIFE_REVISION_CONFLICT"):
        run_life_operation(config, "import", updated, principal, now=NOW)
    assert root.resolve() == before
    event_id = stable_event_id(
        "phone", calendar_events(ICS, "phone", "Asia/Seoul")[0]["source_item_id"]
    )
    result = run_life_operation(
        config, "import", {**updated, "expected_revisions": {event_id: 1}}, principal, now=NOW
    )
    assert result["receipt_id"]
    with read_root(config) as pinned, read_life_store(pinned) as store:
        assert store.current(event_id).event_status == "cancelled"


def test_actual_cli_commands_use_existing_config_and_real_pipeline(tmp_path, monkeypatch, capsys):
    config, _, _ = life_config(tmp_path)
    monkeypatch.setattr("sb.cli.load_config", lambda: config)
    path = tmp_path / "selected.json"
    path.write_text(canonical({"schema_version": 1, "events": [payload()]}))
    assert main(["life", "import", "--input", str(path), "--source", "phone"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["receipt_id"]
    assert main(["life", "run"]) == 0
    assert json.loads(capsys.readouterr().out)["processed"] == 1
    assert main(["life", "timeline", "--day", "2026-09-26"]) == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) == 1
    assert main(["life", "manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["files"]
    assert main(["life", "request"]) == 1
    assert "LIFE_INPUT_FILE_REQUIRED" in capsys.readouterr().err


def test_legacy_restore_cannot_resurrect_life_data_or_replace_existing_vault(tmp_path):
    config, _, principal = life_config(tmp_path)
    send(config, principal)
    archive = tmp_path / "snapshot.tar.gz"
    from sb.runtime_backup import backup_runtime

    backup_runtime(config, archive)
    with read_root(config) as root:
        assert contains_life_state(root)
    destination = tmp_path / "restore-destination"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("preserve")
    with pytest.raises(OperationError, match="LIFE_RESTORE_RECONCILIATION_REQUIRED"):
        restore_backup(archive, destination, force=True)
    assert marker.read_text() == "preserve"
    assert set(destination.iterdir()) == {marker}


def test_life_generation_restore_is_explicitly_blocked_without_reconciliation(tmp_path):
    from sb.generation_runtime import (
        GenerationAuthority,
        GenerationMutation,
        GenerationMutationService,
        GenerationOperation,
    )

    config, root, principal = life_config(tmp_path)
    send(config, principal)
    before = root.resolve()
    called = []
    service = GenerationMutationService.from_config(config)
    try:
        with pytest.raises(Exception, match="LIFE_RESTORE_RECONCILIATION_REQUIRED"):
            service.mutate(
                GenerationMutation(
                    mutation_id="synthetic-restore",
                    operation=GenerationOperation.RESTORE,
                    now=NOW,
                    authority=GenerationAuthority(None, None),
                    apply=lambda _root: called.append(True),
                )
            )
    finally:
        service.close()
    assert not called and root.resolve() == before


def test_original_evidence_endpoint_withholds_shared_restricted_document(tmp_path):
    from sb.life_contracts import LifePrincipal
    from sb.life_http import read_response

    config, _, owner = life_config(tmp_path)
    raw = canonical(
        {
            "schema_version": 1,
            "events": [
                payload(source_item_id="public-part", body="visible"),
                payload(
                    source_item_id="private-part", body="NEVER-SHARE-THIS", sensitivity="restricted"
                ),
            ],
        }
    )
    run_life_operation(
        config,
        "import",
        {
            "source_id": "phone",
            "source_document_id": "RESTRICTED-FILENAME.json",
            "format": "json",
            "content": raw,
        },
        owner,
        now=NOW,
    )
    reader = LifePrincipal("scoped-reader", ("personal",), ("phone",), ("read",), "personal")
    settings = parse_settings(config.raw)
    with read_root(config) as root, read_life_store(root) as store:
        event = store.current(stable_event_id("phone", "public-part"))
        status, evidence = read_response(
            root,
            config,
            settings,
            reader,
            "/api/life/v1/evidence/" + event.evidence_id,
            {"event_id": [event.event_id]},
            NOW,
        )
        assert status == 200
        assert "NEVER-SHARE-THIS" not in canonical(evidence)
        assert "RESTRICTED-FILENAME" not in canonical(evidence)
        assert evidence["original_documents"][0]["available"] is False
        status, owner_evidence = read_response(
            root,
            config,
            settings,
            owner,
            "/api/life/v1/evidence/" + event.evidence_id,
            {"event_id": [event.event_id]},
            NOW,
        )
        assert status == 200 and owner_evidence["original_documents"][0]["raw_text"] == raw
