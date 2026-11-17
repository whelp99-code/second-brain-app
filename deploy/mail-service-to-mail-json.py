#!/usr/bin/env python3
"""Convert Mail service message objects into SB mail-json.

Maps receivedAt, sentAt, subject, body, and internetMessageId onto
messages[].received_at, sent_at, subject, body, and id. Time strings with an
explicit offset are copied unchanged. This script does not open a mailbox,
database, or network API.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO


class ConvertError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def convert(payload: object) -> dict[str, list[dict[str, str | None]]]:
    """Return a mail-json document.

    The same internetMessageId with the same subject, body, and times is kept
    once. A repeated id whose content differs is rejected.
    """
    if isinstance(payload, dict) and set(payload) >= {"messages"}:
        rows = payload.get("messages")
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ConvertError("MAIL_JSON_INVALID")
    if not isinstance(rows, list):
        raise ConvertError("MAIL_JSON_INVALID")
    seen: dict[str, dict[str, str | None]] = {}
    messages: list[dict[str, str | None]] = []
    for row in rows:
        item = _message(row)
        prior = seen.get(item["id"])
        if prior is None:
            seen[item["id"]] = item
            messages.append(item)
            continue
        if prior != item:
            raise ConvertError("MAIL_JSON_DUPLICATE_ID")
    return {"messages": messages}


def main(argv: list[str] | None = None, stdin: TextIO | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) > 1:
            raise ConvertError("MAIL_JSON_INVALID")
        raw = Path(args[0]).read_text(encoding="utf-8") if args else (stdin or sys.stdin).read()
        payload = json.loads(raw)
        document = convert(payload)
    except ConvertError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("MAIL_JSON_INVALID", file=sys.stderr)
        return 2
    json.dump(document, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 100000:
        raise ConvertError("MAIL_JSON_INVALID")
    return value


def _message(row: object) -> dict[str, str | None]:
    if not isinstance(row, dict):
        raise ConvertError("MAIL_JSON_INVALID")
    message_id = row.get("internetMessageId")
    if not isinstance(message_id, str) or not message_id or len(message_id) > 4096:
        raise ConvertError("MAIL_JSON_INVALID")
    return {
        "id": message_id,
        "subject": _text(row.get("subject", "")),
        "body": _text(row.get("body", "")),
        "received_at": _offset_time(row.get("receivedAt")),
        "sent_at": _offset_time(row.get("sentAt")),
    }


def _offset_time(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ConvertError("MAIL_JSON_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConvertError("MAIL_JSON_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConvertError("MAIL_JSON_TIMEZONE_REQUIRED")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
