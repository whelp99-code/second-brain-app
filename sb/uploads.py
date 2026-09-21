"""Safe, idempotent file intake for desktop clients.

Uploaded documents are staged below ``<vault>/inbox/uploads`` so the existing
``inbox-documents`` connector remains the single ingestion path.  The upload
identity includes the client device and relative source path, allowing the same
bytes at two different paths to remain distinguishable while retries are
idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final, Literal, TypedDict, override

from sb.connectors.inbox_documents import MAX_INBOX_BYTES
from sb.parsers import UnsupportedSuffix, parser_for
from sb.store.cas import ContentAddressedStore

MAX_UPLOAD_BYTES: Final = MAX_INBOX_BYTES
MAX_UPLOAD_REQUEST_BYTES: Final = ((MAX_UPLOAD_BYTES + 2) // 3) * 4 + 64 * 1024
MAX_RELATIVE_PATH_CHARS: Final = 1024
_SUPPORTED_SUFFIXES: Final = (".docx", ".hwpx", ".json", ".md", ".pdf", ".txt", ".xlsx", ".yaml")
_SAFE_COMPONENT: Final = re.compile(r"[^0-9A-Za-z가-힣._-]+")
_HEX_64: Final = re.compile(r"[0-9a-f]{64}")

type UploadState = Literal["queued", "already-queued", "already-ingested"]


class UploadReceiptDict(TypedDict):
    upload_id: str
    state: UploadState
    inbox_path: str
    content_sha256: str
    bytes: int
    filename: str
    relative_path: str
    device_id: str


class RetractReceiptDict(TypedDict):
    deleted: bool
    indexed: bool
    restored: bool
    receipt_id: str
    checked_at: str
    upload_id: str


@dataclass(frozen=True, slots=True)
class UploadRejected(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    upload_id: str
    state: UploadState
    inbox_path: Path
    content_sha256: str
    size: int
    filename: str
    relative_path: str
    device_id: str

    def as_dict(self) -> UploadReceiptDict:
        return {
            "upload_id": self.upload_id,
            "state": self.state,
            "inbox_path": self.inbox_path.as_posix(),
            "content_sha256": self.content_sha256,
            "bytes": self.size,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "device_id": self.device_id,
        }


def supported_suffixes() -> tuple[str, ...]:
    """Return the stable desktop upload allowlist."""
    return _SUPPORTED_SUFFIXES


def accept_upload(
    root: Path,
    filename: str,
    content: bytes,
    *,
    device_id: str = "mac",
    relative_path: str | None = None,
    declared_sha256: str | None = None,
) -> UploadReceipt:
    """Atomically stage one supported document in the vault inbox.

    Repeating the same device/path/content upload returns the existing state and
    never writes a second document.  A document already moved by the inbox
    connector is reported as ``already-ingested``.
    """
    if not content:
        raise UploadRejected("file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"file exceeds {MAX_UPLOAD_BYTES} bytes")

    safe_filename = _filename(filename)
    source_path = _relative_path(relative_path or safe_filename)
    safe_device = _component(device_id, "device")
    suffix = Path(safe_filename).suffix.lower()
    try:
        _ = parser_for(suffix)
    except UnsupportedSuffix as exc:
        raise UploadRejected(str(exc)) from exc

    digest = hashlib.sha256(content).hexdigest()
    if declared_sha256 is not None:
        normalized = declared_sha256.strip().lower()
        if _HEX_64.fullmatch(normalized) is None:
            raise UploadRejected("content_sha256 must be 64 lowercase hex characters")
        if normalized != digest:
            raise UploadRejected("content_sha256 mismatch")

    identity = hashlib.sha256(f"{safe_device}\0{source_path}\0{digest}".encode()).hexdigest()
    vault = root.expanduser().resolve()
    existing = read_retract_receipt(vault, _receipt_id(identity))
    if existing is not None:
        raise UploadRejected("upload identity retracted")
    inbox = (vault / "inbox").resolve()
    if not inbox.is_relative_to(vault):
        raise UploadRejected("inbox escapes vault")

    rel = Path("uploads") / safe_device / identity[:2] / f"{identity}-{safe_filename}"
    queued = (inbox / rel).resolve()
    done = (inbox / ".done" / rel).resolve()
    if not queued.is_relative_to(inbox) or not done.is_relative_to(inbox):
        raise UploadRejected("upload path escapes inbox")

    state: UploadState
    if done.is_file():
        _verify_existing(done, content)
        state = "already-ingested"
        chosen = done
    elif queued.is_file():
        _verify_existing(queued, content)
        state = "already-queued"
        chosen = queued
    else:
        queued.parent.mkdir(parents=True, exist_ok=True)
        temporary = queued.with_name(f".{queued.name}.{os.getpid()}.tmp")
        try:
            _ = temporary.write_bytes(content)
            _ = temporary.chmod(0o600)
            os.replace(temporary, queued)
        finally:
            if temporary.exists():
                temporary.unlink()
        state = "queued"
        chosen = queued

    return UploadReceipt(
        upload_id=identity,
        state=state,
        inbox_path=chosen.relative_to(vault),
        content_sha256=digest,
        size=len(content),
        filename=safe_filename,
        relative_path=source_path,
        device_id=safe_device,
    )


def _verify_existing(path: Path, expected: bytes) -> None:
    try:
        actual = path.read_bytes()
    except OSError as exc:
        raise UploadRejected("existing upload is unreadable") from exc
    if not hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest():
        raise UploadRejected("upload identity collision or tampered staged file")


def _filename(value: str) -> str:
    if "\x00" in value:
        raise UploadRejected("filename contains NUL")
    raw = unicodedata.normalize("NFC", value.strip())
    if not raw:
        raise UploadRejected("filename is required")
    pure = PurePosixPath(raw.replace("\\", "/"))
    if pure.is_absolute() or len(pure.parts) != 1 or pure.name in {"", ".", ".."}:
        raise UploadRejected("filename must not contain a path")
    safe = _component(pure.name, "file")
    if safe.startswith("."):
        safe = f"file{safe}"
    if len(safe) > 180:
        suffix = Path(safe).suffix
        stem_limit = max(1, 180 - len(suffix))
        safe = f"{Path(safe).stem[:stem_limit]}{suffix}"
    return safe


def _relative_path(value: str) -> str:
    if "\x00" in value:
        raise UploadRejected("relative_path contains NUL")
    raw = unicodedata.normalize("NFC", value.strip()).replace("\\", "/")
    if not raw or len(raw) > MAX_RELATIVE_PATH_CHARS:
        raise UploadRejected("relative_path is invalid")
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise UploadRejected("relative_path must stay within the selected folder")
    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise UploadRejected("relative_path must stay within the selected folder")
    return pure.as_posix()


def _component(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    cleaned = _SAFE_COMPONENT.sub("-", normalized).strip("-.")
    return (cleaned or fallback)[:80]


@dataclass(frozen=True, slots=True)
class RetractReceipt:
    deleted: bool
    indexed: bool
    restored: bool
    receipt_id: str
    checked_at: str
    upload_id: str
    content_sha256: str = ""

    def as_dict(self) -> RetractReceiptDict:
        return {
            "deleted": self.deleted,
            "indexed": self.indexed,
            "restored": self.restored,
            "receipt_id": self.receipt_id,
            "checked_at": self.checked_at,
            "upload_id": self.upload_id,
        }


def retract_upload(root: Path, upload_id: str) -> RetractReceipt:
    """Delete one staged upload identity and tombstone leftover CAS refs."""
    identity = _upload_identity(upload_id)
    vault = root.expanduser().resolve()
    receipt_id = _receipt_id(identity)
    checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    staged = _staged_uploads(vault, identity)
    digest = ""
    for path in staged:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        _unlink_inbox_file(path)
    leftover = _staged_uploads(vault, identity)
    for path in leftover:
        _unlink_inbox_file(path)
    prior = read_retract_receipt(vault, receipt_id)
    if prior is not None and digest == "":
        digest = prior.content_sha256
    if digest:
        ContentAddressedStore(vault).tombstone(digest)
    deleted = not _staged_uploads(vault, identity)
    receipt = RetractReceipt(
        deleted=deleted,
        indexed=False,
        restored=False,
        receipt_id=receipt_id,
        checked_at=checked_at,
        upload_id=identity,
        content_sha256=digest,
    )
    if deleted:
        _write_receipt(vault, receipt)
    return receipt


def read_retract_receipt(root: Path, receipt_id: str) -> RetractReceipt | None:
    """Return a stored retract receipt, or None when it was never written."""
    if _HEX_64.fullmatch(receipt_id) is None:
        raise UploadRejected("receipt_id must be 64 lowercase hex characters")
    path = _receipt_path(root.expanduser().resolve(), receipt_id)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UploadRejected("retract receipt is unreadable") from exc
    if not isinstance(loaded, dict):
        raise UploadRejected("retract receipt is unreadable")
    upload_id = loaded.get("upload_id")
    checked_at = loaded.get("checked_at")
    digest = loaded.get("content_sha256", "")
    if not isinstance(upload_id, str) or not isinstance(checked_at, str):
        raise UploadRejected("retract receipt is unreadable")
    if not isinstance(digest, str):
        digest = ""
    return RetractReceipt(
        deleted=True,
        indexed=False,
        restored=False,
        receipt_id=receipt_id,
        checked_at=checked_at,
        upload_id=upload_id,
        content_sha256=digest,
    )


def is_retracted_upload(root: Path, upload_id: str) -> bool:
    """True when this upload identity has a stored retract receipt."""
    if _HEX_64.fullmatch(upload_id) is None:
        return False
    return read_retract_receipt(root, _receipt_id(upload_id)) is not None


def _upload_identity(upload_id: str) -> str:
    identity = upload_id.strip().lower()
    if _HEX_64.fullmatch(identity) is None:
        raise UploadRejected("upload_id must be 64 lowercase hex characters")
    return identity


def _receipt_id(upload_id: str) -> str:
    return hashlib.sha256(f"retract\0{upload_id}".encode()).hexdigest()


def _receipt_path(vault: Path, receipt_id: str) -> Path:
    return vault / ".sb" / "retracts" / receipt_id[:2] / f"{receipt_id}.json"


def _write_receipt(vault: Path, receipt: RetractReceipt) -> None:
    path = _receipt_path(vault, receipt.receipt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**receipt.as_dict(), "content_sha256": receipt.content_sha256}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _ = temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        _ = temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    inbox_copy = vault / "inbox" / ".requests" / "retract" / f"{receipt.upload_id}.json"
    inbox_copy.parent.mkdir(parents=True, exist_ok=True)
    inbox_tmp = inbox_copy.with_name(f".{inbox_copy.name}.{os.getpid()}.tmp")
    try:
        _ = inbox_tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        _ = inbox_tmp.chmod(0o600)
        os.replace(inbox_tmp, inbox_copy)
    finally:
        if inbox_tmp.exists():
            inbox_tmp.unlink()


def _staged_uploads(vault: Path, identity: str) -> list[Path]:
    found: list[Path] = []
    inbox = vault / "inbox"
    if not inbox.is_dir():
        return found
    for base in (inbox / "uploads", inbox / ".done" / "uploads"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.name.startswith(f"{identity}-"):
                found.append(path)
    return found


def _unlink_inbox_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError as exc:
        raise UploadRejected("failed to delete staged upload") from exc
