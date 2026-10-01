"""Post-publish failures must not claim NOTHING_WRITTEN."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult

import sb.mcp as mcp_module
from sb.config import Config
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.task30_barriers import BarrierEvent, Task30BarrierId
from sb.vault import init_vault
from sb.vault_owner import VaultOwnerMismatch
from sb.write_request_values import WriteRequestRejected
from tests.task30_clock import FrozenTask30DateTime


def _error_payload(text: str) -> dict[str, object]:
    _prefix, separator, body = text.partition(": ")
    assert separator == ": "
    payload = cast(object, json.loads(body))
    assert body == json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _call(server: MCPServer, name: str, arguments: dict[str, object]) -> CallToolResult:
    async def _go() -> object:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, arguments)

    return cast(CallToolResult, anyio.run(_go))


def _error_text(result: CallToolResult) -> str:
    block = result.content[0]
    text = getattr(block, "text", None)
    assert isinstance(text, str)
    return text


def _inbox_pages(root: Path) -> list[Path]:
    inbox = root / "inbox"
    if not inbox.exists():
        return []
    return sorted(path for path in inbox.iterdir() if path.is_file() and not path.name.startswith("."))


def test_mcp_sb_remember_before_save_is_nothing_written_and_retry_writes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_write = Path.write_bytes

    def fail_temp(self: Path, data: bytes) -> int:
        if self.name.endswith(".tmp"):
            raise OSError("injected before rename")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_temp)
    failed = _call(server, "sb_remember", {"content": "once", "title": "note"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is False
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["delivery"] == "not_written"
    assert _inbox_pages(root) == []
    monkeypatch.setattr(Path, "write_bytes", real_write)
    retried = _call(server, "sb_remember", {"content": "once", "title": "note"})
    assert retried.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 1
    assert pages[0].read_text(encoding="utf-8") == "once"


def test_mcp_sb_remember_after_save_reports_written_and_retry_does_not_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_remember", {"content": "kept", "title": "note"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert payload["code"] != "NOTHING_WRITTEN"
    path = root / str(payload["path"])
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "kept"
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_remember", {"content": "kept", "title": "note"})
    assert retried.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 1
    assert pages[0] == path


def test_mcp_write_request_after_publish_oserror_is_not_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, task30=False)
    request = write_fixture_request()
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_write_request", {"request": request})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is True
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["code"] != "NOTHING_WRITTEN"
    assert payload["request_id"] == request["request_id"]
    published = list((tmp_path / ".requests" / "pending").glob("*.json"))
    assert len(published) == 1
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_write_request", {"request": request})
    assert retried.is_error is False
    body = cast(dict[str, object], retried.structured_content)
    assert body["request_id"] == request["request_id"]
    assert list((tmp_path / ".requests" / "pending").glob("*.json")) == published


def test_mcp_write_request_rejected_after_publish_is_not_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)

    class RejectAfterPublish:
        def reach(self, event: BarrierEvent) -> None:
            if event.barrier_id is Task30BarrierId.PENDING_PUBLISH_FSYNC:
                raise WriteRequestRejected("WRITE_REQUEST_IO_FAILED")

    server = build_server(root, task30=False, barrier_sink=RejectAfterPublish())
    request = write_fixture_request()
    failed = _call(server, "sb_write_request", {"request": request})
    assert failed.is_error is True
    text = _error_text(failed)
    payload = _error_payload(text)
    assert payload["written"] is True
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["cause"] == "WRITE_REQUEST_IO_FAILED"
    assert "NOTHING_WRITTEN" not in text
    published = list((tmp_path / ".requests" / "pending").glob("*.json"))
    assert len(published) == 1
    retried = _call(server, "sb_write_request", {"request": request})
    assert retried.is_error is False
    body = cast(dict[str, object], retried.structured_content)
    assert body["request_id"] == request["request_id"]
    assert len(list((tmp_path / ".requests" / "pending").glob("*.json"))) == 1


def test_mcp_and_web_refuse_foreign_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    foreign = os.getuid() + 1
    monkeypatch.setattr(os, "getuid", lambda: foreign)
    config = Config(raw={"vault_root": str(vault)})
    with pytest.raises(VaultOwnerMismatch, match="VAULT_OWNER_MISMATCH"):
        _ = build_server(vault, config=config)
    from sb.web import build_server as build_web

    with pytest.raises(VaultOwnerMismatch, match="VAULT_OWNER_MISMATCH"):
        _ = build_web(config)
    assert not (vault / ".sb").exists()


def test_generation_remember_after_pointer_switch_is_not_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_replace = os.replace
    switched = {"done": False}

    def fail_after_pointer(src: str | os.PathLike[str], dst: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
        real_replace(src, dst, *args, **kwargs)
        if Path(dst).name == "vault" and Path(src).name.startswith(".vault-") and not switched["done"]:
            switched["done"] = True
            raise RuntimeError("after pointer switch")

    monkeypatch.setattr(os, "replace", fail_after_pointer)
    failed = _call(server, "sb_remember", {"content": "kept-gen", "title": "note"})
    assert switched["done"] is True
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert payload["code"] != "NOTHING_WRITTEN"
    assert (root / "inbox").is_dir()
    notes = [path for path in (root / "inbox").iterdir() if path.suffix == ".md"]
    assert len(notes) == 1
    assert notes[0].read_text(encoding="utf-8") == "kept-gen"
    assert root.is_symlink()


def test_lookup_error_is_unknown_not_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, task30=False)
    real_lstat = os.lstat
    real_fsync = os.fsync

    def deny_pending(path: str | os.PathLike[str], *args: object, **kwargs: object) -> os.stat_result:
        if "pending" in Path(path).parts:
            raise PermissionError("injected lookup")
        return real_lstat(path, *args, **kwargs)

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            monkeypatch.setattr(os, "lstat", deny_pending)
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_write_request", {"request": write_fixture_request()})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert payload["delivery"] == "unknown"
    assert payload["written"] is None
    assert payload["code"] != "NOTHING_WRITTEN"
    assert isinstance(payload["retry"], str)


def test_processing_and_journal_count_as_written(tmp_path: Path) -> None:
    from sb.write_delivery import classify_delivery

    request_root = tmp_path / "requests"
    processing = request_root / "processing"
    processing.mkdir(parents=True)
    identity = "memreq:pos:v2:" + "ab" * 32
    v2 = processing / f"{identity}.1.v2.json"
    _ = v2.write_text("{}", encoding="utf-8")
    found = classify_delivery(request_root, tmp_path / "vault", identity, 2)
    assert found.evidence == "present"
    assert found.path is not None and found.path.endswith(".v2.json")
    v2.unlink()
    v3 = processing / f"{identity}.2.v3.json"
    _ = v3.write_text("{}", encoding="utf-8")
    assert classify_delivery(request_root, tmp_path / "vault", identity, 3).evidence == "present"
    v3.unlink()
    database = request_root / "journal.db"
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            "CREATE TABLE requests(request_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)"
        )
        _ = connection.execute(
            "INSERT INTO requests VALUES (?, ?)",
            (identity, json.dumps({"inbox_path": "pending/kept.json"})),
        )
    journal = classify_delivery(request_root, tmp_path / "vault", identity, 1)
    assert journal.evidence == "present"
    assert journal.path == "pending/kept.json"


def test_remember_retry_requires_same_title_and_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_remember", {"content": "same body", "title": "title-A"})
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is True
    saved = root / str(payload["path"])
    monkeypatch.setattr(os, "fsync", real_fsync)
    other = _call(server, "sb_remember", {"content": "same body", "title": "title-B"})
    assert other.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 2
    assert saved in pages
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from sb.inbox import write_inbox; print(write_inbox(Path(sys.argv[1]), 'same body', 'title-A').as_posix())",
            str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert completed.stdout.strip() == saved.relative_to(root).as_posix()
    assert len(_inbox_pages(root)) == 2
