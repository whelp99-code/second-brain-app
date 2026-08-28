"""Desktop upload staging: safety, idempotency, and inbox compatibility."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path

import pytest

from sb.uploads import MAX_UPLOAD_BYTES, UploadRejected, accept_upload, supported_suffixes


def test_accept_upload_stages_supported_file_under_vault_inbox(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    payload = b"# contract\nWednesday delivery\n"

    receipt = accept_upload(
        root,
        "계약서.md",
        payload,
        device_id="JaeMin-Mac",
        relative_path="Projects/계약서.md",
        declared_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert receipt.state == "queued"
    assert receipt.filename == "계약서.md"
    assert receipt.relative_path == "Projects/계약서.md"
    assert receipt.device_id == "JaeMin-Mac"
    staged = root / receipt.inbox_path
    assert staged.is_file()
    assert staged.read_bytes() == payload
    assert staged.stat().st_mode & 0o777 == 0o600


def test_accept_upload_retry_is_idempotent_before_ingest(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    payload = b"same bytes"

    first = accept_upload(root, "note.txt", payload, relative_path="note.txt")
    second = accept_upload(root, "note.txt", payload, relative_path="note.txt")

    assert first.upload_id == second.upload_id
    assert first.state == "queued"
    assert second.state == "already-queued"
    assert len(tuple((root / "inbox" / "uploads").rglob("*.txt"))) == 1


def test_accept_upload_retry_detects_document_moved_to_done(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    payload = b"already processed"
    first = accept_upload(root, "note.txt", payload, device_id="mac", relative_path="note.txt")
    queued = root / first.inbox_path
    relative_to_inbox = queued.relative_to(root / "inbox")
    done = root / "inbox" / ".done" / relative_to_inbox
    done.parent.mkdir(parents=True, exist_ok=True)
    _ = queued.replace(done)

    second = accept_upload(root, "note.txt", payload, device_id="mac", relative_path="note.txt")

    assert second.state == "already-ingested"
    assert root / second.inbox_path == done


def test_same_content_at_two_relative_paths_has_distinct_upload_identity(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    payload = b"same document body"

    left = accept_upload(root, "note.txt", payload, relative_path="A/note.txt")
    right = accept_upload(root, "note.txt", payload, relative_path="B/note.txt")

    assert left.upload_id != right.upload_id
    assert left.inbox_path != right.inbox_path


def test_unicode_normalization_does_not_create_duplicate_uploads(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    payload = b"normalized"
    composed = "계약서.md"
    decomposed = unicodedata.normalize("NFD", composed)

    first = accept_upload(root, composed, payload, relative_path=f"Docs/{composed}")
    second = accept_upload(root, decomposed, payload, relative_path=f"Docs/{decomposed}")

    assert first.upload_id == second.upload_id
    assert second.state == "already-queued"


def test_accept_upload_rejects_symlink_escape_from_inbox(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    outside = tmp_path / "outside"
    (root / "inbox").mkdir(parents=True)
    outside.mkdir()
    (root / "inbox" / "uploads").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UploadRejected, match="escapes inbox"):
        _ = accept_upload(root, "note.txt", b"safe", relative_path="note.txt")

    assert tuple(outside.iterdir()) == ()


def test_accept_upload_detects_tampered_existing_stage(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    first = accept_upload(root, "note.txt", b"original", relative_path="note.txt")
    _ = (root / first.inbox_path).write_bytes(b"tampered")

    with pytest.raises(UploadRejected, match="tampered"):
        _ = accept_upload(root, "note.txt", b"original", relative_path="note.txt")


@pytest.mark.parametrize(
    "filename,relative_path",
    (
        ("../secret.md", "secret.md"),
        ("folder/secret.md", "secret.md"),
        ("secret.md", "../secret.md"),
        ("secret.md", "/absolute/secret.md"),
        ("secret.md", "folder/./secret.md"),
    ),
)
def test_accept_upload_rejects_path_escape(
    tmp_path: Path, filename: str, relative_path: str
) -> None:
    with pytest.raises(UploadRejected):
        _ = accept_upload(tmp_path / "vault", filename, b"safe", relative_path=relative_path)


def test_accept_upload_rejects_unsupported_suffix(tmp_path: Path) -> None:
    with pytest.raises(UploadRejected, match="unsupported suffix"):
        _ = accept_upload(tmp_path / "vault", "archive.zip", b"PK", relative_path="archive.zip")


def test_accept_upload_rejects_empty_and_oversized_files(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    with pytest.raises(UploadRejected, match="empty"):
        _ = accept_upload(root, "empty.txt", b"")
    with pytest.raises(UploadRejected, match="exceeds"):
        _ = accept_upload(root, "large.txt", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_accept_upload_rejects_declared_digest_mismatch(tmp_path: Path) -> None:
    with pytest.raises(UploadRejected, match="mismatch"):
        _ = accept_upload(
            tmp_path / "vault",
            "note.txt",
            b"actual",
            declared_sha256="0" * 64,
        )


def test_supported_suffixes_match_document_intake_contract() -> None:
    assert supported_suffixes() == (
        ".docx",
        ".hwpx",
        ".json",
        ".md",
        ".pdf",
        ".txt",
        ".xlsx",
        ".yaml",
    )
