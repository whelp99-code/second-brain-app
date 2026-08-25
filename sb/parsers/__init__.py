"""Suffix-routed document parsers. Optional Docling is try-import only."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, override


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


def _try_docling(payload: bytes, suffix: str) -> str | None:
    try:
        module = importlib.import_module("docling.document_converter")
    except ImportError:
        return None
    converter_cls = getattr(module, "DocumentConverter", None)
    if converter_cls is None:
        return None
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / f"input{suffix}"
        _ = path.write_bytes(payload)
        try:
            converted = converter_cls().convert(path)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
    document = getattr(converted, "document", None)
    export = getattr(document, "export_to_markdown", None)
    if export is None:
        return None
    markdown = str(export()).strip()
    return markdown or None


def _bound_parse(module_name: str, class_name: str) -> Callable[[bytes], str]:
    module = importlib.import_module(module_name)
    parser_cls = getattr(module, class_name)
    instance = parser_cls()
    parse = instance.parse
    return parse


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


def _parse_structured(kind: str, payload: bytes) -> str:
    module = importlib.import_module("sb.parsers.structured")
    parser_cls = module.StructuredDocumentParser
    kind_cls = module.StructuredKind
    return parser_cls(kind_cls(kind)).parse(payload)


_PARSERS: Final[dict[str, Callable[[bytes], str]]] = {
    ".pdf": _parse_pdf,
    ".hwpx": lambda payload: _bound_parse("sb.parsers.hwpx", "HwpxDocumentParser")(payload),
    ".docx": _parse_docx,
    ".xlsx": lambda payload: _bound_parse("sb.parsers.office", "XlsxDocumentParser")(payload),
    ".md": lambda payload: _parse_structured("markdown", payload),
    ".txt": lambda payload: _parse_structured("text", payload),
    ".json": lambda payload: _parse_structured("json", payload),
    ".yaml": lambda payload: _parse_structured("yaml", payload),
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
    "parser_for",
)
