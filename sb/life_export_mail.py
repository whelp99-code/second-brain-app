"""Bounded Life source parsing; no persistence or network I/O."""

from __future__ import annotations

from collections.abc import Callable
from email import policy as email_policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import override

from sb.life_attachments import inline
from sb.life_contracts import LifeInputError
from sb.life_export_identity import export_id
from sb.life_json import LifePayload
from sb.life_values import instant


class _PlainHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: int = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag.lower() in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    @override
    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_html(value: str) -> str:
    parser = _PlainHTML()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def eml_event(raw: bytes, relative_path: str) -> LifePayload:
    message = BytesParser(policy=email_policy.default).parsebytes(raw)
    body_parts: list[str] = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.is_multipart():
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        read_content: Callable[[], str | bytes] | None = getattr(part, "get_content", None)
        if read_content is None:
            raise LifeInputError("LIFE_EXPORT_INVALID")
        content = read_content()
        if not isinstance(content, str):
            continue
        body_parts.append(
            plain_html(content) if part.get_content_type() == "text/html" else content
        )
    stamp = None
    if message["Date"] is not None:
        try:
            parsed = parsedate_to_datetime(str(message.get("Date", "")))
            if parsed.tzinfo is not None:
                stamp = instant(parsed.isoformat()).isoformat()
        except (ValueError, TypeError, OverflowError):
            stamp = None
    content = "\n".join(body_parts)
    if len(content.encode()) > 1024 * 1024:
        raise LifeInputError("LIFE_EXPORT_TOO_LARGE")
    return {
        "source_item_id": export_id("mail:", str(message.get("Message-ID") or relative_path)),
        "source_version": sha256(raw).hexdigest(),
        "event_type": "mail_message",
        "title": str(message.get("Subject") or "제목 없는 메일"),
        "body": "보낸 사람: " + str(message.get("From") or "미상") + "\n" + content,
        "occurred_start": stamp,
        "timezone": "UTC",
        "time_precision": "exact" if stamp else "unknown",
        "event_status": "occurred",
        "evidence_level": "observed",
        "attachments": [inline(PurePosixPath(relative_path).name, "message/rfc822", raw)],
    }
