"""Machine-readable parser limits; intake admission is a separate boundary."""

from __future__ import annotations

from typing import Final, TypedDict

from sb.parsers.docling_adapter import MAX_BYTES as DOCLING_MAX_BYTES
from sb.parsers.hwpx import HWPX_MAX_BYTES, MAX_COMPRESSION_RATIO
from sb.parsers.office import DEFAULT_OFFICE_PARSE_LIMITS, OFFICE_MAX_BYTES
from sb.parsers.pdf import PDF_MAX_BYTES, PDF_PAGE_LIMIT
from sb.parsers.structured import MAX_BYTES as STRUCTURED_MAX_BYTES

# Keep this value in sync with inbox_documents.MAX_INBOX_BYTES and uploads.MAX_UPLOAD_BYTES.
INTAKE_MAX_BYTES: Final = 10 * 1024 * 1024


class ParserCapability(TypedDict):
    intake_max_bytes: int
    parser_max_bytes: int
    locator_kind: str
    parser_limits: dict[str, int]


def parser_capabilities() -> dict[str, ParserCapability]:
    """Return fresh per-format limits for the upload capabilities surface."""
    limits = DEFAULT_OFFICE_PARSE_LIMITS
    return {
        ".pdf": {
            "intake_max_bytes": INTAKE_MAX_BYTES,
            "parser_max_bytes": PDF_MAX_BYTES,
            "locator_kind": "page",
            "parser_limits": {"pages": PDF_PAGE_LIMIT, "docling_max_bytes": DOCLING_MAX_BYTES},
        },
        ".docx": {
            "intake_max_bytes": INTAKE_MAX_BYTES,
            "parser_max_bytes": OFFICE_MAX_BYTES,
            "locator_kind": "paragraph",
            "parser_limits": {
                "zip_members": limits.zip_members,
                "zip_member_bytes": limits.zip_member_bytes,
                "zip_uncompressed_bytes": limits.zip_uncompressed_bytes,
                "zip_ratio": limits.zip_ratio,
                "docling_max_bytes": DOCLING_MAX_BYTES,
            },
        },
        ".hwpx": {
            "intake_max_bytes": INTAKE_MAX_BYTES,
            "parser_max_bytes": HWPX_MAX_BYTES,
            "locator_kind": "paragraph",
            "parser_limits": {"zip_ratio": MAX_COMPRESSION_RATIO},
        },
        ".xlsx": {
            "intake_max_bytes": INTAKE_MAX_BYTES,
            "parser_max_bytes": OFFICE_MAX_BYTES,
            "locator_kind": "cell",
            "parser_limits": {
                "zip_members": limits.zip_members,
                "zip_member_bytes": limits.zip_member_bytes,
                "zip_uncompressed_bytes": limits.zip_uncompressed_bytes,
                "zip_ratio": limits.zip_ratio,
                "worksheets": limits.worksheets,
                "rows": limits.rows,
                "cells": limits.cells,
            },
        },
        **{
            suffix: {
                "intake_max_bytes": INTAKE_MAX_BYTES,
                "parser_max_bytes": STRUCTURED_MAX_BYTES,
                "locator_kind": "ordinal",
                "parser_limits": {},
            }
            for suffix in (".md", ".txt", ".json", ".yaml")
        },
    }
