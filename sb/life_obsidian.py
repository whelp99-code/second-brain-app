"""Pure deterministic Life projections; no I/O."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from hashlib import sha256

from sb.life_brief import brief
from sb.life_contracts import LifeEventV1
from sb.life_rendering import entity_path, on_day, safe_text, wikilink
from sb.life_values import canonical_bytes, day_window, instant, zone
from sb.life_view_contracts import (
    ObsidianManifest,
    ViewFile,
)


def obsidian_manifest(
    events: Sequence[LifeEventV1],
    *,
    day: str,
    timezone: str,
    sensitivities: tuple[str, ...] = ("public", "personal"),
    complete: bool = True,
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
    files: dict[str, str] = {}
    entity_events: dict[str, list[tuple[str, LifeEventV1]]] = defaultdict(list)
    local_zone = zone(timezone)
    day_lines: list[tuple[str, str, str]] = []
    for event in visible:
        path = f"Auto/Events/{event.event_id}.md"
        evidence_path = f"Auto/Evidence/{event.event_id}.md"
        lines = [
            "---",
            "sb_view_schema: 1",
            f'sb_object_id: "{event.event_id}"',
            f"sb_revision: {event.revision}",
            "sb_managed: true",
            "sb_event_state: " + event.event_status,
            "sb_evidence_state: " + event.evidence_level,
            "---",
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
        if on_day(event, day, timezone):
            stamp = instant(event.occurred_start).astimezone(local_zone).strftime("%H:%M")
            day_lines.append(
                (
                    event.occurred_start or "",
                    event.event_id,
                    f"- {stamp} · {event.event_status} · " + wikilink(path, event.title),
                )
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
    morning = brief(visible, day, timezone, "morning")
    evening = brief(visible, day, timezone, "evening")
    daily = [
        "# " + day,
        "",
        "## 오늘의 요점",
        "실제 수집 기록만 표시합니다.",
        "",
        "## 시간순 기록",
        *[row[2] for row in sorted(day_lines)],
        "",
        "## 아침 참고",
        *["- " + safe_text(c["title"]) for c in morning["cards"]],
        *[
            "  - 이전 맥락: "
            + wikilink(f"Auto/Events/{past['event_id']}.md", past["title"])
            + " · "
            + safe_text(past["excerpt"][:400])
            for card in morning["cards"]
            for past in card["previous_context"]
        ],
        "",
        "## 완료 여부를 확인할 기록",
        *[
            "- "
            + wikilink(f"Auto/Events/{row['event_id']}.md", row["title"])
            + " · "
            + safe_text(row["reason"])
            for row in morning["followups"]
        ],
        "",
        "## 저녁 정리",
        *["- " + safe_text(c["title"]) + " · " + c["event_status"] for c in evening["cards"]],
        "",
        "## 내 메모",
        f"[[MyNotes/{day}]]",
        "",
        "## 수집 상태",
        "기록이 없는 시간을 실제 활동 없음으로 해석하지 않습니다.",
        "[[Auto/System/Sync-Status]]",
    ]
    files[f"Auto/Daily/{day}.md"] = "\n".join(daily) + "\n"
    files["Auto/Home.md"] = "# 나의 기억\n\n" + wikilink(f"Auto/Daily/{day}.md", "오늘") + "\n"
    files["Auto/System/Sync-Status.md"] = (
        "# 동기화 상태\n\n허용된 기록의 복제 뷰입니다. MyNotes는 자동 갱신하지 않습니다.\n"
        + ("전체 스냅샷\n" if complete else "부분 스냅샷 — 누락된 파일을 삭제하지 않습니다.\n")
    )
    rows: list[ViewFile] = [
        {"path": path, "content": content, "sha256": sha256(content.encode()).hexdigest()}
        for path, content in sorted(files.items())
    ]
    generation = sha256(canonical_bytes(rows)).hexdigest()
    return {
        "schema_version": 1,
        "generation": generation,
        "complete": complete,
        "files": rows,
        "managed_prefix": "Auto/",
        "cursor": generation,
    }
