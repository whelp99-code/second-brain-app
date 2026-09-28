"""L4 pure event/timeline/Obsidian projections. Only sb.vault writes core pages."""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from hashlib import sha256
from urllib.parse import quote

from sb.contracts import PageSpec, SourceCite
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import canonical_bytes, day_window, instant, zone
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


def page_for_event(event: LifeEventV1) -> PageSpec:
    origin = event.source_id + ":" + source_uri(event)
    sid = sha256((origin + "\0" + event.raw_digest).encode()).hexdigest()[:8]
    facts = [
        "사건 ID: " + event.event_id,
        "개정: " + str(event.revision),
        "제목: " + safe_text(event.title),
        "사건 상태: " + event.event_status,
        "근거 수준: " + event.evidence_level + " / 검토: " + event.review_state,
        "발생 시각: " + (event.occurred_start or "알 수 없음"),
        "접수 시각: " + event.recorded_at,
    ]
    if event.value_status != "not_applicable":
        facts.append(
            "측정값: "
            + ("알 수 없음" if event.value is None else str(event.value))
            + " / 상태: "
            + event.value_status
            + " / 단위: "
            + safe_text(event.unit or "")
        )
    excerpt = event.body[:6000]
    facts.extend(safe_text(line) for line in excerpt.splitlines()[:24] if line.strip())
    omitted = len(event.body) > 6000 or len(event.body.splitlines()) > 24
    bounded: list[str] = []
    for fact in facts:
        encoded = fact.encode("utf-8")
        if len(encoded) > 2800:
            bounded.append(encoded[:2800].decode("utf-8", errors="ignore") + "…")
            omitted = True
        else:
            bounded.append(fact)
    facts = bounded
    if omitted:
        facts.append("표시 한도로 원문 일부를 생략했습니다. 원문 근거를 확인하세요.")
    body = "# " + safe_text(event.title) + "\n\n" + "\n".join(f"- {line}[^{sid}]" for line in facts)
    return PageSpec(
        page_id=core_page_id(event.event_id),
        title=redact_credentials(event.title),
        body_md=body,
        sources=[SourceCite(sid=sid, origin=origin, hash=event.raw_digest)],
        status="active",
        prompt_version="life-v1",
        model_id="deterministic-v1",
        sensitivity=event.sensitivity,
    )


def on_day(event: LifeEventV1, day: str, timezone: str) -> bool:
    start, end = day_window(day, timezone)
    if event.occurred_start is None:
        return False
    occurred = instant(event.occurred_start)
    stopped = instant(event.occurred_end) if event.occurred_end else occurred
    if stopped == occurred:
        return start <= occurred < end
    return occurred < end and stopped > start


def timeline(events: Sequence[LifeEventV1], day: str, timezone: str) -> dict[str, object]:
    day_window(day, timezone)
    selected = sorted(
        (event for event in events if on_day(event, day, timezone)),
        key=lambda event: (event.occurred_start or "", event.event_id),
    )
    undated = [event for event in events if event.occurred_start is None]
    return {
        "schema_version": 1,
        "day": day,
        "timezone": timezone,
        "events": [event.as_dict() for event in selected],
        "undated": [event.as_dict() for event in undated],
        "coverage": "source_records_only",
        "complete_day_observed": False,
    }


