"""Fixture-backed provenance and parser admission contracts."""

from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from sb.connectors.inbox_documents import MAX_INBOX_BYTES
from sb.parsers import (
    PARTIAL_REASONS,
    InvalidInput,
    LimitExceeded,
    OcrRequired,
    WorkerFailure,
    docling_adapter,
    parse_document,
)
from sb.parsers.capabilities import INTAKE_MAX_BYTES, parser_capabilities
from sb.parsers.office import OFFICE_MAX_BYTES
from sb.uploads import MAX_UPLOAD_BYTES, UploadRejected, accept_upload

FIXTURES = Path(__file__).parent / "fixtures" / "parsers"


def _pdf(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n"
    body = bytearray(header)
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)
    xref = len(body)
    size = len(objects) + 1
    trailer = [f"xref\n0 {size}\n0000000000 65535 f \n".encode()]
    trailer.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer.append(f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(body) + b"".join(trailer)


def _mixed_ocr_pdf() -> bytes:
    text = b"BT /F1 12 Tf 72 120 Td (visible-pdf-page) Tj ET"
    return _pdf(
        [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >> endobj\n",
            b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            (
                b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                b"/Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >> endobj\n"
            ),
            f"5 0 obj << /Length {len(text)} >> stream\n".encode() + text + b"\nendstream\nendobj\n",
            (
                b"6 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                b"/Resources << /XObject << /Im1 7 0 R >> >> >> endobj\n"
            ),
            (
                b"7 0 obj << /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >> stream\n"
                b"\x00\nendstream\nendobj\n"
            ),
        ]
    )


def _image_only_pdf() -> bytes:
    return _pdf(
        [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            (
                b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                b"/Resources << /XObject << /Im1 4 0 R >> >> >> endobj\n"
            ),
            (
                b"4 0 obj << /Type /XObject /Subtype /Image /Width 1 /Height 1 "
                b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >> stream\n"
                b"\x00\nendstream\nendobj\n"
            ),
        ]
    )


def _generated_oversize(limit: int) -> bytes:
    import importlib.util

    spec = importlib.util.spec_from_file_location("parser_fixtures", FIXTURES / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    produced: bytes = module.oversize_bytes(limit)
    return produced


@pytest.fixture
def builtin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_adapter, "parse_isolated", lambda _payload, _suffix: None)


@pytest.mark.parametrize(
    ("suffix", "locator", "visible"),
    [
        (".pdf", {"kind": "page", "ordinal": 1}, "visible-pdf-page"),
        (".docx", {"kind": "paragraph", "ordinal": 1}, "Office visible body"),
        (".hwpx", {"kind": "paragraph", "section": 0, "ordinal": 1}, "visible-hwpx-section"),
        (".xlsx", {"kind": "cell", "sheet": "Metrics", "cell": "A1"}, "hello-sheet"),
        (".md", {"kind": "ordinal", "ordinal": 1}, "visible markdown"),
        (".txt", {"kind": "ordinal", "ordinal": 1}, "plain visible text"),
        (".json", {"kind": "ordinal", "ordinal": 1}, "visible-json"),
        (".yaml", {"kind": "ordinal", "ordinal": 1}, "visible-yaml"),
    ],
)
def test_each_format_returns_exact_locator_kind(
    builtin_only: None, suffix: str, locator: dict[str, str | int], visible: str
) -> None:
    result = parse_document((FIXTURES / ("sample" + suffix)).read_bytes(), suffix)
    assert visible in result.body
    assert result.locator == locator
    assert result.source_hash.startswith("sha256:")
    assert result.parser_version == "builtin:" + suffix
    assert result.model_version == "none"
    assert result.partial is False
    assert result.partial_reason is None


def test_partial_result_carries_partial_reason_enum(builtin_only: None) -> None:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet["A1"] = "known"
    sheet["B1"] = "=1+1"
    payload = BytesIO()
    workbook.save(payload)
    result = parse_document(payload.getvalue(), ".xlsx")
    assert result.partial is True
    assert result.partial_reason == "formula_unavailable"
    assert result.locator == {"kind": "cell", "sheet": "Sheet", "cell": "A1"}
    assert "formula-unavailable" in result.body
    scanned = parse_document(_mixed_ocr_pdf(), ".pdf")
    assert scanned.partial is True
    assert scanned.partial_reason == "ocr_required"
    assert scanned.locator == {"kind": "page", "ordinal": 1}
    assert "visible-pdf-page" in scanned.body
    assert {result.partial_reason, scanned.partial_reason} == PARTIAL_REASONS


def test_docling_worker_failure_raises_not_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (FIXTURES / "sample.pdf").read_bytes()
    monkeypatch.setattr(
        docling_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2, b""),
    )
    with pytest.raises(WorkerFailure, match="exit"):
        parse_document(payload, ".pdf")
    monkeypatch.setattr(
        docling_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"{}"),
    )
    with pytest.raises(WorkerFailure, match="invalid result"):
        parse_document(payload, ".pdf")
    blank = json.dumps(
        {
            "body": "   ",
            "locator": {"kind": "page", "ordinal": 1},
            "parser_version": "docling:1",
            "model_version": "docling-default",
            "partial": False,
            "partial_reason": None,
        }
    ).encode()
    monkeypatch.setattr(
        docling_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, blank),
    )
    with pytest.raises(WorkerFailure, match="invalid result"):
        parse_document(payload, ".pdf")


