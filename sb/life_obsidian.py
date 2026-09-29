"""Pure deterministic Life projections; no I/O."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from hashlib import sha256

from sb.life_brief import brief
from sb.life_contracts import LifeEventV1
from sb.life_rendering import entity_path, on_day, safe_text, wikilink
from sb.life_values import canonical_bytes, day_window, instant, zone
from sb.life_view_contracts import (
    GapCandidate,
    ObsidianManifest,
    ViewFile,
)


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


def gap_candidates(events: Sequence[LifeEventV1], *, now: datetime) -> tuple[GapCandidate, ...]:
    candidates: list[GapCandidate] = []
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


def daily_markdown(
    events: Sequence[LifeEventV1], *, day: str, timezone: str, complete: bool
) -> str:
    """Daily UX order: 요점, 시간순, 결정 변화, 내일 필요한 기억, 중요한 빈칸, MyNotes, 수집 상태."""
    _, end = day_window(day, timezone)
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
    timed: list[str] = []
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
            + wikilink(f"Auto/Events/{event.event_id}.md", event.title)
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
        + wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        for event in sorted(decisions, key=lambda event: event.event_id)
    ] or ["- 표시할 결정 변화가 없습니다."]
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    morning = brief(events, day, timezone, "morning")
    needed = [
        "- "
        + wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        + " · 내일 예정"
        for event in events
        if on_day(event, tomorrow, timezone) and event.event_status == "planned"
    ]
    needed += [
        "- "
        + wikilink(f"Auto/Events/{row['event_id']}.md", row["title"])
        + " · "
        + safe_text(row["reason"])
        for row in morning["followups"]
    ]
    for card in morning["cards"]:
        for past in card["previous_context"]:
            needed.append(
                "- 내일 참고: "
                + wikilink(f"Auto/Events/{past['event_id']}.md", past["title"])
                + " · "
                + safe_text(past["excerpt"][:240])
            )
    if not needed:
        needed = ["- 내일로 넘길 명시 기록이 없습니다."]
    gaps = [
        "- "
        + wikilink(f"Auto/Events/{row['event_id']}.md", row["title"])
        + " · "
        + safe_text(row["question"])
        for row in gap_candidates(events, now=end - timedelta(seconds=1))
        if on_day(
            next(event for event in events if event.event_id == row["event_id"]), day, timezone
        )
    ]
    undated = [event for event in events if event.occurred_start is None]
    gaps += [
        "- 시각 불명: " + wikilink(f"Auto/Events/{event.event_id}.md", event.title)
        for event in undated
    ]
    if not gaps:
        gaps = ["- 확인된 중요 빈칸이 없습니다. 기록이 없는 시간은 활동 없음이 아닙니다."]
    sections: dict[str, list[str]] = {
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
) -> ObsidianManifest:
    """A bounded, complete authorized snapshot. No private source paths or credentials.

    Callers enforce scope/source policies BEFORE passing records to this function.
    Revoked/deleted/expired records must be excluded, including their graph nodes.
    Only previously-owned generated paths may be pruned by the client.
    """
    _ = day_window(day, timezone)
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
        links = [wikilink(evidence_path, "원문 근거")]
        links.extend(
            wikilink(entity_path(event, entity.kind, entity.entity_id), entity.label)
            for entity in event.entities
        )
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
            wikilink(evidence_path, "원문 근거"),
            "",
            f"[정정 요청](obsidian://sb-life-correct?event={event.event_id}&revision={event.revision})",
        ]
        for entity in event.entities:
            ep = entity_path(event, entity.kind, entity.entity_id)
            lines.append(wikilink(ep, entity.label))
            entity_events[ep].append((entity.label, event))
        files[path] = "\n".join(lines) + "\n"
        files[evidence_path] = (
            "# 원문 근거\n\n"
            + wikilink(path, event.title)
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
            + "\n".join("- " + wikilink(f"Auto/Events/{e.event_id}.md", e.title) for _, e in linked)
            + "\n"
        )
    files[f"Auto/Daily/{day}.md"] = daily_markdown(
        visible, day=day, timezone=timezone, complete=complete
    )
    files["Auto/Home.md"] = "# 나의 기억\n\n" + wikilink(f"Auto/Daily/{day}.md", "오늘") + "\n"
    files["Auto/System/Sync-Status.md"] = (
        "# 동기화 상태\n\n허용된 기록의 복제 뷰입니다. MyNotes는 자동 갱신하지 않습니다.\n"
        + ("전체 스냅샷\n" if complete else "부분 스냅샷 — 누락된 파일을 삭제하지 않습니다.\n")
    )
    rows: list[ViewFile] = [
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
