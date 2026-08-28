"""Session adapters A: omo/opencode/claude/codex SourceAdapter contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sb.connectors import discover_adapters
from sb.connectors.base import ItemMeta
from sb.connectors.sessions_claude import ADAPTER_ID as CLAUDE_ID
from sb.connectors.sessions_claude import create as create_claude
from sb.connectors.sessions_codex import ADAPTER_ID as CODEX_ID
from sb.connectors.sessions_codex import create as create_codex
from sb.connectors.sessions_omo import ADAPTER_ID as OMO_ID
from sb.connectors.sessions_omo import create as create_omo
from sb.connectors.sessions_opencode import ADAPTER_ID as OPENCODE_ID
from sb.connectors.sessions_opencode import create as create_opencode
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
    _ = dest.write_bytes((SPIKE / family / name).read_bytes())
    return dest


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[bytes]:
    return [body for _ref, body, meta in items if "skip_reason" not in meta]


def _texts(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [body.decode() for body in _delivered(items)]


def _skipped(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [str(meta.get("skip_reason")) for _r, _b, meta in items if "skip_reason" in meta]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, separators=(",", ":"), sort_keys=True) for row in records]
    _ = path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _codex_session_meta(session_id: str) -> dict[str, object]:
    return {"type": "session_meta", "payload": {"id": session_id, "session_id": session_id}}


def _codex_event(kind: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"type": kind}
    payload.update(fields)
    return {"type": "event_msg", "payload": payload}


def _codex_user_response(text: str, item_id: str) -> dict[str, object]:
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": item_id,
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _codex_assistant(text: str, item_id: str, phase: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "message",
        "id": item_id,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }
    if phase is not None:
        payload["phase"] = phase
    return {"type": "response_item", "payload": payload}


def test_omo_scan_yields_source_ref_and_visible_text_when_current_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format OMO current JSONL fixture.
    root = tmp_path / "omo"
    _ = _copy_spike(root, "omo", "current.jsonl")
    adapter = create_omo(_cfg(OMO_ID, root, "omo"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: SourceRef items carry the visible user/assistant text.
    assert items
    assert all(isinstance(ref, SourceRef) and ref.source_id == "omo" for ref, _b, _m in items)
    blob = b"\n".join(_delivered(items))
    assert b"VISIBLE_USER_1" in blob
    assert b"VISIBLE_ASSISTANT_1" in blob


def test_opencode_scan_yields_source_ref_and_visible_text_when_current_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format OpenCode snapshot fixture.
    root = tmp_path / "opencode"
    root.mkdir()
    _ = (root / "snapshot.json").write_bytes((SPIKE / "opencode" / "current.json").read_bytes())
    adapter = create_opencode(_cfg(OPENCODE_ID, root, "opencode"))

    # When: the adapter scans the snapshot.
    items = list(adapter.scan(None))

    # Then: visible user/assistant/tool text is delivered under SourceRef.
    blob = b"\n".join(_delivered(items))
    assert items
    assert all(ref.source_id == "opencode" for ref, _b, _m in items)
    assert b"VISIBLE_USER_2" in blob
    assert b"VISIBLE_ASSISTANT_2" in blob


def test_claude_scan_yields_source_ref_and_visible_text_when_golden_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format Claude golden JSONL fixture.
    root = tmp_path / "claude"
    _ = _copy_spike(root, "claude", "golden.jsonl")
    adapter = create_claude(_cfg(CLAUDE_ID, root, "claude"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: SourceRef items include the golden visible texts.
    blob = b"\n".join(_delivered(items))
    assert all(ref.source_id == "claude" for ref, _b, _m in items)
    assert b"VISIBLE_USER_1" in blob
    assert b"VISIBLE_ASSISTANT_1" in blob


def test_codex_scan_yields_source_ref_and_visible_text_when_golden_fixture(tmp_path: Path) -> None:
    # Given: a copied real-format Codex golden JSONL fixture.
    root = tmp_path / "codex"
    _ = _copy_spike(root, "codex", "golden.jsonl")
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the adapter scans with no cursor.
    items = list(adapter.scan(None))

    # Then: SourceRef items include the golden visible user/assistant text.
    blob = b"\n".join(_delivered(items))
    assert all(ref.source_id == "codex" for ref, _b, _m in items)
    assert b"VISIBLE_USER_1" in blob
    assert b"VISIBLE_ASSISTANT_1" in blob


def test_codex_emits_active_response_user_when_task_has_no_event_user(tmp_path: Path) -> None:
    # Given: a live Codex stream with task_started then response-item user input_text.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "active.jsonl",
        [
            _codex_session_meta("sess-active"),
            _codex_event("task_started", turn_id="t1"),
            _codex_user_response("ACTIVE_RESPONSE_USER", "msg-active"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the adapter scans the live stream.
    texts = _texts(list(adapter.scan(None)))

    # Then: the in-task response user is emitted as fallback user text.
    assert "ACTIVE_RESPONSE_USER" in texts


def test_codex_attaches_pre_task_pending_response_user_to_next_task(tmp_path: Path) -> None:
    # Given: a response-item user that arrives before task_started.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "pending.jsonl",
        [
            _codex_session_meta("sess-pending"),
            _codex_user_response("PENDING_RESPONSE_USER", "msg-pending"),
            _codex_event("task_started", turn_id="t1"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the adapter scans.
    texts = _texts(list(adapter.scan(None)))

    # Then: the pending response user attaches to the next task.
    assert "PENDING_RESPONSE_USER" in texts


def test_codex_emits_unphased_assistant_output_as_final_fallback(tmp_path: Path) -> None:
    # Given: an assistant response_item output_text with no phase.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "unphased.jsonl",
        [
            _codex_session_meta("sess-final"),
            _codex_event("task_started", turn_id="t1"),
            _codex_assistant("UNPHASED_ASSISTANT_FINAL", "msg-asst"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the adapter scans.
    texts = _texts(list(adapter.scan(None)))

    # Then: unphased assistant output_text is the final fallback.
    assert "UNPHASED_ASSISTANT_FINAL" in texts


def test_codex_event_user_takes_precedence_over_response_input_text(tmp_path: Path) -> None:
    # Given: both event_msg.user_message and response-item user input_text.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "prec.jsonl",
        [
            _codex_session_meta("sess-prec"),
            _codex_event("task_started", turn_id="t1"),
            _codex_event("user_message", message="EVENT_USER_AUTHORITATIVE"),
            _codex_user_response("RESPONSE_INPUT_TEXT_FALLBACK", "msg-fallback"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the adapter scans.
    texts = _texts(list(adapter.scan(None)))

    # Then: event user wins; response input_text is not delivered as user text.
    assert "EVENT_USER_AUTHORITATIVE" in texts
    assert "RESPONSE_INPUT_TEXT_FALLBACK" not in texts


def test_codex_resume_keeps_session_lineage_when_later_turn_is_appended(
    tmp_path: Path,
) -> None:
    # Given: a live Codex JSONL scanned once, with its byte-offset cursor captured.
    root = tmp_path / "codex"
    path = _write_jsonl(
        root / "live.jsonl",
        [
            _codex_session_meta("sess-resume"),
            _codex_event("task_started", turn_id="t1"),
            _codex_event("user_message", message="TURN_ONE"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))
    first = list(adapter.scan(None))
    assert _texts(first) == ["TURN_ONE"]
    cursor = adapter.next_cursor()

    # When: a second task/user is appended after the same session_meta and scan resumes.
    with path.open("a", encoding="utf-8") as handle:
        for row in (
            _codex_event("task_started", turn_id="t2"),
            _codex_event("user_message", message="TURN_TWO"),
        ):
            _ = handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    resumed = list(adapter.scan(cursor))

    # Then: only the appended turn is delivered, lineage holds, unchanged re-resume is empty.
    assert _texts(resumed) == ["TURN_TWO"]
    assert "lineage" not in _skipped(resumed)
    assert "TURN_ONE" not in _texts(resumed)
    later = adapter.next_cursor()
    assert list(adapter.scan(later)) == []
    assert adapter.next_cursor() == later


def test_codex_quarantines_missing_canonical_text_while_sibling_session_ingests(tmp_path: Path) -> None:
    # Given: one session missing canonical user text and one valid sibling.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "good.jsonl",
        [
            _codex_session_meta("sess-good"),
            _codex_event("task_started", turn_id="t1"),
            _codex_event("user_message", message="SIBLING_OK"),
        ],
    )
    _ = _write_jsonl(
        root / "bad.jsonl",
        [
            _codex_session_meta("sess-bad"),
            _codex_event("task_started", turn_id="t2"),
            _codex_event("user_message", message=""),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: both files are scanned.
    items = list(adapter.scan(None))

    # Then: missing canonical text is typed-quarantined; the sibling still ingests.
    assert "SIBLING_OK" in _texts(items)
    assert "missing-canonical-text" in _skipped(items)


def test_codex_quarantines_size_and_lineage_while_sibling_session_ingests(tmp_path: Path) -> None:
    # Given: size-mismatch and lineage-broken records beside a valid session.
    root = tmp_path / "codex"
    _ = _write_jsonl(
        root / "good.jsonl",
        [
            _codex_session_meta("sess-ok"),
            _codex_event("task_started", turn_id="t1"),
            _codex_event("user_message", message="SIZE_SIBLING_OK"),
        ],
    )
    _ = _write_jsonl(
        root / "size.jsonl",
        [
            _codex_session_meta("sess-size"),
            _codex_event("task_started", turn_id="t2"),
            _codex_event("user_message", message="tiny", size=99),
        ],
    )
    _ = _write_jsonl(
        root / "lineage.jsonl",
        [
            _codex_user_response("ORPHAN_USER", "msg-orphan"),
        ],
    )
    adapter = create_codex(_cfg(CODEX_ID, root, "codex"))

    # When: the mixed tree is scanned.
    items = list(adapter.scan(None))

    # Then: size and lineage are quarantined; the valid session still ingests.
    reasons = _skipped(items)
    assert "SIZE_SIBLING_OK" in _texts(items)
    assert "size-limit" in reasons
    assert "lineage" in reasons


def test_jsonl_byte_offset_resume_yields_zero_when_fixture_unchanged(tmp_path: Path) -> None:
    # Given: scanned OMO/Claude/Codex JSONL fixtures with captured cursors.
    omo_root = tmp_path / "omo"
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    _ = _copy_spike(omo_root, "omo", "current.jsonl")
    _ = _copy_spike(claude_root, "claude", "golden.jsonl")
    _ = _copy_spike(codex_root, "codex", "golden.jsonl")
    omo = create_omo(_cfg(OMO_ID, omo_root, "omo"))
    claude = create_claude(_cfg(CLAUDE_ID, claude_root, "claude"))
    codex = create_codex(_cfg(CODEX_ID, codex_root, "codex"))
    assert _delivered(list(omo.scan(None)))
    assert _delivered(list(claude.scan(None)))
    assert _delivered(list(codex.scan(None)))
    omo_cursor, claude_cursor, codex_cursor = omo.next_cursor(), claude.next_cursor(), codex.next_cursor()

    # When: each adapter rescans with the exact byte-offset cursor.
    omo_resume = list(omo.scan(omo_cursor))
    claude_resume = list(claude.scan(claude_cursor))
    codex_resume = list(codex.scan(codex_cursor))

    # Then: unchanged fixtures yield zero items and the cursor is stable.
    assert omo_resume == []
    assert claude_resume == []
    assert codex_resume == []
    assert omo.next_cursor() == omo_cursor
    assert claude.next_cursor() == claude_cursor
    assert codex.next_cursor() == codex_cursor


def test_opencode_byte_offset_resume_yields_zero_when_snapshot_unchanged(tmp_path: Path) -> None:
    # Given: a scanned OpenCode snapshot whose cursor was captured.
    root = tmp_path / "opencode"
    root.mkdir()
    _ = (root / "snapshot.json").write_bytes((SPIKE / "opencode" / "current.json").read_bytes())
    adapter = create_opencode(_cfg(OPENCODE_ID, root, "opencode"))
    first = list(adapter.scan(None))
    assert _delivered(first)
    cursor = adapter.next_cursor()

    # When: the snapshot is rescanned with the returned cursor.
    resume = list(adapter.scan(cursor))

    # Then: zero items and the byte-offset cursor is unchanged.
    assert resume == []
    assert adapter.next_cursor() == cursor


def test_absent_root_is_skipped_without_raise(tmp_path: Path) -> None:
    # Given: configured roots that do not exist.
    missing = tmp_path / "no-such-sessions-root"
    adapters = (
        create_omo(_cfg(OMO_ID, missing, "omo")),
        create_opencode(_cfg(OPENCODE_ID, missing, "opencode")),
        create_claude(_cfg(CLAUDE_ID, missing, "claude")),
        create_codex(_cfg(CODEX_ID, missing, "codex")),
    )

    # When: each adapter scans the absent root.
    scans = [list(adapter.scan(None)) for adapter in adapters]

    # Then: no raise; each scan reports a typed skip.
    for items in scans:
        assert "absent-root" in _skipped(items)
        assert _delivered(items) == []


def test_malformed_jsonl_line_is_quarantined_and_scan_continues(tmp_path: Path) -> None:
    # Given: an OMO JSONL file with a valid header, a corrupt line, and a valid user message.
    root = tmp_path / "omo"
    path = root / "mixed.jsonl"
    path.parent.mkdir()
    header = json.dumps({"type": "session", "version": 3, "id": "sess-mix"})
    message = json.dumps(
        {
            "type": "message",
            "id": "msg-ok",
            "parentId": None,
            "message": {"role": "user", "content": [{"type": "text", "text": "AFTER_CORRUPT"}]},
        }
    )
    _ = path.write_text(header + "\n{not-json\n" + message + "\n", encoding="utf-8")
    adapter = create_omo(_cfg(OMO_ID, root, "omo"))

    # When: the adapter scans the mixed file.
    items = list(adapter.scan(None))

    # Then: the bad line is quarantined and the later valid message is still ingested.
    assert "AFTER_CORRUPT" in _texts(items)
    assert any(reason in {"malformed-json", "invalid-format"} for reason in _skipped(items))


def test_registry_auto_discovers_four_session_adapters() -> None:
    # Given: the real sb.connectors package after the four session modules exist.
    from sb.config import load_config

    # When: adapters are discovered.
    registry = discover_adapters(load_config())

    # Then: each session adapter is registered under its unique ADAPTER_ID.
    for adapter_id in (OMO_ID, OPENCODE_ID, CLAUDE_ID, CODEX_ID):
        assert adapter_id in registry
        assert registry[adapter_id].source_id
