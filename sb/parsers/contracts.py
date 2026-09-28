"""Parser result and failure contracts shared by routes and implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, override


class DocumentParseResult(Protocol):
    """Provenance-bearing parser result implemented by the optional adapter."""

    @property
    def body(self) -> str: ...

    @property
    def source_hash(self) -> str: ...

    @property
    def locator(self) -> dict[str, str | int]: ...

    @property
    def parser_version(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def partial(self) -> bool: ...


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