def brief(events: Sequence[LifeEventV1], day: str, timezone: str, slot: str) -> dict[str, object]:
    if slot not in {"morning", "evening"}:
        raise LifeInputError("LIFE_SLOT_INVALID")
    selected = [e for e in events if on_day(e, day, timezone)]
    selected.sort(key=lambda e: (e.occurred_start or "", e.event_id))
    day_start, day_end = day_window(day, timezone)

    def entity_keys(event):
        return {
            (event.source_id, entity.kind, entity.entity_id)
            for entity in event.entities
            if entity.kind in {"person", "company", "project"}
        }

    def previous_context(event):
        keys = entity_keys(event)
        if not keys:
            return []
        previous = [
            past
            for past in events
            if past.event_id != event.event_id
            and past.occurred_start is not None
            and instant(past.occurred_start) < day_start
            and keys.intersection(entity_keys(past))
            and (past.valid_from is None or instant(past.valid_from) < day_end)
            and (past.valid_until is None or day_start < instant(past.valid_until))
        ]
        previous.sort(
            key=lambda past: (
                past.event_type == "decision",
                past.occurred_start,
                past.recorded_at,
                past.event_id,
            ),
            reverse=True,
        )
        return [
            {
                "event_id": past.event_id,
                "revision": past.revision,
                "title": past.title,
                "excerpt": past.body[:800],
                "event_status": past.event_status,
                "evidence_level": past.evidence_level,
                "raw_digest": past.raw_digest,
                "reason": "같은 명시적 인물·회사·프로젝트의 이전 기록",
            }
            for past in previous[:3]
        ]

    if slot == "morning":
        selected.sort(key=lambda e: (e.event_status != "planned", e.occurred_start or ""))
    cards = [
        {
            "event_id": e.event_id,
            "revision": e.revision,
            "title": e.title,
            "event_status": e.event_status,
            "evidence_level": e.evidence_level,
            "reason": "오늘의 예정 기록" if e.event_status == "planned" else "오늘의 사건 기록",
            "raw_digest": e.raw_digest,
            "excerpt": e.body[:800],
            "previous_context": previous_context(e),
            "changed": e.revision > 1,
        }
        for e in selected[:5]
    ]
    followups = [
        event
        for event in events
        if event.event_type == "task_started"
        and event.event_status != "cancelled"
        and event.occurred_start is not None
        and instant(event.occurred_start) < day_start
    ]
    followups.sort(key=lambda event: (event.occurred_start, event.event_id), reverse=True)
    pending = [
        {
            "event_id": event.event_id,
            "revision": event.revision,
            "title": event.title,
            "raw_digest": event.raw_digest,
            "reason": "시작 기록은 있으나 이 사건의 완료 상태가 미확인",
        }
        for event in followups[:3]
    ]
    snapshot = {
        "day": day,
        "timezone": timezone,
        "slot": slot,
        "cards": cards,
        "followups": pending,
        "facts_are_quoted_not_inferred": True,
    }
    return {
        **snapshot,
        "input_version": sha256(canonical_bytes(snapshot)).hexdigest(),
        "mode": "facts_only",
        "delivery_state": "not_attempted",
        "omitted": max(0, len(selected) - 5),
    }


def _entity_path(event: LifeEventV1, kind: str, entity_id: str) -> str:
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


def _wikilink(path: str, label: str) -> str:
    return "[[" + path.removesuffix(".md") + "|" + safe_text(label).replace("\n", " ") + "]]"


