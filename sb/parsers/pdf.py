"""Local pypdf extraction. No network and no OCR."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Final

from pypdf import PageObject, PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import DictionaryObject, PdfObject

from sb.parsers import InvalidInput, LimitExceeded, OcrRequired

PDF_PAGE_LIMIT: Final = 5_000
PDF_MEDIA_TYPE: Final = "application/pdf"
PDF_MAX_BYTES: Final = 67_108_864


def _as_dictionary(value: PdfObject | None) -> DictionaryObject | None:
    if value is None:
        return None
    resolved = value.get_object()
    if isinstance(resolved, DictionaryObject):
        return resolved
    return None


def _dictionary_objects(catalog: DictionaryObject) -> list[PdfObject]:
    values: list[PdfObject] = list(catalog.values())
    return values


def _page_has_image_xobject(page: PageObject) -> bool:
    resources: PdfObject | None = page.get("/Resources")
    resolved = _as_dictionary(resources)
    if resolved is None:
        return False
    xobjects: PdfObject | None = resolved.get("/XObject")
    catalog = _as_dictionary(xobjects)
    if catalog is None:
        return False
    for stream in _dictionary_objects(catalog):
        material = _as_dictionary(stream)
        if material is not None and material.get("/Subtype") == "/Image":
            return True
    return False


def _extract_pages(reader: PdfReader) -> str:
    if reader.is_encrypted:
        raise InvalidInput("encrypted pdf")
    if len(reader.pages) > PDF_PAGE_LIMIT:
        raise LimitExceeded("pdf page count")
    texts: list[str] = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except PyPdfError as exc:
            raise InvalidInput("pdf page text") from exc
        if "\x00" in raw:
            raise InvalidInput("pdf page nul")
        text = raw.strip()
        if not text and _page_has_image_xobject(page):
            raise OcrRequired()
        if text:
            texts.append(text)
    return "\n".join(texts)


@dataclass(frozen=True, slots=True)
class PdfParser:
    """Bounded local PDF parser."""

    max_bytes: int = PDF_MAX_BYTES

    def parse(self, payload: bytes) -> str:
        if not payload:
            raise InvalidInput("empty pdf payload")
        if len(payload) > self.max_bytes:
            raise LimitExceeded("pdf payload size")
        try:
            with PdfReader(BytesIO(payload), strict=False) as reader:
                return _extract_pages(reader)
        except PyPdfError as exc:
            raise InvalidInput("corrupt pdf") from exc


__all__ = ("PDF_MEDIA_TYPE", "PDF_PAGE_LIMIT", "PdfParser")