@pytest.mark.parametrize(("suffix", "kind"), [(".pdf", "page"), (".docx", "paragraph")])
def test_docling_success_preserves_locator_parser_and_model_version(
    monkeypatch: pytest.MonkeyPatch, suffix: str, kind: str
) -> None:
    encoded = json.dumps(
        {
            "body": "docling unit",
            "locator": {"kind": kind, "ordinal": 2},
            "parser_version": "docling:9.9.9",
            "model_version": "docling-layout",
            "partial": True,
            "partial_reason": "ocr_required",
        }
    ).encode()
    monkeypatch.setattr(
        docling_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, encoded),
    )
    result = parse_document((FIXTURES / f"sample{suffix}").read_bytes(), suffix)
    assert result.body == "docling unit"
    assert result.locator == {"kind": kind, "ordinal": 2}
    assert result.parser_version == "docling:9.9.9"
    assert result.model_version == "docling-layout"
    assert result.partial is True
    assert result.partial_reason == "ocr_required"
    assert result.source_hash.startswith("sha256:")


def test_docling_worker_timeout_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="docling", timeout=20)

    monkeypatch.setattr(docling_adapter.subprocess, "run", timeout)
    with pytest.raises(WorkerFailure, match="timeout"):
        parse_document((FIXTURES / "sample.docx").read_bytes(), ".docx")


def test_docling_absent_uses_builtin_with_builtin_parser_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        docling_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 3, b""),
    )
    result = parse_document((FIXTURES / "sample.pdf").read_bytes(), ".pdf")
    assert result.parser_version == "builtin:.pdf"
    assert result.locator == {"kind": "page", "ordinal": 1}


def test_capabilities_separate_intake_10mib_from_parser_internal_limits() -> None:
    capabilities = parser_capabilities()
    assert set(capabilities) == {".pdf", ".docx", ".hwpx", ".xlsx", ".md", ".txt", ".json", ".yaml"}
    assert INTAKE_MAX_BYTES == MAX_INBOX_BYTES == MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert all(row["intake_max_bytes"] == MAX_UPLOAD_BYTES for row in capabilities.values())
    assert all(row["parser_max_bytes"] > MAX_UPLOAD_BYTES for row in capabilities.values())
    assert capabilities[".xlsx"]["parser_max_bytes"] == OFFICE_MAX_BYTES
    assert capabilities[".pdf"]["parser_limits"]["pages"] == 5_000


def test_image_only_pdf_raises_ocr_required(builtin_only: None) -> None:
    with pytest.raises(OcrRequired, match="ocr required"):
        parse_document(_image_only_pdf(), ".pdf")


def test_empty_xlsx_locator_does_not_read_closed_workbook(builtin_only: None) -> None:
    workbook = Workbook()
    payload = BytesIO()
    workbook.save(payload)
    result = parse_document(payload.getvalue(), ".xlsx")
    assert result.locator == {"kind": "cell", "sheet": "Sheet", "cell": "A1"}
    assert result.partial is False
    assert result.partial_reason is None


def test_oversize_corrupt_and_expansion_bomb_rejected_with_reason(
    tmp_path: Path, builtin_only: None
) -> None:
    # Upload intake rejects at 10 MiB; parser-only limits are separately exposed.
    with pytest.raises(UploadRejected, match="file exceeds 10485760 bytes"):
        accept_upload(tmp_path, "oversize.bin", _generated_oversize(MAX_UPLOAD_BYTES))
    with pytest.raises(InvalidInput, match="corrupt pdf"):
        parse_document((FIXTURES / "truncated.pdf").read_bytes(), ".pdf")
    with pytest.raises(LimitExceeded, match="hwpx zip compression ratio"):
        parse_document((FIXTURES / "zip-bomb.hwpx").read_bytes(), ".hwpx")
