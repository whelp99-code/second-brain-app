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
