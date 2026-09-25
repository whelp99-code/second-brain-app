"""Web Push payload builder. This process does not listen for pushes."""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

_ALLOWED_SCHEMES: Final = frozenset({"https"})


class PushServerRefused(RuntimeError):
    pass


def notification_request(endpoint: str, title: str, body: str) -> dict[str, str]:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise ValueError("web push endpoint must be https")
    if not title.strip() or not body.strip():
        raise ValueError("web push title and body are required")
    return {"endpoint": endpoint, "title": title.strip(), "body": body.strip()}


def listen() -> None:
    raise PushServerRefused("NO_PUSH_SERVER")
