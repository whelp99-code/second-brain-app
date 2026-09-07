"""GJC/Orca/project record adapters: fixtures, unique ids, and cursor resume."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "second-brain"

from sb.connectors import discover_adapters
from sb.connectors.base import ItemMeta
from sb.connectors.records_orca import ADAPTER_ID as ORCA_ID
from sb.connectors.records_orca import create as create_orca
from sb.connectors.records_project import ADAPTER_ID as PROJECT_ID
from sb.connectors.records_project import create as create_project
from sb.connectors.sessions_gjc import ADAPTER_ID as GJC_ID
from sb.connectors.sessions_gjc import create as create_gjc
from sb.contracts import SourceRef

SPIKE = Path(__file__).resolve().parent / "fixtures" / "wiki-spike"


@dataclass(frozen=True, slots=True)
class _Cfg:
    source_roots: list[dict[str, str]]


def _cfg(adapter_id: str, root: Path, source_id: str) -> _Cfg:
    return _Cfg([{"id": source_id, "adapter": adapter_id, "root": str(root)}])


def _copy_spike(tmp: Path, family: str, name: str) -> Path:
    dest = tmp / family / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    _ = dest.write_bytes((FIXTURES / family / name).read_bytes())
    return dest


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[bytes]:
    return [body for _ref, body, meta in items if "skip_reason" not in meta]


def _texts(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [body.decode() for body in _delivered(items)]


def _skipped(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [str(meta.get("skip_reason")) for _r, _b, meta in items if "skip_reason" in meta]


def _uris(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [ref.source_uri for ref, _b, meta in items if "skip_reason" not in meta]


def test_gjc_scan_yields_unique_ids_and_visible_text_when_golden_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format GJC golden JSONL fixture.
    root = tmp_path / "gjc"
    _ = _copy_spike(root, "gjc", "golden.jsonl")
    adapter = create_gjc(_cfg(GJC_ID, root, "gjc"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: unique SourceRef ids carry the visible conversation/tool/artifact text.
    blob = b"\n".join(_delivered(items))
    uris = _uris(items)
    assert items
    assert all(ref.source_id == "gjc" for ref, _b, _m in items)
    assert len(uris) == len(set(uris))
    assert all("#" in uri for uri in uris)
    assert b"VISIBLE_USER_1" in blob
    assert b"VISIBLE_ASSISTANT_1" in blob
    assert b"VISIBLE_TOOL_RESULT_1" in blob
    assert b"VISIBLE_ARTIFACT_1" in blob


def test_orca_scan_yields_unique_ids_and_visible_text_when_golden_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format Orca golden JSONL fixture.
    root = tmp_path / "orca"
    _ = _copy_spike(root, "orca", "golden.jsonl")
    adapter = create_orca(_cfg(ORCA_ID, root, "orca"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: unique SourceRef ids carry the visible comment/terminal/artifact text.
    blob = b"\n".join(_delivered(items))
    uris = _uris(items)
    assert all(ref.source_id == "orca" for ref, _b, _m in items)
    assert len(uris) == len(set(uris))
    assert all("#" in uri for uri in uris)
    assert b"VISIBLE_COMMENT_1" in blob
    assert b"VISIBLE_TERMINAL_1" in blob
    assert b"VISIBLE_ARTIFACT_1" in blob


def test_project_scan_yields_unique_ids_and_visible_text_when_golden_fixture(
    tmp_path: Path,
) -> None:
    # Given: a copied real-format project/JARVIS golden JSONL fixture.
    root = tmp_path / "project-records"
    _ = _copy_spike(root, "project-records", "golden.jsonl")
    adapter = create_project(_cfg(PROJECT_ID, root, "project"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: unique SourceRef ids carry the visible operational and tower text.
    blob = b"\n".join(_delivered(items))
    uris = _uris(items)
    assert all(ref.source_id == "project" for ref, _b, _m in items)
    assert len(uris) == len(set(uris))
    assert all("#" in uri for uri in uris)
    assert b"VISIBLE_STATUS_1" in blob
    assert b"VISIBLE_DECISION_1" in blob
    assert b"VISIBLE_TOWER_1" in blob


def test_jsonl_byte_offset_resume_yields_zero_when_record_fixtures_unchanged(
    tmp_path: Path,
) -> None:
    # Given: scanned GJC/Orca/project fixtures with captured cursors.
    gjc_root = tmp_path / "gjc"
    orca_root = tmp_path / "orca"
    project_root = tmp_path / "project-records"
    _ = _copy_spike(gjc_root, "gjc", "golden.jsonl")
    _ = _copy_spike(orca_root, "orca", "golden.jsonl")
    _ = _copy_spike(project_root, "project-records", "golden.jsonl")
    gjc = create_gjc(_cfg(GJC_ID, gjc_root, "gjc"))
    orca = create_orca(_cfg(ORCA_ID, orca_root, "orca"))
    project = create_project(_cfg(PROJECT_ID, project_root, "project"))
    assert _delivered(list(gjc.scan(None)))
    assert _delivered(list(orca.scan(None)))
    assert _delivered(list(project.scan(None)))
    gjc_cursor, orca_cursor, project_cursor = (
        gjc.next_cursor(),
        orca.next_cursor(),
        project.next_cursor(),
    )

    # When: each adapter rescans with the exact byte-offset cursor.
    gjc_resume = list(gjc.scan(gjc_cursor))
    orca_resume = list(orca.scan(orca_cursor))
    project_resume = list(project.scan(project_cursor))

    # Then: unchanged fixtures yield zero items and the cursor is stable.
    assert gjc_resume == []
    assert orca_resume == []
    assert project_resume == []
    assert gjc.next_cursor() == gjc_cursor
    assert orca.next_cursor() == orca_cursor
    assert project.next_cursor() == project_cursor


def test_gjc_and_orca_omit_forbidden_markers_when_secrets_fixture(tmp_path: Path) -> None:
    # Given: sanitized GJC and Orca exports that also contain denied records.
    gjc_root = tmp_path / "gjc"
    orca_root = tmp_path / "orca"
    _ = _copy_spike(gjc_root, "gjc", "secrets.jsonl")
    _ = _copy_spike(orca_root, "orca", "secrets.jsonl")
    gjc = create_gjc(_cfg(GJC_ID, gjc_root, "gjc"))
    orca = create_orca(_cfg(ORCA_ID, orca_root, "orca"))

    # When: both adapters scan the secret-bearing fixtures.
    gjc_blob = "\n".join(_texts(list(gjc.scan(None))))
    orca_blob = "\n".join(_texts(list(orca.scan(None))))

    # Then: only visible text is delivered and forbidden markers do not persist.
    assert "VISIBLE_USER_S" in gjc_blob
    assert "VISIBLE_COMMENT_S" in orca_blob
    for marker in (
        "FORBIDDEN_REASONING",
        "FORBIDDEN_AUTH",
        "FORBIDDEN_PROVIDER",
        "FORBIDDEN_CREDENTIAL",
        "FORBIDDEN_BROWSER",
        "FORBIDDEN_TERMINAL_CONTROL",
        "FORBIDDEN_API_KEY",
    ):
        assert marker not in gjc_blob
        assert marker not in orca_blob


def test_project_quarantines_unknown_schema_while_sibling_record_ingests(tmp_path: Path) -> None:
    # Given: a project export with one unknown schema beside a valid sibling record.
    root = tmp_path / "project-records"
    _ = _copy_spike(root, "project-records", "unknown-schema.jsonl")
    adapter = create_project(_cfg(PROJECT_ID, root, "project"))

    # When: the adapter scans the mixed export.
    items = list(adapter.scan(None))

    # Then: the unknown schema is quarantined and the sibling still ingests.
    assert "VISIBLE_STATUS_OK" in _texts(items)
    assert "FORBIDDEN_UNKNOWN_SCHEMA" not in _texts(items)
    assert "unknown-schema" in _skipped(items)


def test_unsupported_export_version_is_quarantined_without_visible_items(tmp_path: Path) -> None:
    # Given: GJC/Orca/project fixtures whose export_version is not supported.
    gjc_root = tmp_path / "gjc"
    orca_root = tmp_path / "orca"
    project_root = tmp_path / "project-records"
    _ = _copy_spike(gjc_root, "gjc", "unsupported.jsonl")
    _ = _copy_spike(orca_root, "orca", "unsupported.jsonl")
    _ = _copy_spike(project_root, "project-records", "unsupported.jsonl")
    adapters = (
        create_gjc(_cfg(GJC_ID, gjc_root, "gjc")),
        create_orca(_cfg(ORCA_ID, orca_root, "orca")),
        create_project(_cfg(PROJECT_ID, project_root, "project")),
    )

    # When: each adapter scans the unsupported export.
    scans = [list(adapter.scan(None)) for adapter in adapters]

    # Then: the file is quarantined and no visible payload is delivered.
    for items in scans:
        assert "unsupported-version" in _skipped(items)
        assert _delivered(items) == []


def test_absent_root_is_skipped_without_raise(tmp_path: Path) -> None:
    # Given: configured roots that do not exist.
    missing = tmp_path / "no-such-records-root"
    adapters = (
        create_gjc(_cfg(GJC_ID, missing, "gjc")),
        create_orca(_cfg(ORCA_ID, missing, "orca")),
        create_project(_cfg(PROJECT_ID, missing, "project")),
    )

    # When: each adapter scans the absent root.
    scans = [list(adapter.scan(None)) for adapter in adapters]

    # Then: no raise; each scan reports a typed skip.
    for items in scans:
        assert "absent-root" in _skipped(items)
        assert _delivered(items) == []


def test_malformed_jsonl_line_is_quarantined_and_scan_continues(tmp_path: Path) -> None:
    # Given: a GJC export with a valid header, a corrupt line, and a later visible record.
    root = tmp_path / "gjc"
    path = root / "mixed.jsonl"
    path.parent.mkdir()
    header = json.dumps(
        {"type": "export_meta", "export_version": "gjc-public-session-v1", "source_profile": "GJC"},
        separators=(",", ":"),
        sort_keys=True,
    )
    session = json.dumps({"type": "session_meta", "session_id": "sess-mix"}, separators=(",", ":"))
    message = json.dumps(
        {
            "type": "conversation",
            "id": "msg-ok",
            "parent_id": None,
            "role": "user",
            "text": "AFTER_CORRUPT",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    _ = path.write_text(
        header + "\n" + session + "\n{not-json\n" + message + "\n", encoding="utf-8"
    )
    adapter = create_gjc(_cfg(GJC_ID, root, "gjc"))

    # When: the adapter scans the mixed file.
    items = list(adapter.scan(None))

    # Then: the bad line is quarantined and the later valid record is still ingested.
    assert "AFTER_CORRUPT" in _texts(items)
    assert "malformed-json" in _skipped(items)


def test_registry_auto_discovers_gjc_orca_and_project_adapters() -> None:
    # Given: the real sb.connectors package after the record modules exist.
    from sb.config import load_config

    # When: adapters are discovered.
    registry = discover_adapters(load_config())

    # Then: each record adapter is registered under its unique ADAPTER_ID.
    for adapter_id in (GJC_ID, ORCA_ID, PROJECT_ID):
        assert adapter_id in registry
        assert registry[adapter_id].source_id
        assert adapter_id not in {key for key in registry if key != adapter_id}
