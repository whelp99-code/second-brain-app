"""Suffix-routed document parsers. Optional Docling is try-import only."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol, cast, override


class DocumentParseResult(Protocol):
    """Provenance-bearing parser result implemented by the optional adapter."""

    body: str
    source_hash: str
    locator: dict[str, str | int]
    parser_version: str
    model_version: str
    partial: bool


class ParseError(Exception):
    """Base class for document parse failures."""


@dataclass(frozen=True, slots=True)
class InvalidInput(ParseError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class FormatUnsupported(ParseError):
    format_name: str

    @override
    def __str__(self) -> str:
        return f"unsupported format: {self.format_name}"


@dataclass(frozen=True, slots=True)
class LimitExceeded(ParseError):
    limit_name: str

    @override
    def __str__(self) -> str:
        return f"limit exceeded: {self.limit_name}"


@dataclass(frozen=True, slots=True)
class OcrRequired(ParseError):
    @override
    def __str__(self) -> str:
        return "ocr required"


@dataclass(frozen=True, slots=True)
class UnsupportedSuffix(Exception):
    suffix: str

    @override
    def __str__(self) -> str:
        return f"unsupported suffix: {self.suffix}"


class _BytesParser(Protocol):
    def parse(self, payload: bytes) -> str: ...


class _BytesParserType(Protocol):
    def __call__(self) -> _BytesParser: ...


class _StructuredParse(Protocol):
    def __call__(self, kind: str, payload: bytes) -> str: ...


def _try_docling(payload: bytes, suffix: str) -> str | None:
    adapter = importlib.import_module("sb.parsers.docling_adapter")
    result = adapter.parse_isolated(payload, suffix)
    return None if result is None else result.body


def parse_document(payload: bytes, suffix: str) -> DocumentParseResult:
    """Parse one document and retain provenance for derived memory records."""
    adapter = importlib.import_module("sb.parsers.docling_adapter")

    normalized = suffix if suffix.startswith(".") else f".{suffix}"
    isolated = (
        adapter.parse_isolated(payload, normalized.lower())
        if normalized.lower() in {".pdf", ".docx"}
        else None
    )
    if isolated is not None:
        return cast(DocumentParseResult, isolated)
    parser = parser_for(normalized)
    body = parser(payload)
    result_type = adapter.DocumentParseResult
    return cast(DocumentParseResult, result_type(
        body=body,
        source_hash="sha256:" + hashlib.sha256(payload).hexdigest(),
        locator={"kind": "document", "ordinal": 1},
        parser_version=f"builtin:{normalized.lower()}",
        model_version="none",
        partial=False,
    ))


def _bound_parse(module_name: str, class_name: str) -> Callable[[bytes], str]:
    module = importlib.import_module(module_name)
    parser_cls: _BytesParserType | None = getattr(module, class_name, None)
    if parser_cls is None:
        raise TypeError(class_name)
    return parser_cls().parse


def _parse_pdf(payload: bytes) -> str:
    extracted = _try_docling(payload, ".pdf")
    if extracted is not None:
        return extracted
    return _bound_parse("sb.parsers.pdf", "PdfParser")(payload)


def _parse_docx(payload: bytes) -> str:
    extracted = _try_docling(payload, ".docx")
    if extracted is not None:
        return extracted
    return _bound_parse("sb.parsers.office", "DocxDocumentParser")(payload)


def _parse_hwpx(payload: bytes) -> str:
    return _bound_parse("sb.parsers.hwpx", "HwpxDocumentParser")(payload)


def _parse_xlsx(payload: bytes) -> str:
    return _bound_parse("sb.parsers.office", "XlsxDocumentParser")(payload)


def _parse_structured(kind: str, payload: bytes) -> str:
    module = importlib.import_module("sb.parsers.structured")
    parse: _StructuredParse | None = getattr(module, "parse_structured", None)
    if parse is None:
        raise TypeError(kind)
    return parse(kind, payload)


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
    "FormatUnsupported",
    "InvalidInput",
    "LimitExceeded",
    "OcrRequired",
    "ParseError",
    "UnsupportedSuffix",
    "parse_document",
    "parser_for",
)
