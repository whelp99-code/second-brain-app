"""Pure, explicit plain-text-v1 body policy; never normalize approved input."""

import unicodedata

from sb.remember_values import remember_lines


def plain_text_body(content: object) -> str:
    if not isinstance(content, str) or not content or unicodedata.normalize("NFC", content) != content:
        raise ValueError("WRITE_REQUEST_INVALID")
    try:
        raw = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("WRITE_REQUEST_INVALID") from exc
    if len(raw) > 4_096 or any(
        (ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in content
    ):
        raise ValueError("WRITE_REQUEST_INVALID")
    _ = remember_lines(content)
    return content
