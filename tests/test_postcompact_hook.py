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


def _prompt(*, session_id: str = "sess-omega") -> bytes:
    return json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
    }).encode()


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
    _ = handle_postcompact(_event(summary="OmegaCompiledBody", prompt_id="p2"), index)
    again = handle_postcompact(_prompt(), index)
    assert first.pending_confirm is True
    assert again.duplicate is False
    assert again.pending_confirm is True
    assert "OmegaCompiledBody" in cast(
        str, cast(dict[str, object], again.hook_payload["hookSpecificOutput"])["additionalContext"],
    )


def test_new_compaction_same_prompt_new_compaction_id(tmp_path: Path) -> None:
    root, _digest = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    _ = handle_postcompact(_event(prompt_id="p1", compaction_id="c1"), index)
    first = handle_postcompact(_prompt(), index)
    confirm_delivery(root, "sess-omega")
    _ = handle_postcompact(_event(prompt_id="p1", compaction_id="c2"), index)
    again = handle_postcompact(_prompt(), index)
    assert first.pending_confirm is True
    assert again.duplicate is False
    assert again.pending_confirm is True


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
    from sb.postcompact_hook import _prompt_payload, _serialize, parse_postcompact_event

    event = parse_postcompact_event(_event())
    records, context = _serialize(event, hits)
    payload = _prompt_payload(context)
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
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
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
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
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
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
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
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
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
