"""PostCompact stages reselect; UserPromptSubmit is the documented inject event."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from sb.cli import main
from sb.contracts import PageSpec, SourceCite
from sb.memory_records import parse_page_records
from sb.postcompact_hook import (
    PostCompactHookError,
    confirm_delivery,
    handle_postcompact,
    parse_postcompact_event,
    select_search_query,
)
from sb.search import SearchHit, SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from tests.knowledge import stamp_knowledge


class _HashLedger:
    def __init__(self, root: Path) -> None:
        self._root = root

    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "vault"
    vault = init_vault(root)
    digest = ContentAddressedStore(root).put(b"omega-body")
    cite = SourceCite(sid=digest[:8], origin="me-wiki:notes/omega.md", hash=digest)
    page = PageSpec(
        "wiki/omega",
        "Omega",
        f"# Omega\nOmegaCompiledBody is the current record.\n[^{digest[:8]}]",
        [cite],
        "active",
    )
    _ = vault.write_pages((page,), "run-postcompact", _HashLedger(root))
    stamp_knowledge(root)
    return root, digest


def _write_config(tmp_path: Path, root: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    config = tmp_path / "config.toml"
    _ = config.write_text(
        f"vault_root = {json.dumps(str(root))}\n"
        + f"state_root = {json.dumps(str(state))}\n",
    )
    return config


def _event(
    *,
    session_id: str = "sess-omega",
    summary: str = "OmegaCompiledBody",
    prompt_id: str = "p1",
    compaction_id: str = "c1",
) -> bytes:
    return json.dumps({
        "hook_event_name": "PostCompact",
        "session_id": session_id,
        "compact_summary": summary,
        "trigger": "auto",
        "prompt_id": prompt_id,
        "compaction_id": compaction_id,
    }).encode()


def _prompt(*, session_id: str = "sess-omega", prompt: str = "") -> bytes:
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
    }
    if prompt:
        payload["prompt"] = prompt
    return json.dumps(payload).encode()


def test_parse_rejects_precompact_and_invalid_json() -> None:
    with pytest.raises(PostCompactHookError, match="HOOK_EVENT_UNSUPPORTED"):
        _ = parse_postcompact_event(json.dumps({
            "hook_event_name": "PreCompact",
            "session_id": "s1",
            "compact_summary": "x",
        }).encode())
    with pytest.raises(PostCompactHookError, match="HOOK_JSON_INVALID"):
        _ = parse_postcompact_event(b"{")


def test_postcompact_stages_without_additional_context(tmp_path: Path) -> None:
    root, digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    result = handle_postcompact(_event(), index)
    assert result.hook_payload == {}
    assert result.records[0]["page_id"] == "wiki/omega"
    parsed = parse_page_records((root / "wiki/omega.md").read_bytes(), "wiki/omega")
    assert parsed
    assert result.records[0]["source_ref"] == "me-wiki:notes/omega.md"
    assert result.records[0]["record_id"] == parsed[0].record_id
    assert result.records[0]["version"] == parsed[0].record_digest
    assert result.records[0]["version"] != digest
    assert "OmegaCompiledBody" in result.records[0]["snippet"]
    injected = handle_postcompact(_prompt(), index)
    specific = cast(dict[str, object], injected.hook_payload["hookSpecificOutput"])
    assert specific["hookEventName"] == "UserPromptSubmit"
    context = cast(str, specific["additionalContext"])
    assert "sess-omega" in context
    assert "OmegaCompiledBody" in context
    assert "wiki/omega" in context
    encoded = json.dumps(injected.hook_payload, ensure_ascii=False).encode()
    assert len(encoded) <= 16384


def test_duplicate_prompt_does_not_reinject(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_event(), index)
    first = handle_postcompact(_prompt(), index)
    assert first.pending_confirm is True
    confirm_delivery(root, "sess-omega")
    second = handle_postcompact(_prompt(), index)
    assert first.hook_payload["hookSpecificOutput"]
    assert second.hook_payload == {}
    assert second.duplicate is True


def test_new_compaction_same_summary_new_prompt_id(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_event(summary="OmegaCompiledBody", prompt_id="p1"), index)
    first = handle_postcompact(_prompt(), index)
    confirm_delivery(root, "sess-omega")
    staged = handle_postcompact(_event(summary="OmegaCompiledBody", prompt_id="p2"), index)
    again = handle_postcompact(_prompt(), index)
    assert first.pending_confirm is True
    assert staged.records == ()
    assert again.hook_payload == {}


def test_new_compaction_same_prompt_new_compaction_id(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_event(prompt_id="p1", compaction_id="c1"), index)
    first = handle_postcompact(_prompt(), index)
    confirm_delivery(root, "sess-omega")
    staged = handle_postcompact(_event(prompt_id="p1", compaction_id="c2"), index)
    again = handle_postcompact(_prompt(), index)
    assert first.pending_confirm is True
    assert staged.records == ()
    assert again.hook_payload == {}


def test_same_page_sections_dedupe_to_one_record() -> None:
    hits = tuple(
        SearchHit("wiki/omega", f"s{index}", "OmegaCompiledBody", 1.0 - index / 10)
        for index in range(8)
    )
    from sb.postcompact_hook import _serialize, parse_postcompact_event

    event = parse_postcompact_event(_event())
    records, _context = _serialize(event, hits)
    assert len(records) == 1
    assert records[0]["page_id"] == "wiki/omega"


def test_final_json_stays_within_budget() -> None:
    hits = tuple(
        SearchHit(f"wiki/p{index}", "body", "x" * 2048, 1.0)
        for index in range(8)
    )
    from sb.postcompact_hook import _inject_payload, _serialize, parse_postcompact_event

    event = parse_postcompact_event(_event())
    records, context = _serialize(event, hits)
    payload = _inject_payload("UserPromptSubmit", context)
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= 16384
    assert len(records) <= 8


def test_long_summary_selects_a_bounded_query() -> None:
    summary = ("OmegaCompiledBody " * 400).strip()
    assert len(summary.encode()) > 4096
    query = select_search_query(summary)
    assert "OmegaCompiledBody" in query
    assert len(query.encode()) <= 4096


def test_postcompact_cli_long_summary_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root, _digest = _seed(tmp_path)
    config = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(_event(summary=("OmegaCompiledBody " * 400).strip())))
    assert main(["postcompact-hook"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    monkeypatch.setattr("sys.stdin", BytesIO(_prompt()))
    assert main(["postcompact-hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "OmegaCompiledBody" in payload["hookSpecificOutput"]["additionalContext"]


def test_empty_search_is_not_context_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root, _digest = _seed(tmp_path)
    config = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(_event(summary="zzzz-no-such-term")))
    assert main(["postcompact-hook"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    monkeypatch.setattr("sys.stdin", BytesIO(_prompt()))
    assert main(["postcompact-hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "additionalContext" not in json.dumps(payload) or payload.get("hookSpecificOutput") is None or payload == {}


def test_syntax_failure_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root, _digest = _seed(tmp_path)
    config = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(json.dumps({
        "hook_event_name": "PostCompact",
        "session_id": "sess-bad",
        "compact_summary": '"미완성',
    }).encode()))
    assert main(["postcompact-hook"]) == 1
    captured = capsys.readouterr()
    assert "SEARCH_QUERY_" in captured.err
    assert captured.out == ""


def test_broken_pipe_retry_still_delivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root, _digest = _seed(tmp_path)
    config = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(_event()))
    assert main(["postcompact-hook"]) == 0
    _ = capsys.readouterr()

    class Boom:
        def write(self, _data: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            return None

    live_stdout = sys.stdout
    monkeypatch.setattr("sys.stdin", BytesIO(_prompt()))
    monkeypatch.setattr("sys.stdout", Boom())
    assert main(["postcompact-hook"]) == 1
    monkeypatch.setattr("sys.stdout", live_stdout)
    monkeypatch.setattr("sys.stdin", BytesIO(_prompt()))
    assert main(["postcompact-hook"]) == 0
    output = capsys.readouterr().out
    assert "OmegaCompiledBody" in output
    assert "UserPromptSubmit" in output


def test_query_binds_omega_record_not_alpha_on_two_cite_page(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    vault = init_vault(root)
    alpha_hash = ContentAddressedStore(root).put(b"alpha-body")
    omega_hash = ContentAddressedStore(root).put(b"omega-body")
    page = PageSpec(
        "wiki/mixed",
        "Mixed",
        (
            f"# Mixed\nAlphaUniqueMemory is old.\n[^{alpha_hash[:8]}]\n\n"
            + f"OmegaUniqueTarget is current.\n[^{omega_hash[:8]}]"
        ),
        [
            SourceCite(sid=alpha_hash[:8], origin="me-wiki:notes/alpha.md", hash=alpha_hash),
            SourceCite(sid=omega_hash[:8], origin="me-wiki:notes/omega.md", hash=omega_hash),
        ],
        "active",
    )
    _ = vault.write_pages((page,), "run-mixed", _HashLedger(root))
    stamp_knowledge(root)
    index = SearchIndex(root, hybrid=False)
    result = handle_postcompact(_event(summary="OmegaUniqueTarget"), index, tmp_path / "state")
    parsed = parse_page_records((root / "wiki/mixed.md").read_bytes(), "wiki/mixed")
    omega = next(rec for rec in parsed if "OmegaUniqueTarget" in rec.record_text)
    alpha = next(rec for rec in parsed if "AlphaUniqueMemory" in rec.record_text)
    assert len(result.records) == 1
    assert result.records[0]["record_id"] == omega.record_id
    assert result.records[0]["version"] == omega.record_digest
    assert result.records[0]["source_ref"] == "me-wiki:notes/omega.md"
    assert "OmegaUniqueTarget" in result.records[0]["snippet"]
    assert alpha.record_id not in result.records[0]["record_id"]
    assert "AlphaUniqueMemory" not in result.records[0]["snippet"]


def test_compiled_page_id_keeps_docs_note_origin(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    vault = init_vault(root)
    alpha_hash = ContentAddressedStore(root).put(b"alpha-body")
    omega_hash = ContentAddressedStore(root).put(b"omega-body")
    page = PageSpec(
        "docs-note-87c681b2",
        "Note",
        (
            f"# Note\nAlphaUniqueMemory is old.\n[^{alpha_hash[:8]}]\n\n"
            + f"OmegaUniqueTarget is current.\n[^{omega_hash[:8]}]"
        ),
        [
            SourceCite(sid=alpha_hash[:8], origin="docs:note.md", hash=alpha_hash),
            SourceCite(sid=omega_hash[:8], origin="docs:note.md", hash=omega_hash),
        ],
        "active",
    )
    _ = vault.write_pages((page,), "run-compiled", _HashLedger(root))
    stamp_knowledge(root)
    index = SearchIndex(root, hybrid=False)
    result = handle_postcompact(_event(summary="OmegaUniqueTarget"), index, tmp_path / "state")
    parsed = parse_page_records((root / "wiki/docs-note-87c681b2.md").read_bytes(), "wiki/docs-note-87c681b2")
    omega = next(rec for rec in parsed if "OmegaUniqueTarget" in rec.record_text)
    assert result.records[0]["page_id"] == "wiki/docs-note-87c681b2"
    assert result.records[0]["source_ref"] == "docs:note.md"
    assert result.records[0]["record_id"] == omega.record_id
    assert result.records[0]["version"] == omega.record_digest
    assert "OmegaUniqueTarget" in result.records[0]["snippet"]
    assert "AlphaUniqueMemory" not in result.records[0]["snippet"]


def test_session_state_uses_state_root_not_generation(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    result = handle_postcompact(_event(), SearchIndex(root, hybrid=False), state)
    assert result.hook_payload == {}
    assert (state / ".sb" / "session-memory").is_dir()
    assert not (root / ".sb" / "session-memory").exists()


def _session(
    *,
    session_id: str = "sess-omega",
    summary: str = "OmegaCompiledBody",
    prompt_id: str = "p1",
    compaction_id: str = "c1",
) -> bytes:
    return json.dumps({
        "hook_event_name": "SessionStart",
        "source": "compact",
        "session_id": session_id,
        "compact_summary": summary,
        "prompt_id": prompt_id,
        "compaction_id": compaction_id,
    }).encode()


def test_session_start_compact_injects_omega_not_prompt_wait(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    result = handle_postcompact(_session(), index, tmp_path / "state")
    specific = cast(dict[str, object], result.hook_payload["hookSpecificOutput"])
    assert specific["hookEventName"] == "SessionStart"
    context = cast(str, specific["additionalContext"])
    assert "sess-omega" in context
    assert "OmegaCompiledBody" in context
    assert result.records[0]["source_ref"] == "me-wiki:notes/omega.md"
    assert result.pending_confirm is True
    encoded = json.dumps(result.hook_payload, ensure_ascii=False).encode()
    assert len(encoded) <= 16384
    confirm_delivery(tmp_path / "state", "sess-omega")
    again = handle_postcompact(_session(), index, tmp_path / "state")
    assert again.hook_payload == {}
    assert again.duplicate is True


def test_session_start_compact_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root, _digest = _seed(tmp_path)
    config = _write_config(tmp_path, root)
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(_session()))
    assert main(["postcompact-hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "OmegaCompiledBody" in payload["hookSpecificOutput"]["additionalContext"]


def test_session_start_compact_uses_last_query(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_prompt(prompt="OmegaCompiledBody"), index, state)
    result = handle_postcompact(json.dumps({
        "hook_event_name": "SessionStart",
        "source": "compact",
        "session_id": "sess-omega",
    }).encode(), index, state)
    specific = cast(dict[str, object], result.hook_payload["hookSpecificOutput"])
    assert specific["hookEventName"] == "SessionStart"
    assert "OmegaCompiledBody" in cast(str, specific["additionalContext"])


def test_session_start_compact_without_query_is_empty(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    result = handle_postcompact(json.dumps({
        "hook_event_name": "SessionStart",
        "source": "compact",
        "session_id": "sess-omega",
    }).encode(), SearchIndex(root, hybrid=False), tmp_path / "state")
    assert result.hook_payload == {}


def test_session_start_other_source_empty(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    result = handle_postcompact(json.dumps({
        "hook_event_name": "SessionStart",
        "source": "startup",
        "session_id": "sess-omega",
    }).encode(), SearchIndex(root, hybrid=False), tmp_path / "state")
    assert result.hook_payload == {}


def test_postcompact_excludes_in_turn_delivered(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    state = tmp_path / "state"
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_session(), index, state)
    confirm_delivery(state, "sess-omega")
    staged = handle_postcompact(_event(), index, state)
    assert staged.records == ()
    follow = handle_postcompact(_prompt(), index, state)
    assert follow.hook_payload == {}
