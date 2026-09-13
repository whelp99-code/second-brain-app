"""Claude Code PostCompact stdin → search reselect → same-session hook JSON."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import cast

import pytest

from sb.cli import main
from sb.contracts import PageSpec, SourceCite
from sb.postcompact_hook import (
    PostCompactHookError,
    handle_postcompact,
    parse_postcompact_event,
)
from sb.search import SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from tests.knowledge import stamp_knowledge


class _HashLedger:
    def __init__(self, root: Path) -> None:
        self._root = root

    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _seed(tmp_path: Path) -> Path:
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
    return root


def _event(*, session_id: str = "sess-omega", summary: str = "OmegaCompiledBody") -> bytes:
    return json.dumps({
        "hook_event_name": "PostCompact",
        "session_id": session_id,
        "compact_summary": summary,
        "trigger": "auto",
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


def test_postcompact_reselects_body_source_and_budget(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    index = SearchIndex(root, hybrid=False)
    result = handle_postcompact(_event(), index)
    output = result.hook_payload
    specific = cast(dict[str, object], output["hookSpecificOutput"])
    assert specific["hookEventName"] == "PostCompact"
    context = cast(str, specific["additionalContext"])
    assert "sess-omega" in context
    assert "OmegaCompiledBody" in context
    assert "wiki/omega" in context
    assert result.session_id == "sess-omega"
    assert result.budgets == {
        "max_items": 8,
        "max_excerpt_bytes": 4096,
        "max_total_bytes": 16384,
    }
    assert result.records[0]["page_id"] == "wiki/omega"
    assert result.records[0]["source_ref"]


def test_postcompact_cli_failure_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root = _seed(tmp_path)
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(json.dumps({
        "hook_event_name": "PostCompact",
        "session_id": "sess-bad",
        "compact_summary": "가" * 1366,
    }).encode()))
    assert main(["postcompact-hook"]) == 1
    captured = capsys.readouterr()
    assert "SEARCH_QUERY_" in captured.err
    assert "additionalContext" not in captured.out


def test_postcompact_cli_success_stdout_is_claude_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root = _seed(tmp_path)
    config = tmp_path / "config.toml"
    _ = config.write_text(f"vault_root = {json.dumps(str(root))}\n")
    monkeypatch.setenv("SB_CONFIG", str(config))
    monkeypatch.setattr("sys.stdin", BytesIO(_event()))
    assert main(["postcompact-hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostCompact"
    assert "OmegaCompiledBody" in payload["hookSpecificOutput"]["additionalContext"]
