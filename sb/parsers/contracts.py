"""Parser result and failure contracts shared by routes and implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, override


@dataclass(frozen=True, slots=True)
class DocumentParseResult:
    """Provenance of the first extracted unit of a document."""

    body: str
    source_hash: str
    locator: dict[str, str | int]
    parser_version: str
    model_version: str
    partial: bool
    partial_reason: str | None = None


PARTIAL_REASONS: Final = frozenset({"ocr_required", "formula_unavailable"})


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
class WorkerFailure(ParseError):
    reason: str

    @override
    def __str__(self) -> str:
        return f"docling worker failure: {self.reason}"


@dataclass(frozen=True, slots=True)
class UnsupportedSuffix(Exception):
    suffix: str

    @override
    def __str__(self) -> str:
        return f"unsupported suffix: {self.suffix}"
