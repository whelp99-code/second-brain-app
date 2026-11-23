"""Post-publish failures must not claim NOTHING_WRITTEN."""

from __future__ import annotations

import errno
import json
import os
import sqlite3
import stat
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import cast

import anyio
import pytest
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult

import sb.mcp as mcp_module
from sb.config import Config
from sb.inbox import write_inbox
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
    real_write = os.write

    def fail_temp(fd: int, data: bytes) -> int:
        if data == b"once":
            raise OSError("injected before rename")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", fail_temp)
    failed = _call(server, "sb_remember", {"content": "once", "title": "note", "request_id": "retry-same"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is False
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["delivery"] == "not_written"
    assert payload["request_id"] == "retry-same"
    assert _inbox_pages(root) == []
    monkeypatch.setattr(os, "write", real_write)
    retried = _call(server, "sb_remember", {"content": "once", "title": "note", "request_id": "retry-same"})
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
    failed = _call(server, "sb_remember", {"content": "kept", "title": "note", "request_id": "retry-same"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert payload["code"] != "NOTHING_WRITTEN"
    assert payload["request_id"] == "retry-same"
    path = root / str(payload["path"])
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "kept"
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_remember", {"content": "kept", "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    pages = [item for item in (root / "inbox").rglob("*.md") if item.is_file() and item.read_text(encoding="utf-8") == "kept"]
    assert len(pages) == 1


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


def test_omitted_request_id_stays_a_distinct_page(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    first = write_inbox(root, "same body", "title")
    second = write_inbox(root, "same body", "  title  ")
    assert first != second
    reused = write_inbox(root, "same body", "  title  ", "same-id")
    again = write_inbox(root, "same body", "title", "same-id")
    assert reused == again
    pages = [item for item in (root / "inbox").glob("*.md") if item.is_file()]
    assert len(pages) == 3
    assert all(item.read_text(encoding="utf-8") == "same body" for item in pages)


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
    failed = _call(server, "sb_remember", {"content": "kept-gen", "title": "note", "request_id": "retry-same"})
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
    monkeypatch.setattr(os, "replace", real_replace)
    retried = _call(server, "sb_remember", {"content": "kept-gen", "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    again = [path for path in (root / "inbox").rglob("*.md") if path.is_file() and path.read_text(encoding="utf-8") == "kept-gen"]
    assert len(again) == 1


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
    request = write_fixture_request()
    failed = _call(server, "sb_write_request", {"request": request})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert payload["delivery"] == "unknown"
    assert payload["written"] is None
    assert payload["request_id"] == request["request_id"]
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
    failed = _call(server, "sb_remember", {"content": "same body", "title": "title-A", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is True
    saved = root / str(payload["path"])
    monkeypatch.setattr(os, "fsync", real_fsync)
    other = _call(server, "sb_remember", {"content": "same body", "title": "title-B", "request_id": "retry-same"})
    assert other.is_error is False
    pages = [item for item in (root / "inbox").rglob("*.md") if item.is_file() and item.read_bytes() == b"same body"]
    assert len(pages) == 2
    assert saved in pages
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from sb.inbox import write_inbox; print(write_inbox(Path(sys.argv[1]), 'same body', 'title-A', 'retry-same').as_posix())",
            str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert completed.returncode == 0
    kept = [item for item in (root / "inbox").rglob("*.md") if item.is_file() and item.read_bytes() == b"same body"]
    assert len(kept) == 2


def test_post_link_fsync_failure_retry_does_not_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory fsync after the final name exists must not mint a second page."""
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected post-link fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_remember", {"content": "saved", "title": "title-A", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is True
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["code"] != "NOTHING_WRITTEN"
    assert not (root / "inbox" / ".retry-index.json").exists()
    assert list((root / "inbox").glob(".retry-*.md")) == []
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_remember", {"content": "saved", "title": "title-A", "request_id": "retry-same"})
    assert retried.is_error is False
    pages = [path for path in (root / "inbox").rglob("*.md") if path.is_file() and path.read_bytes() == b"saved"]
    assert len(pages) == 1
    other = _call(server, "sb_remember", {"content": "saved", "title": "title-B", "request_id": "retry-same"})
    assert other.is_error is False
    both = [path for path in (root / "inbox").rglob("*.md") if path.is_file() and path.read_bytes() == b"saved"]
    assert len(both) == 2


def _pages(root: Path, text: str) -> list[Path]:
    return [path for path in (root / "inbox").rglob("*.md") if path.is_file() and text in path.read_text(encoding="utf-8")]


def test_final_rename_fsync_failure_retry_does_not_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fsync after the final name is linked must not mint a second page.

    There is no retry filename to delete and no marker to strip. Marker-like
    user text is stored byte for byte.
    """
    body = "final <!-- sb-remember-id:deadbeef -->"
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_fsync = os.fsync
    directory_fsyncs = {"count": 0}

    def fail_second_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_fsyncs["count"] += 1
            if directory_fsyncs["count"] >= 1:
                raise OSError("injected post-link fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second_directory_fsync)
    failed = _call(server, "sb_remember", {"content": body, "title": "note", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    first = root / str(payload["path"])
    assert first.is_file()
    assert first.read_bytes() == body.encode()
    assert list(root.joinpath("inbox").glob(".retry-*.md")) == []
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_remember", {"content": body, "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    pages = [path for path in (root / "inbox").iterdir() if path.suffix == ".md" and not path.name.startswith(".")]
    assert pages == [first]
    assert pages[0].read_bytes() == body.encode()


def test_rename_failure_restores_sealed_inbox_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "notes"
    _ = init_vault(root)
    inbox = root / "inbox"
    inbox.chmod(0o500)
    real_link = os.link

    def fail_link(src: str | os.PathLike[str], dst: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
        del src, dst, args, kwargs
        raise OSError(errno.EIO, "injected exclusive link")

    monkeypatch.setattr(os, "link", fail_link)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    failed = _call(server, "sb_remember", {"content": "sealed", "title": "note", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["written"] is False
    assert stat.S_IMODE(inbox.stat().st_mode) == 0o500
    assert _pages(root, "sealed") == []
    monkeypatch.setattr(os, "link", real_link)
    retried = _call(server, "sb_remember", {"content": "sealed", "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    assert len(_pages(root, "sealed")) == 1
    assert stat.S_IMODE((root / "inbox").stat().st_mode) == 0o500


def test_mode_restore_failure_is_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "notes"
    _ = init_vault(root)
    (root / "inbox").chmod(0o500)
    real_chmod = os.chmod

    def fail_restore(path: str | os.PathLike[str], mode: int, follow_symlinks: bool = True) -> None:
        del follow_symlinks
        if Path(path).name == "inbox" and mode == 0o500:
            raise OSError("injected mode restore")
        real_chmod(path, mode)

    monkeypatch.setattr(os, "chmod", fail_restore)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    failed = _call(server, "sb_remember", {"content": "mode", "title": "note", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "INBOX_MODE_RESTORE_FAILED"
    assert payload["code"] != "NOTHING_WRITTEN"
    assert payload["written"] is True


_MARKER_BODY = "keep <!-- sb-remember-id:deadbeef --> tail"


def _from_inbox() -> bool:
    return any(frame.filename.endswith("/sb/inbox.py") for frame in traceback.extract_stack())


def test_unreadable_existing_page_is_unknown_and_not_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed read of the existing final path must not create a second page."""
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    first = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert first.is_error is False
    page = _inbox_pages(root)[0]
    assert page.read_bytes() == _MARKER_BODY.encode()
    real_read = os.read

    def fail_read(fd: int, length: int) -> bytes:
        if _from_inbox():
            raise OSError(errno.EIO, "injected read")
        return real_read(fd, length)

    monkeypatch.setattr(os, "read", fail_read)
    failed = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITE_OUTCOME_UNKNOWN"
    assert payload["written"] is None
    assert payload["code"] != "NOTHING_WRITTEN"
    assert _inbox_pages(root) == [page]
    assert page.read_bytes() == _MARKER_BODY.encode()
    monkeypatch.setattr(os, "read", real_read)
    retried = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    assert _inbox_pages(root) == [page]
    assert page.read_bytes() == _MARKER_BODY.encode()


def test_rename_noreplace_failure_does_not_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When link cannot work, renameat2 is the exclusive publish. Its failure is absent."""
    import sb.inbox as inbox_module

    root = tmp_path / "notes"
    _ = init_vault(root)
    (root / "inbox").chmod(0o500)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_link = os.link

    def link_unsupported(src: str | os.PathLike[str], dst: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
        del src, dst, args, kwargs
        raise OSError(errno.EXDEV, "link unsupported")

    def fail_rename(src: Path, dst: Path) -> None:
        del src, dst
        raise OSError(errno.EIO, "injected renameat2")

    monkeypatch.setattr(os, "link", link_unsupported)
    monkeypatch.setattr(inbox_module, "_rename_noreplace", fail_rename)
    failed = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert stat.S_IMODE((root / "inbox").stat().st_mode) == 0o500
    monkeypatch.setattr(os, "link", real_link)
    monkeypatch.undo()
    retried = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 1
    assert pages[0].read_bytes() == _MARKER_BODY.encode()
    assert stat.S_IMODE((root / "inbox").stat().st_mode) == 0o500


def test_fault_injection_matrix_one_page_and_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail each write-path filesystem call once, then retry the same request."""
    root = tmp_path / "notes"
    _ = init_vault(root)
    (root / "inbox").chmod(0o500)
    original_mode = 0o500
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    kinds: list[str] = []
    real_open = os.open
    real_write = os.write
    real_fsync = os.fsync
    real_link = os.link
    real_unlink = os.unlink
    real_chmod = os.chmod
    real_lstat = os.lstat
    real_read = os.read

    def install(fail_at: int | None) -> None:
        seen = {"n": 0}

        def bump(kind: str) -> None:
            if not _from_inbox():
                return
            seen["n"] += 1
            if fail_at is None:
                kinds.append(kind)
            if fail_at is not None and seen["n"] == fail_at:
                raise OSError(errno.EIO, f"injected {kind}")

        def wrapped_open(
            path: str | os.PathLike[str], flags: int, mode: int = 0o777, *,
            dir_fd: int | None = None,
        ) -> int:
            bump("open")
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        def wrapped_write(fd: int, data: bytes) -> int:
            bump("write")
            return real_write(fd, data)

        def wrapped_fsync(fd: int) -> None:
            kind = "dir fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync"
            bump(kind)
            real_fsync(fd)

        def wrapped_link(
            src: str | os.PathLike[str], dst: str | os.PathLike[str], *,
            src_dir_fd: int | None = None, dst_dir_fd: int | None = None,
            follow_symlinks: bool = True,
        ) -> None:
            bump("link")
            real_link(
                src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )

        def wrapped_unlink(path: str | os.PathLike[str], *, dir_fd: int | None = None) -> None:
            bump("unlink")
            if dir_fd is None:
                real_unlink(path)
            else:
                real_unlink(path, dir_fd=dir_fd)

        def wrapped_chmod(
            path: str | os.PathLike[str], mode: int, *, follow_symlinks: bool = True,
        ) -> None:
            bump("chmod")
            real_chmod(path, mode, follow_symlinks=follow_symlinks)

        def wrapped_lstat(
            path: str | os.PathLike[str], *, dir_fd: int | None = None,
        ) -> os.stat_result:
            bump("stat")
            if dir_fd is None:
                return real_lstat(path)
            return real_lstat(path, dir_fd=dir_fd)

        def wrapped_read(fd: int, length: int) -> bytes:
            bump("read")
            return real_read(fd, length)

        monkeypatch.setattr(os, "open", wrapped_open)
        monkeypatch.setattr(os, "write", wrapped_write)
        monkeypatch.setattr(os, "fsync", wrapped_fsync)
        monkeypatch.setattr(os, "link", wrapped_link)
        monkeypatch.setattr(os, "unlink", wrapped_unlink)
        monkeypatch.setattr(os, "chmod", wrapped_chmod)
        monkeypatch.setattr(os, "lstat", wrapped_lstat)
        monkeypatch.setattr(os, "read", wrapped_read)

    install(None)
    ok = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert ok.is_error is False
    assert _inbox_pages(root)[0].read_bytes() == _MARKER_BODY.encode()
    monkeypatch.undo()
    assert kinds
    summary: list[str] = []
    for index, kind in enumerate(kinds, start=1):
        trial = tmp_path / f"trial-{index}"
        _ = init_vault(trial)
        (trial / "inbox").chmod(original_mode)
        trial_server = build_server(trial, config=Config(raw={"vault_root": str(trial)}))
        install(index)
        failed = _call(trial_server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
        monkeypatch.undo()
        mode_now = stat.S_IMODE((trial / "inbox").stat().st_mode)
        pages = _inbox_pages(trial)
        payload = _error_payload(_error_text(failed)) if failed.is_error else {"code": "WRITTEN", "written": True}
        code = str(payload["code"])
        if code == "INBOX_MODE_RESTORE_FAILED":
            assert payload["code"] != "NOTHING_WRITTEN"
        elif mode_now != original_mode:
            raise AssertionError(f"mode {mode_now:04o} code {code} kind {kind} index {index} payload {payload}")
        if code == "NOTHING_WRITTEN":
            assert pages == []
            assert payload["written"] is False
        elif code in {"WRITTEN_WITH_FOLLOWUP_ERROR", "WRITTEN", "INBOX_MODE_RESTORE_FAILED"}:
            assert len(pages) == 1
            assert pages[0].read_bytes() == _MARKER_BODY.encode()
        elif code == "WRITE_OUTCOME_UNKNOWN":
            assert payload["written"] is None
            assert len(pages) <= 1
        else:
            raise AssertionError(f"unexpected code {code} at {kind}")
        retried = _call(trial_server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
        assert retried.is_error is False
        restored = _inbox_pages(trial)
        assert len(restored) == 1
        assert restored[0].read_bytes() == _MARKER_BODY.encode()
        # A failed restore is reported, not healed from the already-changed mode.
        if code != "INBOX_MODE_RESTORE_FAILED":
            assert stat.S_IMODE((trial / "inbox").stat().st_mode) == original_mode
        summary.append(f"{index}:{kind}:{code}")
    assert len(summary) == len(kinds)
    assert any(item.split(":")[1] == "link" for item in summary)
    assert any(item.split(":")[1] == "dir fsync" for item in summary)


def test_generation_pointer_replace_failure_then_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing the generation pointer replace must not mint two active pages."""
    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_replace = os.replace

    def fail_pointer(src: str | os.PathLike[str], dst: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
        if Path(dst).name == "vault":
            raise OSError(errno.EIO, "injected generation pointer")
        real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_pointer)
    failed = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] in {"NOTHING_WRITTEN", "WRITE_OUTCOME_UNKNOWN", "WRITTEN_WITH_FOLLOWUP_ERROR"}
    assert payload["code"] != "NOTHING_WRITTEN" or payload["written"] is False
    monkeypatch.setattr(os, "replace", real_replace)
    retried = _call(server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    pages = [path for path in (root / "inbox").rglob("*.md") if path.is_file() and not path.name.startswith(".")]
    bodies = [path.read_bytes() for path in pages]
    assert bodies.count(_MARKER_BODY.encode()) == 1
    assert len(pages) == 1


def test_unkeyed_publish_collision_preserves_both_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = init_vault(tmp_path / "notes").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_link = os.link
    competing: list[Path] = []

    def publish_competitor(src: Path, dst: Path) -> None:
        if not competing and Path(dst).parent == root / "inbox":
            Path(dst).write_text("concurrent note", encoding="utf-8")
            competing.append(Path(dst))
        real_link(src, dst)

    monkeypatch.setattr(os, "link", publish_competitor)
    result = _call(server, "sb_remember", {"content": "new note", "title": "ExampleAlpha"})
    assert result.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 2
    assert competing[0].read_text(encoding="utf-8") == "concurrent note"
    assert sorted(page.read_text(encoding="utf-8") for page in pages) == [
        "concurrent note", "new note",
    ]


def test_rename_fallback_success_keeps_the_published_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful renameat2 fallback publishes; it is not a follow-up error."""
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))

    def link_unsupported(
        src: str | os.PathLike[str], dst: str | os.PathLike[str], *args: object, **kwargs: object
    ) -> None:
        del src, dst, args, kwargs
        raise OSError(errno.EXDEV, "link unsupported")

    monkeypatch.setattr(os, "link", link_unsupported)
    result = _call(
        server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"}
    )
    assert result.is_error is False
    pages = _inbox_pages(root)
    assert len(pages) == 1
    assert pages[0].read_bytes() == _MARKER_BODY.encode()
    assert list((root / "inbox").glob(".*.tmp")) == []
    monkeypatch.undo()
    retried = _call(
        server, "sb_remember", {"content": _MARKER_BODY, "title": "note", "request_id": "retry-same"}
    )
    assert retried.is_error is False
    assert _inbox_pages(root) == pages


def test_linked_temporary_is_removed_on_followup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A follow-up failure must not leave the hard linked temporary behind."""
    root = tmp_path / "notes"
    _ = init_vault(root)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    failed = _call(server, "sb_remember", {"content": "kept", "title": "note", "request_id": "retry-same"})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert payload["cause"] == "RememberFollowupError"
    assert payload["request_id"] == "retry-same"
    page = root / str(payload["path"])
    assert page.is_file()
    assert page.stat().st_nlink == 1
    assert list((root / "inbox").glob(".*.tmp")) == []
    monkeypatch.setattr(os, "fsync", real_fsync)
    retried = _call(server, "sb_remember", {"content": "kept", "title": "note", "request_id": "retry-same"})
    assert retried.is_error is False
    kept = [item for item in (root / "inbox").rglob("*.md") if item.is_file() and item.read_bytes() == b"kept"]
    assert kept == [page]


def test_delivery_digest_mismatch_is_not_evidence(tmp_path: Path) -> None:
    """An artifact of a different request never reconciles this submission."""
    from sb.write_delivery import classify_delivery

    request_root = tmp_path / "requests"
    pending = request_root / "pending"
    pending.mkdir(parents=True)
    identity = "memreq:pos:v2:" + "ab" * 32
    envelope = {
        "schema_version": 2,
        "state": "pending",
        "accepted_at": "2026-08-31T00:00:00.000Z",
        "request": {"request_id": identity, "request_digest": "sha256:" + "aa" * 32},
    }
    artifact = pending / f"{identity}.v2.json"
    _ = artifact.write_text(json.dumps(envelope), encoding="utf-8")
    vault = tmp_path / "vault"
    found = classify_delivery(request_root, vault, identity, 2, "sha256:" + "aa" * 32)
    assert found.evidence == "present"
    foreign = classify_delivery(request_root, vault, identity, 2, "sha256:" + "bb" * 32)
    assert foreign.evidence == "absent"
    assert foreign.request_id == identity
    _ = artifact.write_text("{}", encoding="utf-8")
    unprovable = classify_delivery(request_root, vault, identity, 2, "sha256:" + "aa" * 32)
    assert unprovable.evidence == "unknown"
    unchecked = classify_delivery(request_root, vault, identity, 2)
    assert unchecked.evidence == "present"
    database = request_root / "journal.db"
    with sqlite3.connect(database) as connection:
        _ = connection.execute(
            "CREATE TABLE requests(request_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)"
        )
        _ = connection.execute(
            "INSERT INTO requests VALUES (?, ?)",
            (
                identity,
                json.dumps({
                    "inbox_path": "pending/kept.json",
                    "request_digest": "sha256:" + "aa" * 32,
                }),
            ),
        )
    _ = artifact.unlink()
    journal = classify_delivery(request_root, vault, identity, 2, "sha256:" + "aa" * 32)
    assert journal.evidence == "present"
    assert journal.path == "pending/kept.json"
    foreign_journal = classify_delivery(request_root, vault, identity, 2, "sha256:" + "bb" * 32)
    assert foreign_journal.evidence == "absent"


def test_rejected_request_with_unrelated_digest_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected submission whose digest differs from the artifact is not written."""
    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    server = build_server(root, task30=False)
    request = write_fixture_request()
    accepted = _call(server, "sb_write_request", {"request": request})
    assert accepted.is_error is False
    forged = dict(request)
    forged["request_digest"] = "sha256:" + "cd" * 32
    failed = _call(server, "sb_write_request", {"request": forged})
    assert failed.is_error is True
    payload = _error_payload(_error_text(failed))
    assert payload["written"] is False
    assert payload["delivery"] == "not_written"
    assert payload["code"] == "WRITE_REQUEST_IDENTITY_INVALID"
    assert len(list((tmp_path / ".requests" / "pending").glob("*.json"))) == 1


def test_maintain_failure_before_accept_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-accept maintenance failure is a strict JSON not_written answer."""
    from sb.provider_lifecycle import ProviderLifecycle

    root = init_vault(tmp_path / "vault").root
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)

    def broken_maintain(self: ProviderLifecycle, now: object) -> object:
        del self, now
        raise OSError("injected maintain")

    monkeypatch.setattr(ProviderLifecycle, "maintain", broken_maintain)
    server = build_server(root, task30=False)
    request = write_fixture_request()
    result = _call(server, "sb_write_request", {"request": request})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["delivery"] == "not_written"
    assert payload["written"] is False
    assert payload["cause"] == "OSError"
    assert list((tmp_path / ".requests" / "pending").glob("*.json")) == []


def test_remember_maintain_failure_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-publish maintenance failure carries the known explicit request id."""
    from sb.provider_lifecycle import ProviderLifecycle

    root = tmp_path / "notes"
    _ = init_vault(root)

    def broken_maintain(self: ProviderLifecycle, now: object) -> object:
        del self, now
        raise OSError("injected maintain")

    monkeypatch.setattr(ProviderLifecycle, "maintain", broken_maintain)
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    result = _call(server, "sb_remember", {"content": "m", "title": "note", "request_id": "retry-same"})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["delivery"] == "not_written"
    assert payload["written"] is False
    assert payload["request_id"] == "retry-same"
    assert _inbox_pages(root) == []


def test_mutation_construction_failure_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mutation service construction failure is not the generic MCP error."""
    from sb.generation_runtime import GenerationMutationService

    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))

    def broken_from_config(cls: type, config: object, **kwargs: object) -> object:
        del cls, config, kwargs
        raise OSError("injected construction")

    monkeypatch.setattr(GenerationMutationService, "from_config", classmethod(broken_from_config))
    result = _call(server, "sb_remember", {"content": "m", "title": "note", "request_id": "retry-same"})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "NOTHING_WRITTEN"
    assert payload["written"] is False
    assert payload["request_id"] == "retry-same"


def test_mutation_close_failure_after_write_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close failure after activation still reports the written page."""
    from sb.generation_runtime import GenerationMutationService

    root = init_vault(tmp_path / "vault").root
    server = build_server(root, config=Config(raw={"vault_root": str(root)}))
    closes = {"count": 0}

    def broken_close(self: GenerationMutationService) -> None:
        del self
        closes["count"] += 1
        raise OSError("injected close")

    monkeypatch.setattr(GenerationMutationService, "close", broken_close)
    result = _call(server, "sb_remember", {"content": "kept-close", "title": "note", "request_id": "retry-same"})
    assert result.is_error is True
    payload = _error_payload(_error_text(result))
    assert payload["code"] == "WRITTEN_WITH_FOLLOWUP_ERROR"
    assert payload["written"] is True
    assert payload["request_id"] == "retry-same"
    assert closes["count"] == 1
    notes = [path for path in (root / "inbox").rglob("*.md") if path.is_file()]
    assert len(notes) == 1
    assert notes[0].read_text(encoding="utf-8") == "kept-close"


def test_explicit_retry_after_acknowledgement_returns_the_consumed_page(tmp_path: Path) -> None:
    """A consumed explicit page is returned from durable evidence, never reminted."""
    import shutil

    from sb.connectors.inbox_documents import InboxDocumentsAdapter
    from sb.store.cas import ContentAddressedStore
    from sb.store.ledger import Ledger, SourceItem

    root = tmp_path / "notes"
    _ = init_vault(root)
    rel = write_inbox(root, "consumed body", "note", "retry-same")
    name = Path(rel).name
    body = (root / rel).read_bytes()
    adapter = InboxDocumentsAdapter(root=root / "inbox", source_id="inbox")
    committed = [ref for ref, _payload, meta in adapter.scan("0") if not meta.get("skip_reason")]
    adapter.acknowledge(committed)
    retried = write_inbox(root, "consumed body", "note", "retry-same")
    assert retried == Path("inbox") / ".done" / name
    assert (root / retried).read_bytes() == body
    assert list((root / "inbox").glob("*.md")) == []
    shutil.rmtree(root / "inbox" / ".done")
    digest = ContentAddressedStore(root).put(body)
    with Ledger(root) as ledger:
        _ = ledger.upsert_source_item(
            SourceItem("inbox", name, f"{name}:{digest}", digest, "run", "run")
        )
    again = write_inbox(root, "consumed body", "note", "retry-same")
    assert again == Path("inbox") / ".done" / name
    assert list((root / "inbox").glob("*.md")) == []


def test_web_remember_outcome_errors_answer_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outcome errors at the web write boundary stay JSON responses."""
    import sb.web as web_module
    from sb.inbox import RememberFollowupError, RememberOutcomeUnknown
    from tests.test_web import _ready, _request, _running

    config, _root = _ready(tmp_path)
    for error in (
        RememberFollowupError(Path("inbox/x.md")),
        RememberOutcomeUnknown(Path("inbox/x.md")),
    ):
        def broken_write_inbox(_root: Path, _content: str, _title: str | None, failure=error) -> Path:
            raise failure

        monkeypatch.setattr(web_module, "write_inbox", broken_write_inbox)
        with _running(config) as base:
            status, payload = _request(
                base + "/api/remember", method="POST", payload={"content": "kept", "title": "note"}
            )
        assert status == 500
        assert payload == {"error": type(error).__name__}
        monkeypatch.undo()


def test_cli_remember_outcome_errors_exit_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Outcome errors at the CLI write boundary print the code and exit 1."""
    from sb.cli import main
    from sb.generation_runtime import GenerationMutationService
    from sb.inbox import RememberFollowupError, RememberOutcomeUnknown

    root = tmp_path / "vault"
    _ = init_vault(root)
    cfg = tmp_path / "config.toml"
    _ = cfg.write_text(
        f'vault_root = "{root}"\nstate_root = "{tmp_path / "state"}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("SB_CONFIG", str(cfg))
    cases = (
        (RememberFollowupError(Path("inbox/x.md")), "WRITTEN_WITH_FOLLOWUP_ERROR"),
        (RememberOutcomeUnknown(Path("inbox/x.md")), "WRITE_OUTCOME_UNKNOWN"),
    )
    for error, code in cases:
        monkeypatch.setattr(
            GenerationMutationService,
            "remember",
            _remember_failure(error),
        )
        assert main(["remember", "kept", "--title", "note", "--request-id", "retry-same"]) == 1
        captured = capsys.readouterr()
        assert code in captured.err
        monkeypatch.undo()


def _remember_failure(error: BaseException) -> Callable[..., Path]:
    """Patch GenerationMutationService.remember to surface one outcome error."""

    def remember(
        self: object,
        content: str,
        title: str | None,
        now: object,
        request_id: object = None,
        failure: BaseException = error,
    ) -> Path:
        del self, content, title, now, request_id
        raise failure

    return remember
