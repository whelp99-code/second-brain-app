"""Suffix-routed document parsers. Optional Docling is try-import only."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Protocol, override


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


class _DoclingDocument(Protocol):
    def export_to_markdown(self) -> str: ...


class _DoclingConversion(Protocol):
    @property
    def document(self) -> _DoclingDocument: ...


class _DoclingConverter(Protocol):
    def convert(self, source: Path) -> _DoclingConversion: ...


class _DoclingConverterType(Protocol):
    def __call__(self) -> _DoclingConverter: ...


def _try_docling(payload: bytes, suffix: str) -> str | None:
    try:
        module = importlib.import_module("docling.document_converter")
    except ImportError:
        return None
    converter_cls: _DoclingConverterType | None = getattr(module, "DocumentConverter", None)
    if converter_cls is None:
        return None
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / f"input{suffix}"
        _ = path.write_bytes(payload)
        try:
            converted: _DoclingConversion = converter_cls().convert(path)
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
    markdown = converted.document.export_to_markdown().strip()
    return markdown or None


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
    "parser_for",
)