def _yaml_scalar(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def source_generation(events: Sequence[LifeEventV1], day: str, timezone: str) -> str:
    """Stable id of the authorized event set. Independent of rendered Markdown."""
    rows = [
        [event.event_id, event.revision, event.raw_digest, event.event_status, event.evidence_level]
        for event in sorted(events, key=lambda event: event.event_id)
    ]
    return sha256(canonical_bytes([day, timezone, rows])).hexdigest()


def _frontmatter(
    event: LifeEventV1,
    *,
    generation: str,
    timezone: str,
    evidence_count: int,
    links: Sequence[str],
) -> list[str]:
    """Flat scalars and one list of link strings. No nested mappings."""
    lines = [
        "---",
        "sb_view_schema: 1",
        "sb_object_id: " + _yaml_scalar(event.event_id),
        "sb_revision: " + str(event.revision),
        "sb_managed: true",
        "sb_generation: " + _yaml_scalar(generation),
        "sb_event_state: " + event.event_status,
        "sb_evidence_state: " + event.evidence_level,
        "sb_timezone: " + _yaml_scalar(timezone),
        "sb_evidence_count: " + str(evidence_count),
    ]
    if links:
        lines.append("sb_links:")
        lines.extend("  - " + _yaml_scalar(link) for link in links)
    else:
        lines.append("sb_links: []")
    lines.append("---")
    return lines


DAILY_SECTIONS = (
    "요점",
    "시간순",
    "결정 변화",
    "내일 필요한 기억",
    "중요한 빈칸",
    "MyNotes",
    "수집 상태",
)


def daily_markdown(
    events: Sequence[LifeEventV1], * , day: str, timezone: str, complete: bool
) -> str:
    """Daily UX order: 요점, 시간순, 결정 변화, 내일 필요한 기억, 중요한 빈칸, MyNotes, 수집 상태."""
    start, end = day_window(day, timezone)
    local_zone = zone(timezone)
    selected = sorted(
        (event for event in events if on_day(event, day, timezone)),
        key=lambda event: (event.occurred_start or "", event.event_id),
    )
    points = [
        "- "
        + (event.occurred_start or "시각 없음")
        + " · "
        + event.event_status
        + " · "
        + safe_text(event.title)
        for event in selected[:7]
    ] or ["- 오늘 창에 해당하는 명시 기록이 없습니다."]
    timed = []
    for event in selected:
        if event.occurred_start is None:
            continue
        stamp = instant(event.occurred_start).astimezone(local_zone).strftime("%H:%M")
        timed.append(
            "- "
            + stamp
            + " · "
            + event.event_status
            + " · "
            + _wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        )
    decisions = [
        event
        for event in events
        if on_day(event, day, timezone) and (event.event_type == "decision" or event.revision > 1)
    ]
    decision_lines = [
        "- 개정 "
        + str(event.revision)
        + " · "
        + event.event_status
        + " · "
        + _wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        for event in sorted(decisions, key=lambda event: event.event_id)
    ] or ["- 표시할 결정 변화가 없습니다."]
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    morning = brief(events, day, timezone, "morning")
    needed = [
        "- "
        + _wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        + " · 내일 예정"
        for event in events
        if on_day(event, tomorrow, timezone) and event.event_status == "planned"
    ]
    needed += [
        "- "
        + _wikilink(f"Auto/Events/{row['event_id']}.md", row["title"])
        + " · "
        + safe_text(row["reason"])
        for row in morning["followups"]
    ]
    for card in morning["cards"]:
        for past in card["previous_context"]:
            needed.append(
                "- 내일 참고: "
                + _wikilink(f"Auto/Events/{past['event_id']}.md", past["title"])
                + " · "
                + safe_text(past["excerpt"][:240])
            )
    if not needed:
        needed = ["- 내일로 넘길 명시 기록이 없습니다."]
    gaps = [
        "- "
        + _wikilink(f"Auto/Events/{row['event_id']}.md", row["title"])
        + " · "
        + safe_text(row["question"])
        for row in gap_candidates(events, now=end - timedelta(seconds=1))
        if on_day(
            next(event for event in events if event.event_id == row["event_id"]), day, timezone
        )
    ]
    undated = [event for event in events if event.occurred_start is None]
    gaps += [
        "- 시각 불명: " + _wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        for event in undated
    ]
    if not gaps:
        gaps = ["- 확인된 중요 빈칸이 없습니다. 기록이 없는 시간은 활동 없음이 아닙니다."]
    del start
    sections = {
        "요점": ["실제 수집 기록만 표시합니다. 추정은 요점이 아닙니다.", *points],
        "시간순": timed or ["- 시간순으로 놓을 발생 시각이 없습니다."],
        "결정 변화": decision_lines,
        "내일 필요한 기억": needed,
        "중요한 빈칸": gaps,
        "MyNotes": [f"[[MyNotes/{day}]]", f"![[MyNotes/{day}]]"],
        "수집 상태": [
            "기록이 없는 시간을 실제 활동 없음으로 해석하지 않습니다.",
            "[[Auto/System/Sync-Status]]",
            "전체 스냅샷" if complete else "부분 스냅샷 — 누락된 파일을 삭제하지 않습니다.",
        ],
    }
    lines = ["# " + day, ""]
    for name in DAILY_SECTIONS:
        lines += ["## " + name, *sections[name], ""]
    return "\n".join(lines).rstrip() + "\n"


def obsidian_manifest(
    events: Sequence[LifeEventV1],
    *,
    day: str,
    timezone: str,
    sensitivities: tuple[str, ...] = ("public", "personal"),
    complete: bool = True,
    generation: str | None = None,
    evidence_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """A bounded, complete authorized snapshot. No private source paths or credentials.

    Callers enforce scope/source policies BEFORE passing records to this function.
    Revoked/deleted/expired records must be excluded, including their graph nodes.
    Only previously-owned generated paths may be pruned by the client.
    """
    day_window(day, timezone)
    visible = tuple(
        sorted((e for e in events if e.sensitivity in sensitivities), key=lambda e: e.event_id)
    )
    shared = generation or source_generation(visible, day, timezone)
    counts = evidence_counts or {}
    files: dict[str, str] = {}
    entity_events: dict[str, list[tuple[str, LifeEventV1]]] = defaultdict(list)
    for event in visible:
        path = f"Auto/Events/{event.event_id}.md"
        evidence_path = f"Auto/Evidence/{event.event_id}.md"
        links = [_wikilink(evidence_path, "원문 근거")]
        for entity in event.entities:
            links.append(_wikilink(_entity_path(event, entity.kind, entity.entity_id), entity.label))
        count = counts.get(event.event_id, 1)
        if type(count) is not int or count < 1:
            count = 1
        lines = [
            *_frontmatter(
                event,
                generation=shared,
                timezone=timezone,
                evidence_count=count,
                links=links,
            ),
            "# " + safe_text(event.title),
            "",
            "발생: " + (event.occurred_start or "알 수 없음"),
            "접수: " + event.recorded_at,
            "",
            "상태: " + event.event_status + " / " + event.evidence_level,
            "",
            safe_text(event.body),
            "",
            _wikilink(evidence_path, "원문 근거"),
            "",
            f"[정정 요청](obsidian://sb-life-correct?event={event.event_id}&revision={event.revision})",
        ]
        for entity in event.entities:
            ep = _entity_path(event, entity.kind, entity.entity_id)
            lines.append(_wikilink(ep, entity.label))
            entity_events[ep].append((entity.label, event))
        files[path] = "\n".join(lines) + "\n"
        files[evidence_path] = (
            "# 원문 근거\n\n"
            + _wikilink(path, event.title)
            + "\n\n"
            + "출처 버전: "
            + safe_text(event.source_version)
            + "\n\n"
            + f"[인증하여 원문 열기](obsidian://sb-life-evidence?event={event.event_id})\n"
        )
    for path, linked in sorted(entity_events.items()):
        files[path] = (
            "# "
            + safe_text(linked[0][0])
            + "\n\n"
            + "자동 병합이 아닌 출처의 명시적 연결입니다.\n\n"
            + "\n".join(
                "- " + _wikilink(f"Auto/Events/{e.event_id}.md", e.title) for _, e in linked
            )
            + "\n"
        )
    files[f"Auto/Daily/{day}.md"] = daily_markdown(
        visible, day=day, timezone=timezone, complete=complete
    )
    files["Auto/Home.md"] = "# 나의 기억\n\n" + _wikilink(f"Auto/Daily/{day}.md", "오늘") + "\n"
    files["Auto/System/Sync-Status.md"] = (
        "# 동기화 상태\n\n허용된 기록의 복제 뷰입니다. MyNotes는 자동 갱신하지 않습니다.\n"
        + ("전체 스냅샷\n" if complete else "부분 스냅샷 — 누락된 파일을 삭제하지 않습니다.\n")
    )
    rows = [
        {"path": path, "content": content, "sha256": sha256(content.encode()).hexdigest()}
        for path, content in sorted(files.items())
    ]
    content_generation = sha256(canonical_bytes(rows)).hexdigest()
    return {
        "schema_version": 1,
        "generation": content_generation,
        "source_generation": shared,
        "complete": complete,
        "files": rows,
        "managed_prefix": "Auto/",
        "cursor": content_generation,
    }


def gap_candidates(
    events: Sequence[LifeEventV1], *, now: datetime
) -> tuple[dict[str, object], ...]:
    candidates = []
    for event in events:
        if event.event_type != "calendar_event" or event.event_status == "cancelled":
            continue
        if (
            event.occurred_start is None
            or instant(event.occurred_end or event.occurred_start) > now
        ):
            continue
        if event.review_state in {"rejected", "disputed"}:
            continue
        if event.event_status == "planned":
            question = "예정된 일정이 실제로 진행됐나요?"
        elif event.event_status == "occurred" and not event.body.strip():
            question = "확인된 일정의 결과로 기억할 내용이 있나요?"
        else:
            continue
        candidates.append(
            {
                "event_id": event.event_id,
                "revision": event.revision,
                "title": event.title,
                "question": question,
                "evidence_digest": event.raw_digest,
            }
        )
    return tuple(sorted(candidates, key=lambda c: c["event_id"]))
