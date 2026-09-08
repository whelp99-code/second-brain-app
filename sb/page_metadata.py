"""Literal frontmatter fields shared by committed search projections."""
from __future__ import annotations


def frontmatter_value(text: str, key: str) -> str:
    if not text.startswith("---"):
        return ""
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return ""
    for raw in rest[:end].splitlines():
        field, sep, value = raw.partition(":")
        if sep and field.strip() == key:
            return value.strip().strip("\"'")
    return ""
