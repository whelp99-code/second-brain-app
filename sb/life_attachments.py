"""Bounded inline attachments: no arbitrary CAS hash grants read authority.

Only bytes supplied with the event create attachment references. Consumers must
resolve them through an authorized current event, never directly by a hash.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from hashlib import sha256
from pathlib import PurePosixPath

from sb.effect_values import JsonInput
from sb.life_contracts import AttachmentRefV1, LifeInputError

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ENVELOPE_BYTES = 16 * 1024 * 1024
ATTACHMENT_STATES = frozenset({"stored", "too_large", "untranscribed", "quarantined"})


def attachment_state(
    *, size: int, mime: str, signature_ok: bool, transcribed: bool = False
) -> str:
    """Classify one attachment. Audio is not stored as a finished memory."""
    if type(size) is not int or size > MAX_ATTACHMENT_BYTES:
        return "too_large"
    if not signature_ok or mime not in MIMES or size <= 0:
        return "quarantined"
    if mime.startswith("audio/") and not transcribed:
        return "untranscribed"
    return "stored"
OFFICE_PARTS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word/document.xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xl/workbook.xml",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt/presentation.xml",
}


def _office_signature(data: bytes, mime: str) -> bool:
    """Inspect bounded ZIP metadata only; never extract or execute Office content."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if not 1 <= len(entries) <= 2000 or len(names) != len(entries):
                return False
            if "[Content_Types].xml" not in names or OFFICE_PARTS[mime] not in names:
                return False
            if sum(entry.file_size for entry in entries) > 64 * 1024 * 1024:
                return False
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or entry.flag_bits & 1
                    or entry.external_attr >> 16 & 0o170000 == 0o120000
                    or not 0 <= entry.file_size <= 32 * 1024 * 1024
                ):
                    return False
            return True
    except (zipfile.BadZipFile, ValueError, OSError):
        return False


MIMES = frozenset(
    {
        *OFFICE_PARTS,
        "image/png",
        "image/jpeg",
        "image/heic",
        "image/heif",
        "audio/wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/aac",
        "application/pdf",
        "application/json",
        "message/rfc822",
        "text/plain",
        "text/markdown",
        "text/calendar",
        "text/vtt",
    }
)


def _signature(data: bytes, mime: str) -> bool:
    if mime in OFFICE_PARTS:
        return _office_signature(data, mime)
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime in {"image/heic", "image/heif", "audio/mp4"}:
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if mime == "audio/wav":
        return data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if mime in {"audio/mpeg", "audio/aac"}:
        return (
            data.startswith(b"ID3") or len(data) > 1 and data[0] == 255 and data[1] & 0xE0 == 0xE0
        )
    if mime == "application/pdf":
        return data.startswith(b"%PDF-")
    if mime.startswith("text/") or mime == "application/json":
        try:
            _ = data.decode("utf-8")
            return b"\0" not in data
        except UnicodeError:
            return False
    return mime == "message/rfc822" and b"\0" not in data


def decode_attachments(value: JsonInput) -> tuple[tuple[AttachmentRefV1, bytes], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 4:
        raise LifeInputError("LIFE_ATTACHMENT_INVALID")
    results: list[tuple[AttachmentRefV1, bytes]] = []
    total = 0
    for row in value:
        if not isinstance(row, dict) or set(row) - {"name", "mime", "content_base64", "sha256"}:
            raise LifeInputError("LIFE_ATTACHMENT_INVALID")
        name, mime, encoded = row.get("name"), row.get("mime"), row.get("content_base64")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.encode()) <= 240
            or name.startswith(".")
            or PurePosixPath(name).name != name
            or any(c in name for c in "\\/:\0\r\n")
            or name.rstrip(". ") != name
            or any(ord(c) < 32 for c in name)
            or not isinstance(mime, str)
            or mime not in MIMES
            or not isinstance(encoded, str)
            or len(encoded) > (MAX_ATTACHMENT_BYTES + 2) // 3 * 4
        ):
            raise LifeInputError("LIFE_ATTACHMENT_INVALID")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, UnicodeError, ValueError) as exc:
            raise LifeInputError("LIFE_ATTACHMENT_INVALID") from exc
        total += len(raw)
        if not raw or total > MAX_ATTACHMENT_BYTES:
            raise LifeInputError("LIFE_ATTACHMENT_TOO_LARGE")
        if not _signature(raw, mime):
            raise LifeInputError("LIFE_ATTACHMENT_MIME_MISMATCH")
        digest = sha256(raw).hexdigest()
        declared = row.get("sha256", digest)
        if (
            not isinstance(declared, str)
            or re.fullmatch(r"[0-9a-f]{64}", declared) is None
            or declared != digest
        ):
            raise LifeInputError("LIFE_ATTACHMENT_DIGEST_MISMATCH")
        results.append((AttachmentRefV1(name=name, mime=mime, size=len(raw), sha256=digest), raw))
    return tuple(results)


def inline(name: str, mime: str, data: bytes) -> dict[str, str]:
    encoded = {
        "name": name,
        "mime": mime,
        "content_base64": base64.b64encode(data).decode(),
        "sha256": sha256(data).hexdigest(),
    }
    _ = decode_attachments([encoded])
    return encoded
