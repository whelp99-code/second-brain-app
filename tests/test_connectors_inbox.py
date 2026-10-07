"""Inbox document adapter: parser routing, size guard, done-move, resume."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from sb.connectors import discover_adapters
from sb.connectors.base import AcknowledgingSourceAdapter, ItemMeta
from sb.connectors.inbox_documents import ADAPTER_ID as INBOX_ID
from sb.connectors.inbox_documents import MAX_INBOX_BYTES, create
from sb.contracts import SourceRef

OVERSIZE_BYTES = MAX_INBOX_BYTES + 1


@dataclass(frozen=True, slots=True)
class _Cfg:
    source_roots: list[dict[str, str]]
    vault_root: str = "/nonexistent-vault"


def _cfg(root: Path, source_id: str = "inbox") -> _Cfg:
    return _Cfg([{"id": source_id, "adapter": INBOX_ID, "root": str(root)}])


def _delivered(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[tuple[str, bytes]]:
    return [(ref.source_uri, body) for ref, body, meta in items if "skip_reason" not in meta]


def _skipped(items: Sequence[tuple[SourceRef, bytes, ItemMeta]]) -> list[str]:
    return [str(meta.get("skip_reason")) for _r, _b, meta in items if "skip_reason" in meta]


def _text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [4 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    stream = f"BT /F1 12 Tf 72 120 Td ({escaped}) Tj ET".encode("ascii")
    objects.append(
        b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        + b"/Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >> endobj\n"
    )
    objects.append(
        f"5 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream\nendobj\n"
    )
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray(header)
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)
    xref_pos = len(body)
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()]
    xref.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(body) + b"".join(xref) + trailer


def test_inbox_routes_markdown_fixture_through_parser_registry(tmp_path: Path) -> None:
    # Given: a vault inbox containing a markdown fixture.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _ = (inbox / "note.md").write_text("visible markdown body\n", encoding="utf-8")
    adapter = create(_cfg(inbox))

    # When: the adapter scans the inbox.
    items = list(adapter.scan(None))

    # Then: parser_for(.md) text is delivered under a unique SourceRef.
    delivered = _delivered(items)
    assert delivered == [("note.md", b"visible markdown body\n")]
    assert all(ref.source_id == "inbox" for ref, _b, _m in items)


def test_inbox_routes_pdf_fixture_through_parser_registry(tmp_path: Path) -> None:
    # Given: a vault inbox containing a synthesized extractable PDF.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _ = (inbox / "page.pdf").write_bytes(_text_pdf("visible-pdf-page"))
    adapter = create(_cfg(inbox))

    # When: the adapter scans the inbox.
    items = list(adapter.scan(None))

    # Then: parser_for(.pdf) yields the page text.
    blob = b"\n".join(body for _uri, body in _delivered(items))
    assert b"visible-pdf-page" in blob
    assert _delivered(items)[0][0] == "page.pdf"


def test_inbox_moves_parsed_file_to_done_after_success(tmp_path: Path) -> None:
    # Given: one successfully parseable inbox document.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "keep.md"
    _ = source.write_text("move-me\n", encoding="utf-8")
    adapter = create(_cfg(inbox))

    # When: the adapter ingests the document.
    items = list(adapter.scan(None))

    # Scanning is read-only; only durable intake acknowledgment permits the move.
    assert _delivered(items)
    assert source.is_file()
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    adapter.acknowledge(tuple(ref for ref, _body, _meta in items))
    assert not source.exists()
    assert (inbox / ".done" / "keep.md").is_file()
    assert (inbox / ".done" / "keep.md").read_text(encoding="utf-8") == "move-me\n"


def test_acknowledge_preserves_previous_file_with_same_name(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    done = inbox / ".done"
    done.mkdir(parents=True)
    _ = (done / "keep.md").write_text("previous original\n")
    source = inbox / "keep.md"
    _ = source.write_text("new original\n")
    adapter = create(_cfg(inbox))
    items = list(adapter.scan(None))
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    adapter.acknowledge(tuple(ref for ref, _, _ in items))
    assert not source.exists()
    assert (done / "keep.md").read_text() == "previous original\n"
    assert sorted(path.read_text() for path in done.iterdir()) == [
        "new original\n", "previous original\n"]


@pytest.mark.parametrize("collision", [False, True])
def test_acknowledge_resumes_published_file_after_unlink_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collision: bool):

    inbox = tmp_path / "inbox"
    done = inbox / ".done"
    done.mkdir(parents=True)
    if collision:
        _ = (done / "keep.md").write_text("previous\n")
    source = inbox / "keep.md"
    _ = source.write_text("current\n")
    adapter = create(_cfg(inbox))
    items = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    refs = tuple(ref for ref, _, _ in items)

    def fail_unlink(_path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *, dir_fd: int | None = None) -> None:
        del dir_fd
        raise OSError("simulated failure after publication")

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_unlink)
        with pytest.raises(OSError, match="after publication"):
            adapter.acknowledge(refs)
    assert source.read_text() == "current\n"
    published = sorted(path.name for path in done.iterdir())
    assert len(published) == (2 if collision else 1)
    resumed = create(_cfg(inbox))
    assert list(resumed.scan(cursor)) == []
    assert isinstance(resumed, AcknowledgingSourceAdapter)
    resumed.acknowledge(refs)
    assert not source.exists()
    assert sorted(path.name for path in done.iterdir()) == published
    assert sorted(path.read_text() for path in done.iterdir()) == (
        ["current\n", "previous\n"] if collision else ["current\n"])


@pytest.mark.parametrize("replace_inode", [False, True])
def test_acknowledge_rejects_change_after_verified_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_inode: bool):
    import sb.connectors.inbox_documents as module

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "note.md"
    _ = source.write_text("committed original\n")
    adapter = create(_cfg(inbox))
    items = list(adapter.scan(None))
    cursor = adapter.next_cursor()
    move = module.move_done

    def changed(root: Path, rel: str, version: str, verified: os.stat_result) -> None:
        if replace_inode:
            replacement = inbox / "replacement.md"
            _ = replacement.write_text("uncommitted replacement\n")
            _ = replacement.replace(source)
        else:
            _ = source.write_text("uncommitted replacement\n")
        return move(root, rel, version, verified)

    assert isinstance(adapter, AcknowledgingSourceAdapter)
    with monkeypatch.context() as patch:
        patch.setattr(module, "move_done", changed)
        with pytest.raises(OSError, match="changed"):
            adapter.acknowledge(tuple(ref for ref, _, _ in items))
    assert source.read_text() == "uncommitted replacement\n"
    assert list((inbox / ".done").iterdir()) == []
    resumed = list(adapter.scan(cursor))
    assert len(resumed) == 1
    assert resumed[0][0].source_version != items[0][0].source_version


def test_inbox_rejects_oversize_file_and_leaves_it_in_place(tmp_path: Path) -> None:
    # Given: an 11 MiB inbox file above the 10 MiB cap.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    huge = inbox / "huge.md"
    _ = huge.write_bytes(b"x" * OVERSIZE_BYTES)
    adapter = create(_cfg(inbox))

    # When: the adapter scans the oversize file.
    items = list(adapter.scan(None))

    # Then: the file is rejected with a reason and remains in inbox/.
    assert "size-limit" in _skipped(items)
    assert _delivered(items) == []
    assert huge.is_file()
    assert not (inbox / ".done" / "huge.md").exists()


def test_inbox_resume_yields_zero_when_parsed_and_rejected_unchanged(tmp_path: Path) -> None:
    # Given: a scanned inbox with one ingested file and one rejected oversize file.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _ = (inbox / "ok.md").write_text("first\n", encoding="utf-8")
    huge = inbox / "huge.md"
    _ = huge.write_bytes(b"y" * OVERSIZE_BYTES)
    adapter = create(_cfg(inbox))
    first = list(adapter.scan(None))
    assert _delivered(first)
    assert "size-limit" in _skipped(first)
    cursor = adapter.next_cursor()

    # When: the inbox is rescanned with the returned cursor.
    resume = list(adapter.scan(cursor))

    # Then: zero items are emitted and the rejected file is still in place.
    assert resume == []
    assert huge.is_file()
    assert "huge.md" in adapter.next_cursor()


def test_inbox_rejects_non_utf8_text_and_leaves_it_in_place(tmp_path: Path) -> None:
    # Given: a markdown file that is not UTF-8.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bad = inbox / "latin.md"
    _ = bad.write_bytes(b"caf\xe9\n")
    adapter = create(_cfg(inbox))

    # When: the adapter scans the non-UTF-8 text file.
    items = list(adapter.scan(None))

    # Then: the file is rejected and remains in inbox/.
    assert _skipped(items)
    assert _delivered(items) == []
    assert bad.is_file()


def test_inbox_skips_symlink_and_does_not_read_outside_target(tmp_path: Path) -> None:
    # Given: an inbox symlink pointing at a file outside the inbox.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = tmp_path / "secret.md"
    _ = outside.write_text("OUTSIDE_SECRET\n", encoding="utf-8")
    link = inbox / "alias.md"
    _ = link.symlink_to(outside)
    adapter = create(_cfg(inbox))

    # When: the adapter scans the inbox.
    items = list(adapter.scan(None))

    # Then: the symlink is skipped, outside bytes are not delivered, and nothing is moved.
    assert "symlink" in _skipped(items)
    assert b"OUTSIDE_SECRET" not in b"\n".join(body for _u, body in _delivered(items))
    assert link.is_symlink()
    assert outside.is_file()
    assert not (inbox / ".done" / "alias.md").exists()


def test_inbox_does_not_write_outside_inbox_when_nested_file_succeeds(tmp_path: Path) -> None:
    # Given: a nested inbox document under a subdirectory.
    inbox = tmp_path / "inbox"
    nested = inbox / "nested"
    nested.mkdir(parents=True)
    _ = (nested / "inner.md").write_text("nested-ok\n", encoding="utf-8")
    adapter = create(_cfg(inbox))

    # When: the adapter ingests the nested document.
    items = list(adapter.scan(None))

    # Then: explicit acknowledgment writes only inside inbox/.done/.
    assert _delivered(items) == [("nested/inner.md", b"nested-ok\n")]
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    adapter.acknowledge(tuple(ref for ref, _body, _meta in items))
    assert (inbox / ".done" / "nested" / "inner.md").is_file()
    assert set(tmp_path.iterdir()) == {inbox}


def test_inbox_ignores_memory_request_queue(tmp_path: Path) -> None:
    # Given: a pending write request beneath the reserved queue directory.
    inbox = tmp_path / "inbox"
    pending = inbox / ".requests" / "pending"
    pending.mkdir(parents=True)
    _ = (pending / "memreq.json").write_text('{"state":"pending"}\n', encoding="utf-8")
    adapter = create(_cfg(inbox))

    # When: generic inbox intake scans the inbox.
    items = list(adapter.scan(None))

    # Then: request files are neither parsed nor moved by the connector.
    assert items == []
    assert (pending / "memreq.json").is_file()
    assert not (inbox / ".done").exists()


def test_registry_auto_discovers_inbox_documents_adapter() -> None:
    # Given: the real sb.connectors package after inbox_documents exists.
    from sb.config import load_config

    # When: adapters are discovered.
    registry = discover_adapters(load_config())

    # Then: the inbox adapter is registered under its unique ADAPTER_ID.
    assert INBOX_ID in registry
    assert registry[INBOX_ID].source_id


def test_acknowledgment_does_not_move_changed_input(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    _ = source.write_text("old content")
    adapter = create(_cfg(tmp_path))
    scanned = list(adapter.scan(None))
    _ = source.write_text("new content must remain pending")
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    adapter.acknowledge(tuple(ref for ref, _body, _meta in scanned))
    assert source.read_text() == "new content must remain pending"
    assert not (tmp_path / ".done").exists()


def test_fifo_is_skipped_without_opening_a_writer(tmp_path: Path):
    import os
    import subprocess
    import sys

    os.mkfifo(tmp_path / 'blocked.txt')
    code = """
