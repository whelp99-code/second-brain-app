"""Canonical committed Second Brain page identifiers."""

from __future__ import annotations

import unicodedata

from sb.vault import PathEscapeError


def git_rel(page_id: str) -> str:
    """Map one canonical logical page ID to its tracked Markdown path."""
    invalid = not page_id or page_id.startswith("/") or "\x00" in page_id or "\\" in page_id
    invalid = invalid or page_id != page_id.lower() or page_id != unicodedata.normalize("NFC", page_id)
    invalid = invalid or any(ord(character) < 32 or ord(character) == 127 for character in page_id)
    parts = page_id.split("/")
    invalid = invalid or any(part in {"", ".", "..", "_proposed"} for part in parts)
    if invalid:
        raise PathEscapeError(page_id=page_id)
    if page_id.startswith(("wiki/", "daily/", "conflicts/")):
        return f"{page_id}.md"
    if "/" in page_id:
        raise PathEscapeError(page_id=page_id)
    return f"wiki/{page_id}.md"
