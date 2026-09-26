"""Pure enriched Obsidian projections and generation-bound paging.

Inputs have already been authorized. No filesystem, database or network I/O.
All user-authored text is escaped using the existing life view boundary.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any
from urllib.parse import quote

from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_values import canonical_bytes, instant, zone
from sb.life_views import obsidian_manifest, safe_text


def _path(kind: str, identity: str) -> str:
    return "Auto/" + kind + "/" + sha256(identity.encode()).hexdigest() + ".md"


def _event_link(event_id: str, label: str) -> str:
    return "[[Auto/Events/" + event_id + "|" + safe_text(label) + "]]"


def project(
    events: Sequence[LifeEventV1],
    *,
    day: str,
    timezone: str,
    sensitivities: tuple[str, ...],
    complete: bool,
    workflows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    base = obsidian_manifest(
        events, day=day, timezone=timezone, sensitivities=sensitivities, complete=complete
    )
    files = {row["path"]: row["content"] for row in base["files"]}
    visible = {e.event_id: e for e in events if e.sensitivity in sensitivities}
    history: dict[str, list[LifeEventV1]] = defaultdict(list)
    for event in visible.values():
        if event.occurred_start is not None:
            date = instant(event.occurred_start).astimezone(zone(timezone)).date().isoformat()
            history[date].append(event)
        if event.event_type == "decision":
            files[f"Auto/Decisions/{event.event_id}.md"] = (
                "# "
                + safe_text(event.title)
                + "\n\n"
                + _event_link(event.event_id, "사건과 근거")
                + "\n\n"
                + safe_text(event.body)
                + "\n"
                + "상태: "
                + event.event_status
                + " / "
                + event.evidence_level
                + "\n"
            )
    for date, items in sorted(history.items()):
        if date == day:
            continue
        lines = ["# " + date, "", "## 시간순 기록"]
        for event in sorted(items, key=lambda e: (e.occurred_start, e.event_id)):
            at = instant(event.occurred_start).astimezone(zone(timezone)).strftime("%H:%M")
            lines.append(
                "- "
                + at
                + " · "
                + event.event_status
                + " · "
                + _event_link(event.event_id, event.title)
            )
        lines += [
            "",
            "## 내 메모",
            "[[MyNotes/" + date + "]]",
            "",
            "과거 기록 화면입니다. 기록이 없는 시간을 활동 없음으로 해석하지 않습니다.",
        ]
        files[f"Auto/Daily/{date}.md"] = "\n".join(lines) + "\n"
    dates = sorted(set(history) | {day}, reverse=True)
    files["Auto/History.md"] = (
        "# 날짜별 기억\n\n"
        + "\n".join("- [[Auto/Daily/" + date + "|" + date + "]]" for date in dates)
        + "\n"
    )
    files["Auto/Home.md"] += (
        "\n[[Auto/History|날짜별 기록]]\n[[Auto/Questions|확인할 기록]]\n[[Auto/Relations|관계]]\n[[Auto/Predictions|예측과 실제 결과]]\n"
    )
    workflows = workflows or {}
    question_links = []
    for row in workflows.get("question", ()):
        body = row["body"]
        path = _path("Questions", row["object_id"])
        qid = quote(row["object_id"], safe="")
        lines = [
            "# " + safe_text(body.get("title", "기록 확인")),
            "",
            "상태: " + safe_text(body["state"]),
            "",
            safe_text(body["prompt"]),
            "",
            _event_link(body["event_id"], "대상 사건과 근거"),
        ]
        if body["state"] == "open":
            lines.append(
                "\n[답변·건너뛰기·다시 묻지 않기](obsidian://sb-life-question?id="
                + qid
                + "&revision="
                + str(row["revision"])
                + ")"
            )
        elif "answer" in body:
            lines += ["", "사용자 응답: " + safe_text(body["answer"])]
        files[path] = "\n".join(lines) + "\n"
        question_links.append(
            "- [[" + path[:-3] + "|" + safe_text(body.get("title", "기록 확인")) + "]]"
        )
    files["Auto/Questions.md"] = "# 확인할 기록\n\n" + "\n".join(question_links) + "\n"
    relation_lines = [
        "# 근거가 있는 관계",
        "",
        "타입·효력·근거가 보존된 관계입니다. 추정은 확정과 다릅니다.",
        "",
    ]
    for row in workflows.get("relation", ()):
        b = row["body"]
        relation_lines += [
            "## " + safe_text(b["relation_kind"]),
            safe_text(b["from_id"]) + " → " + safe_text(b["to_id"]),
            "상태: " + safe_text(b["state"]) + " / " + safe_text(b["evidence_level"]),
            "효력: "
            + safe_text(b.get("valid_from") or "미지정")
            + " ~ "
            + safe_text(b.get("valid_until") or "미지정"),
        ]
        relation_lines += [
            "- " + _event_link(ref["event_id"], "근거 사건") for ref in row["evidence"]
        ]
    for row in workflows.get("entity_alias", ()):
        b = row["body"]
        relation_lines += [
            "",
            "동일인 연결: " + safe_text(b["from_id"]) + " → " + safe_text(b["to_id"]),
            "상태: " + safe_text(b["state"]),
            "근거: " + safe_text(b["reason"]),
        ]
    files["Auto/Relations.md"] = "\n".join(relation_lines) + "\n"
    prediction_lines = [
        "# 예측과 실제 결과",
        "",
        "예측은 확정 사실이 아닙니다. 표본 부족과 결과 결측은 별도로 표시합니다.",
        "",
    ]
    actuals = {r["body"]["prediction_id"]: r["body"] for r in workflows.get("actual", ())}
    for row in workflows.get("prediction", ()):
        b = row["body"]
        path = _path("Predictions", row["object_id"])
        lines = [
            "# 소요시간 예측",
            "",
            "상태: " + safe_text(b["state"]),
            "대상: " + safe_text(b["target_id"]),
            "발행: " + safe_text(b["issued_at"]),
            "표본: " + str(b["sample_count"]),
            "예상 분: "
            + ("자료 부족" if b["estimate_minutes"] is None else str(b["estimate_minutes"])),
            "통계적 충분성·보정된 신뢰구간을 보장하지 않습니다.",
        ]
        actual = actuals.get(row["object_id"])
        if actual:
            lines += [
                "",
                "실제 결과 상태: " + safe_text(actual["state"]),
                "실제 분: "
                + ("결측" if actual["actual_minutes"] is None else str(actual["actual_minutes"])),
                "절대 오차: "
                + (
                    "미채점"
                    if actual["absolute_error_minutes"] is None
                    else str(actual["absolute_error_minutes"])
                ),
            ]
        lines += ["", "## 근거"] + [
            "- " + _event_link(ref["event_id"], "사건 근거") for ref in row["evidence"]
        ]
        files[path] = "\n".join(lines) + "\n"
        prediction_lines.append("- [[" + path[:-3] + "|" + safe_text(b["target_id"]) + "]]")
    files["Auto/Predictions.md"] = "\n".join(prediction_lines) + "\n"
    rows = [
        {"path": path, "content": content, "sha256": sha256(content.encode()).hexdigest()}
        for path, content in sorted(files.items())
    ]
    generation = sha256(canonical_bytes(rows)).hexdigest()
    return {
        **base,
        "files": rows,
        "generation": generation,
        "cursor": generation,
        "day": day,
        "timezone": timezone,
    }


def page(manifest: dict[str, Any], *, limit: int, cursor: str | None = None) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise LifeInputError("LIFE_LIMIT_INVALID")
    offset = 0
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 1000:
                raise ValueError
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if (
                not isinstance(value, list)
                or len(value) != 2
                or type(value[1]) is not int
                or value[1] < 0
            ):
                raise ValueError
            if value[0] != manifest["generation"]:
                raise LifeInputError("LIFE_VIEW_GENERATION_CONFLICT")
            offset = value[1]
        except (ValueError, TypeError) as exc:
            if isinstance(exc, LifeInputError):
                raise
            raise LifeInputError("LIFE_CURSOR_INVALID") from exc
    files = manifest["files"]
    if offset > len(files):
        raise LifeInputError("LIFE_CURSOR_INVALID")
    end = min(offset + limit, len(files))
    next_cursor = (
        None
        if end == len(files)
        else base64.urlsafe_b64encode(canonical_bytes([manifest["generation"], end]))
        .decode()
        .rstrip("=")
    )
    return {
        **manifest,
        "files": files[offset:end],
        "page_offset": offset,
        "total_files": len(files),
        "next_cursor": next_cursor,
        "page_complete": next_cursor is None,
        "complete": bool(manifest["complete"] and offset == 0 and next_cursor is None),
        "snapshot_complete": manifest["complete"],
    }