import sys
from pathlib import Path
from sb.connectors.inbox_documents import create
from tests.test_connectors_inbox import _cfg, _skipped
adapter = create(_cfg(Path(sys.argv[1])))
assert _skipped(list(adapter.scan(None))) == ['unreadable']
assert list(adapter.scan(adapter.next_cursor())) == []
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], timeout=10, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_file_replacement_before_open_is_not_ingested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import os

    import sb.connectors.inbox_documents as module

    path = tmp_path / 'note.txt'
    _ = path.write_text('original')
    original = module.read_regular

    def replace_before_read(target: Path, metadata: os.stat_result) -> bytes:
        replacement = tmp_path / 'replacement'
        _ = replacement.write_text('replaced')
        os.replace(replacement, target)
        return original(target, metadata)

    monkeypatch.setattr(module, 'read_regular', replace_before_read)
    adapter = create(_cfg(tmp_path))
    assert _skipped(list(adapter.scan(None))) == ['unreadable']
    monkeypatch.setattr(module, 'read_regular', original)
    assert _delivered(list(adapter.scan(adapter.next_cursor()))) == [('note.txt', b'replaced')]


def test_acknowledge_does_not_follow_done_directory_symlink(tmp_path: Path):
    import pytest

    from sb.connectors.base import AcknowledgingSourceAdapter

    inbox = tmp_path / 'inbox'
    outside = tmp_path / 'outside'
    inbox.mkdir()
    outside.mkdir()
    _ = (inbox / 'note.txt').write_text('keep inside inbox')
    adapter = create(_cfg(inbox))
    assert isinstance(adapter, AcknowledgingSourceAdapter)
    items = list(adapter.scan(None))
    (inbox / '.done').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        adapter.acknowledge(tuple(ref for ref, _, _ in items))
    assert (inbox / 'note.txt').read_text() == 'keep inside inbox'
    assert list(outside.iterdir()) == []
