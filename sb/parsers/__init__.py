"""Suffix-routed document parsers. Optional Docling is try-import only."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Final

from sb.parsers.contracts import (
    PARTIAL_REASONS,
    FormatUnsupported,
    InvalidInput,
    LimitExceeded,
    OcrRequired,
    ParseError,
    UnsupportedSuffix,
    WorkerFailure,
)
from sb.parsers.contracts import DocumentParseResult as DocumentParseResult


def _try_docling(payload: bytes, suffix: str) -> str | None:
    from sb.parsers.docling_adapter import parse_isolated

    result = parse_isolated(payload, suffix)
    return None if result is None else result.body


def parse_document(payload: bytes, suffix: str) -> DocumentParseResult:
    """Parse with an exact first-unit locator; worker failure is never fallback."""
    from sb.parsers.docling_adapter import parse_isolated

    normalized = (suffix if suffix.startswith(".") else f".{suffix}").lower()
    _ = parser_for(normalized)  # Reject unknown suffixes before starting an optional worker.
    if normalized in {".pdf", ".docx"}:
        isolated = parse_isolated(payload, normalized)
        if isolated is not None:
            return isolated
    if normalized == ".pdf":
        from sb.parsers.pdf import PdfParser

        body, locator, reason = PdfParser().parse_details(payload)
    elif normalized == ".docx":
        from sb.parsers.office import DocxDocumentParser

        body, locator, reason = DocxDocumentParser().parse_details(payload)
    elif normalized == ".xlsx":
        from sb.parsers.office import XlsxDocumentParser

        body, locator, reason = XlsxDocumentParser().parse_details(payload)
    elif normalized == ".hwpx":
        from sb.parsers.hwpx import HwpxDocumentParser

        body, locator, reason = HwpxDocumentParser().parse_details(payload)
    else:
        body = parser_for(normalized)(payload)
        locator, reason = {"kind": "ordinal", "ordinal": 1}, None
    return DocumentParseResult(
        body=body,
        source_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
        locator=locator,
        parser_version=f"builtin:{normalized}",
        model_version="none",
        partial=reason is not None,
        partial_reason=reason,
    )


def _parse_pdf(payload: bytes) -> str:
    extracted = _try_docling(payload, ".pdf")
    if extracted is not None:
        return extracted
    from sb.parsers.pdf import PdfParser

    return PdfParser().parse(payload)


def _parse_docx(payload: bytes) -> str:
    extracted = _try_docling(payload, ".docx")
    if extracted is not None:
        return extracted
    from sb.parsers.office import DocxDocumentParser

    return DocxDocumentParser().parse(payload)


def _parse_hwpx(payload: bytes) -> str:
    from sb.parsers.hwpx import HwpxDocumentParser

    return HwpxDocumentParser().parse(payload)


def _parse_xlsx(payload: bytes) -> str:
    from sb.parsers.office import XlsxDocumentParser

    return XlsxDocumentParser().parse(payload)


def _parse_structured(kind: str, payload: bytes) -> str:
    from sb.parsers.structured import parse_structured

    return parse_structured(kind, payload)


def _parse_md(payload: bytes) -> str:
    return _parse_structured("markdown", payload)


def _parse_txt(payload: bytes) -> str:
    return _parse_structured("text", payload)


def _parse_json(payload: bytes) -> str:
    return _parse_structured("json", payload)


def _parse_yaml(payload: bytes) -> str:
    return _parse_structured("yaml", payload)


_PARSERS: Final[dict[str, Callable[[bytes], str]]] = {
    ".pdf": _parse_pdf,
    ".hwpx": _parse_hwpx,
    ".docx": _parse_docx,
    ".xlsx": _parse_xlsx,
    ".md": _parse_md,
    ".txt": _parse_txt,
    ".json": _parse_json,
    ".yaml": _parse_yaml,
}


def parser_for(suffix: str) -> Callable[[bytes], str]:
    """Return the bytes-to-text parser for a registered suffix.

    Unknown suffixes raise UnsupportedSuffix. Optional Docling, when
    importable, is preferred for .pdf and .docx.
    """
    normalized = suffix if suffix.startswith(".") else f".{suffix}"
    normalized = normalized.lower()
    parser = _PARSERS.get(normalized)
    if parser is None:
        raise UnsupportedSuffix(suffix)
    return parser


__all__ = (
    "PARTIAL_REASONS",
    "DocumentParseResult",
    "FormatUnsupported",
    "InvalidInput",
    "LimitExceeded",
    "OcrRequired",
    "ParseError",
    "UnsupportedSuffix",
    "WorkerFailure",
    "parse_document",
    "parser_for",
)
