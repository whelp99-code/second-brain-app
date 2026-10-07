"""Bounded raw Office preservation for document and iPhone shared-file imports."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from sb.life_attachments import OFFICE_PARTS, decode_attachments, inline
from sb.life_contracts import LifeInputError
from sb.life_exports import parse_export
from sb.life_phone import phone_event
from tests.life_test_support import json_text
from tests.test_life_phone_shipping import attachment, sample


def office(part: str, extra: str | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(part, "<document>synthetic fixture</document>")
        if extra:
            archive.writestr(extra, "never extract this")
    return output.getvalue()


@pytest.mark.parametrize(
    "suffix, mime",
    [
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ],
)
def test_office_document_and_phone_source_preserve_identical_bytes(suffix: str, mime: str) -> None:
    raw = office(OFFICE_PARTS[mime])
    filename = "fixture." + suffix
    row = parse_export("document", raw, filename)[0]
    assert row["event_type"] == "document_saved"
    assert "해석 대기" in json_text(row["body"])
    assert decode_attachments(row["attachments"])[0][1] == raw
    mirrored = phone_event(sample("file_shared", attachment(mime, raw, filename)))
    assert mirrored["event_type"] == "document_saved"
    assert decode_attachments(mirrored["attachments"])[0][1] == raw


@pytest.mark.parametrize("mode", ["traversal", "wrong-kind", "zip-bomb-metadata"])
def test_office_archive_metadata_negative_controls(mode: str) -> None:
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raw = office(
        "xl/workbook.xml" if mode == "wrong-kind" else "word/document.xml",
        "../escape.txt" if mode == "traversal" else None,
    )
    if mode == "zip-bomb-metadata":
        value = bytearray(raw)
        central = value.index(b"PK\x01\x02")
        struct.pack_into("<I", value, central + 24, 128 * 1024 * 1024)
        raw = bytes(value)
    with pytest.raises(LifeInputError, match="LIFE_ATTACHMENT_MIME_MISMATCH"):
        _ = inline("fixture.docx", mime, raw)
