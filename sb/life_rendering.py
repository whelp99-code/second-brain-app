"""Pure deterministic Life projections; no I/O."""

from __future__ import annotations

import html
from hashlib import sha256
from urllib.parse import quote

from sb.life_contracts import LifeEventV1
from sb.life_values import day_window, instant
from sb.redaction import redact_credentials


def safe_text(value: str) -> str:
    """Render input as literal Markdown text, not commands, HTML, images or links."""
    return (
        html.escape(redact_credentials(value), quote=True)
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("!", "&#33;")
    )


def source_uri(event: LifeEventV1) -> str:
    return "life/" + quote(event.source_item_id, safe="")


def core_page_id(event_id: str) -> str:
    # Keep the existing Vault.forget_page no-follow, single-folder boundary.
    return f"wiki/life-event-{event_id}"


def on_day(event: LifeEventV1, day: str, timezone: str) -> bool:
    start, end = day_window(day, timezone)
    if event.occurred_start is None:
        return False
    occurred = instant(event.occurred_start)
    stopped = instant(event.occurred_end) if event.occurred_end else occurred
    if stopped == occurred:
        return start <= occurred < end
    return occurred < end and stopped > start


def entity_path(event: LifeEventV1, kind: str, entity_id: str) -> str:
    folders = {
        "person": "People",
        "company": "Companies",
        "project": "Projects",
        "place": "Places",
        "event": "Events",
        "decision": "Decisions",
    }
    stable = sha256((event.source_id + "\0" + kind + "\0" + entity_id).encode()).hexdigest()[:24]
    return "Auto/" + folders[kind] + "/entity-" + stable + ".md"


def wikilink(path: str, label: str) -> str:
    return "[[" + path.removesuffix(".md") + "|" + safe_text(label).replace("\n", " ") + "]]"
