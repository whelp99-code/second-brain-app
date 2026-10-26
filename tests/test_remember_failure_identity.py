"""Explicit retry identity survives every remember JSON failure family."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import sb.mcp as mcp_module
from sb.config import Config
from sb.inbox import InboxModeRestoreError, RememberIdentity
from sb.mcp import build_server
from tests.test_write_followup import _call, _error_payload, _error_text


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("outcome", ["absent", "written", "unknown", "mode_written", "mode_unknown"])
def test_remember_json_failure_preserves_only_explicit_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit: bool,
    outcome: str,
) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    arguments: dict[str, object] = {"content": "exact identity body", "title": "note"}
    if explicit:
        arguments["request_id"] = "Retry_ID-724"
    real_write = mcp_module.write_inbox
    real_lstat = os.lstat

    def fail_write(
        root: Path, content: str, title: str | None,
        request_id: str | RememberIdentity | None = None,
        *, config: Config | None = None,
    ) -> Path:
        saved = real_write(root, content, title, request_id, config=config)
        if outcome == "mode_written":
            raise InboxModeRestoreError(root / "inbox", 0o500, saved)
        raise OSError("synthetic post-publication failure")

    def fail_before(*_args: object, **_kwargs: object) -> Path:
        if outcome == "mode_unknown":
            raise InboxModeRestoreError(root / "inbox", 0o500, None)
        raise OSError("synthetic pre-publication failure")

    def deny_evidence(path: str | os.PathLike[str], *args: object, **kwargs: object) -> os.stat_result:
        if Path(path).parent == root / "inbox" and Path(path).suffix == ".md":
            raise PermissionError("synthetic evidence read failure")
        return real_lstat(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(mcp_module, "write_inbox", fail_write if outcome in {"written", "mode_written"} else fail_before)
        if outcome == "unknown":
            fault.setattr(os, "lstat", deny_evidence)
        result = _call(server, "sb_remember", arguments)
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    code, delivery, written = {
        "absent": ("NOTHING_WRITTEN", "not_written", False),
        "written": ("WRITTEN_WITH_FOLLOWUP_ERROR", "written", True),
        "unknown": ("WRITE_OUTCOME_UNKNOWN", "unknown", None),
        "mode_written": ("INBOX_MODE_RESTORE_FAILED", "written", True),
        "mode_unknown": ("INBOX_MODE_RESTORE_FAILED", "unknown", None),
    }[outcome]
    assert payload["code"] == code
    assert payload["delivery"] == delivery
    assert payload["written"] is written
    if explicit:
        assert payload["request_id"] == arguments["request_id"]
    else:
        assert "request_id" not in payload
    pages_before = list((root / "inbox").glob("*.md"))
    assert len(pages_before) == (1 if written else 0)
    assert all(page.read_bytes() == b"exact identity body" for page in pages_before)
    assert _call(server, "sb_remember", arguments).is_error is False
    pages_after = list((root / "inbox").glob("*.md"))
    assert len(pages_after) == (1 if explicit or not written else 2)
    assert all(page.read_bytes() == b"exact identity body" for page in pages_after)


@pytest.mark.parametrize("request_id", ["", "invalid.id", "x" * 65])
def test_invalid_explicit_identity_still_rejects_before_publication(
    tmp_path: Path, request_id: str,
) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    result = _call(server, "sb_remember", {"content": "invalid", "request_id": request_id})
    assert result.is_error is True
    assert "REMEMBER_REQUEST_ID_INVALID" in _error_text(result)
    assert not list((root / "inbox").glob("*.md"))
