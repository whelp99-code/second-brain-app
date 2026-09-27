"""Deterministic, inert Obsidian projection; only Auto/ and owned Home.md."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sb.life_contracts import LifeError, LifeEventV1, canonical, digest, integer, strict_json
from sb.life_views import EVIDENCE_LABELS, STATE_LABELS, escape_markdown

FOLDERS = {
    "person": "People",
    "company": "Companies",
    "project": "Projects",
    "place": "Places",
    "event": "Events",
    "decision": "Decisions",
}
MAX_FILES = 20000
MAX_VIEW_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ViewFile:
    path: str
    object_id: str
    revision: int
    content: str

    def wire(self, generation: str) -> dict:
        content = self.content.replace(
            'sb_generation: "SB_GENERATION_PLACEHOLDER"', f'sb_generation: "{generation}"', 1
        )
        return {
            "path": self.path,
            "object_id": self.object_id,
            "revision": self.revision,
            "sha256": digest(content),
            "content": content,
        }


def safe_label(value: str) -> str:
    return (
        escape_markdown(value)
        .replace("|", "／")
        .replace("[", "［")
        .replace("]", "］")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def entity_path(scope: str, kind: str, entity_id: str) -> str:
    folder = FOLDERS.get(kind)
    if folder is None:
        raise LifeError("LIFE_ENTITY_KIND_INVALID")
    return f"Auto/{folder}/" + digest(f"{scope}\0{kind}\0{entity_id}") + ".md"


def note(
    path: str, object_id: str, revision: int, title: str, body: str, *, extra: Mapping | None = None
) -> ViewFile:
    from sb.security import mask_sensitive

    title = mask_sensitive(title)
    # JSON strings are valid YAML scalars. Source titles never become YAML syntax.
    fields = {
        "sb_view_schema": 1,
        "sb_object_id": object_id,
        "sb_revision": revision,
        "sb_managed": True,
        "sb_generation": "SB_GENERATION_PLACEHOLDER",
        "aliases": [title],
        **dict(extra or {}),
    }
    front = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )
    return ViewFile(
        path, object_id, revision, f"---\n{front}\n---\n\n# {escape_markdown(title)}\n\n{body}\n"
    )


def evidence_url(event: LifeEventV1) -> str:
    return "obsidian://sb-memory?" + urlencode(
        {"event": event.event_id, "evidence": event.evidence_id}
    )


def event_view(event: LifeEventV1) -> ViewFile:
    restricted = event.sensitivity == "restricted"
    title = "제한된 생활 기록" if restricted else event.title
    body = [
        f"**{STATE_LABELS[event.event_status]} · {EVIDENCE_LABELS[event.evidence_level]}**",
        f"발생: {event.occurred_start or '알 수 없음'} · 정밀도: {event.time_precision}",
        f"관측: {event.observed_at or '알 수 없음'} · 접수: {event.recorded_at}",
        "정확한 위치·건강 본문은 이 뷰에 복제하지 않습니다."
        if restricted
        else escape_markdown(event.body),
        f"[원문 확인]({evidence_url(event)})",
        "정정은 플러그인의 ‘현재 사건 정정’ 명령을 사용합니다.",
    ]
    if not restricted:
        for ref in event.entity_refs:
            path = entity_path(event.scope, ref.kind, ref.entity_id).removesuffix(".md")
            body.append(f"관련 {ref.kind}: [[{path}|{safe_label(ref.name)}]]")
    return note(
        f"Auto/Events/{event.event_id}.md",
        event.event_id,
        event.revision,
        title,
        "\n\n".join(body),
        extra={
            "sb_event_state": event.event_status,
            "sb_evidence_state": event.evidence_level,
            "sb_evidence_id": event.evidence_id,
            "sb_sensitivity": event.sensitivity,
            "sb_time_zone": event.timezone,
        },
    )


def build_view(
    events: Sequence[LifeEventV1],
    *,
    timezone: str,
    health: Mapping,
    questions: Sequence[Mapping] = (),
    briefings: Sequence[Mapping] = (),
) -> tuple[str, tuple[ViewFile, ...], dict]:
    """Input is already authorized. Oversize fails explicitly, never truncates silently."""
    zone = ZoneInfo(timezone)
    files: list[ViewFile] = []
    days: dict[str, list[LifeEventV1]] = {}
    entities: dict[str, tuple[str, str, list[LifeEventV1]]] = {}
    graph_nodes, graph_edges = [], []
    for event in events:
        view = event_view(event)
        files.append(view)
        title = "제한된 생활 기록" if event.sensitivity == "restricted" else event.title
        graph_nodes.append(
            {
                "id": event.event_id,
                "name": title,
                "path": view.path,
                "kind": "event",
                "state": event.event_status,
                "evidence_level": event.evidence_level,
            }
        )
        when = (
            "Undated"
            if event.occurred_start is None
            else datetime.fromisoformat(event.occurred_start).astimezone(zone).date().isoformat()
        )
        days.setdefault(when, []).append(event)
        if event.sensitivity != "restricted":
            for ref in event.entity_refs:
                path = entity_path(event.scope, ref.kind, ref.entity_id)
                entry = entities.setdefault(path, (ref.name, ref.kind, []))
                entry[2].append(event)
                graph_edges.append(
                    {
                        "from": event.event_id,
                        "to": path,
                        "type": "related_to",
                        "evidence_id": event.evidence_id,
                        "revision": event.revision,
                    }
                )
        files.append(
            note(
                f"Auto/Evidence/{event.evidence_id.removeprefix('ev:')}.md",
                event.evidence_id,
                event.revision,
                "원문 근거",
                f"사건: [[Auto/Events/{event.event_id}|{safe_label(title)}]]\n\n"
                f"[인증 후 원문 확인]({evidence_url(event)})\n\n원문은 파일 경로나 관리자 토큰 없이 조회합니다.",
            )
        )
    for path, (name, kind, related) in sorted(entities.items()):
        lines = [
            "원출처에서 관련된 기록입니다. 동명이인이나 실제 소속을 이름만으로 합치지 않습니다.",
            "| 사건 | 상태 | 근거 |",
            "|---|---|---|",
        ]
        for event in sorted(
            related, key=lambda e: (e.occurred_start or "", e.event_id), reverse=True
        ):
            lines.append(
                f"| [[Auto/Events/{event.event_id}|{safe_label(event.title)}]] | {STATE_LABELS[event.event_status]} | [원문]({evidence_url(event)}) |"
            )
        files.append(note(path, path, max(e.revision for e in related), name, "\n".join(lines)))
        graph_nodes.append({"id": path, "name": name, "kind": kind, "path": path})
    for day, items in sorted(days.items()):
        lines = [
            "## 오늘의 기록" if day != "Undated" else "## 발생일을 알 수 없는 기록",
            "빈 시간은 기록이 없다는 뜻이며 실제 활동이 없었다고 판단하지 않습니다.",
            "| 시간 | 사건 | 상태 | 근거 |",
            "|---|---|---|---|",
        ]
        for event in sorted(items, key=lambda e: (e.occurred_start or "", e.event_id)):
            when = (
                "미상"
                if event.occurred_start is None
                else datetime.fromisoformat(event.occurred_start).astimezone(zone).strftime("%H:%M")
            )
            title = "제한된 생활 기록" if event.sensitivity == "restricted" else event.title
            lines.append(
                f"| {when} | [[Auto/Events/{event.event_id}|{safe_label(title)}]] | {STATE_LABELS[event.event_status]} | {EVIDENCE_LABELS[event.evidence_level]} |"
            )
        lines.extend(["", "## 새 결정과 변경"])
        for event in items:
            if (
                event.event_type == "decision"
                or event.event_status == "cancelled"
                or event.revision > 1
            ):
                title = "제한된 생활 기록" if event.sensitivity == "restricted" else event.title
                lines.append(
                    f"- [[Auto/Events/{event.event_id}|{safe_label(title)}]] · 개정 {event.revision} · {STATE_LABELS[event.event_status]}"
                )
        lines.extend(["", "## 아침·저녁 브리핑"])
        for brief in briefings:
            if brief.get("day") == day:
                lines.append(f"- [[Auto/Daily/{day}-{brief['slot']}|{brief['slot']}]]")
        lines.extend(["", "## 중요한 빈칸"])
        day_ids = {e.event_id for e in items}
        for question in questions:
            if question["event_id"] in day_ids:
                lines.append(f"- [[Auto/Questions/{digest(question['question_id'])}|확인할 질문]]")
        lines.extend(
            [
                "",
                "## 내 메모",
                f"[[MyNotes/{day}|직접 작성한 메모 열기]]",
                "이 링크의 개인 메모는 자동 갱신 대상이 아닙니다.",
                "",
                "[[Auto/System/Sync-Status|수집·동기화 상태]]",
            ]
        )
        files.append(
            note(
                f"Auto/Daily/{day}.md",
                "day:" + day,
                max(e.revision for e in items),
                "날짜 미상" if day == "Undated" else day,
                "\n\n".join(lines),
            )
        )
    event_by_id = {e.event_id: e for e in events}
    for question in questions:
        event = event_by_id.get(question.get("event_id"))
        if event is None or event.revision != question.get("event_revision"):
            continue
        prompt = (
            "제한된 기록의 확인 질문입니다. 인증된 화면에서 확인하세요."
            if event.sensitivity == "restricted"
            else question["prompt"]
        )
        files.append(
            note(
                f"Auto/Questions/{digest(question['question_id'])}.md",
                question["question_id"],
                event.revision,
                "확인할 기록",
                escape_markdown(prompt)
                + f"\n\n[[Auto/Events/{event.event_id}|사건 열기]]\n\n질문 응답은 플러그인 명령으로 처리합니다.",
                extra={"sb_question_id": question["question_id"], "sb_event_id": event.event_id},
            )
        )
    for brief in briefings:
        day, slot = brief.get("day"), brief.get("slot")
        if not isinstance(day, str) or slot not in {"morning", "evening", "maintenance"}:
            raise LifeError("LIFE_BRIEF_INVALID")
        # Day is a server-validated ISO calendar date, not an arbitrary client path.
        from datetime import date

        if date.fromisoformat(day).isoformat() != day:
            raise LifeError("LIFE_DAY_INVALID")
        lines = ["출처 기록 기반 요약 · 실제 전달/열람 여부와 별개입니다."]
        for card in brief.get("cards", []):
            event = event_by_id.get(card.get("event_id"))
            if event is None or event.revision != card.get("revision"):
                continue
            title = "제한된 생활 기록" if event.sensitivity == "restricted" else event.title
            lines.append(
                f"- [[Auto/Events/{event.event_id}|{safe_label(title)}]] · {STATE_LABELS[event.event_status]}"
            )
            if event.sensitivity != "restricted":
                lines.append(escape_markdown(str(card.get("summary", ""))))
        files.append(
            note(
                f"Auto/Daily/{day}-{slot}.md",
                f"brief:{day}:{slot}",
                1,
                f"{day} {slot}",
                "\n\n".join(lines),
            )
        )
    health_lines = [
        "수집을 끈 출처는 기억의 빈칸으로 추적하지 않습니다.",
        "| 출처 | 상태 | 마지막 도착 |",
        "|---|---|---|",
    ]
    for source in health.get("sources", []):
        health_lines.append(
            f"| {safe_label(source['source_id'])} | {safe_label(source['state'])} | {source.get('last_seen') or '없음'} |"
        )
    files.append(
        note("Auto/System/Sync-Status.md", "system:sync", 1, "수집 상태", "\n".join(health_lines))
    )
    home = [
        "내 기록을 사건과 근거로 찾아보는 화면입니다. 추정은 사실과 구분합니다.",
        "## 날짜별 기록",
    ]
    home.extend(f"- [[Auto/Daily/{day}|{day}]]" for day in sorted(days, reverse=True))
    home.extend(
        [
            "",
            "## 수집 상태",
            "[[Auto/System/Sync-Status]]",
            "",
            "## 개인 메모",
            "개인 메모는 MyNotes/에 직접 작성합니다.",
        ]
    )
    files.append(note("Home.md", "home", 1, "Second Brain · 내 기억", "\n".join(home)))
    files.sort(key=lambda f: f.path)
    if len(files) > MAX_FILES or sum(len(f.content.encode()) for f in files) > MAX_VIEW_BYTES:
        raise LifeError("LIFE_VIEW_CAPACITY_EXCEEDED", 413)
    if len({f.path for f in files}) != len(files):
        raise LifeError("LIFE_VIEW_PATH_COLLISION", 503)
    generation = "view-v1:" + digest(canonical([(f.path, digest(f.content)) for f in files]))
    return generation, tuple(files), {"nodes": graph_nodes, "edges": graph_edges}


def manifest_page(
    generation: str, files: Sequence[ViewFile], *, cursor: str | None, page_size: int = 100
) -> dict:
    integer(page_size, minimum=1, maximum=100)
    offset = 0
    if cursor:
        try:
            if len(cursor) > 512:
                raise ValueError
            raw = strict_json(
                base64.urlsafe_b64decode(cursor.encode() + b"=" * ((-len(cursor)) % 4))
            )
            if not isinstance(raw, dict) or set(raw) != {"generation", "offset"}:
                raise ValueError
            if raw["generation"] != generation:
                raise LifeError("LIFE_VIEW_GENERATION_CHANGED", 409)
            offset = integer(raw["offset"], maximum=len(files))
        except (ValueError, UnicodeError, TypeError) as exc:
            if isinstance(exc, LifeError):
                raise
            raise LifeError("LIFE_CURSOR_INVALID") from exc
    end = min(len(files), offset + page_size)
    following = (
        None
        if end == len(files)
        else base64.urlsafe_b64encode(canonical({"generation": generation, "offset": end}).encode())
        .decode()
        .rstrip("=")
    )
    return {
        "schema_version": 1,
        "generation": generation,
        "offset": offset,
        "total_files": len(files),
        "files": [f.wire(generation) for f in files[offset:end]],
        "next_cursor": following,
        "inventory_complete": following is None,
        "replace_owned": True,
        "tombstone_policy": "remove_previous_owned_paths_absent_from_completed_inventory",
        "my_notes_policy": "never_modify",
    }
