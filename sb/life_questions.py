"""Persistent bounded confirmation questions, using the existing life journal.

Collection failures are operational signals, never fabricated gaps in a life.
All mutating functions run inside the caller's existing writer transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from sb.effect_values import JsonInput, JsonObject
from sb.life_config import LifeSettingsV1
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.life_fields import string
from sb.life_journal_contracts import EventMutation, JournalRow
from sb.life_json import decode_json
from sb.life_values import canonical_bytes, instant, text, zone
from sb.store.life_journal import LifeJournal, identity
from sb.store.life_rows import all_rows


def quiet(now: datetime, opts: LifeSettingsV1) -> bool:
    hour = now.astimezone(zone(opts.timezone)).hour
    start, end = opts.quiet_start, opts.quiet_end
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end


def candidate(event: LifeEventV1, now: datetime) -> tuple[str, str] | None:
    if event.review_state == "disputed":
        return (
            "conflict",
            "이 기록의 내용이 충돌 상태입니다. 근거를 확인하고 현재 내용을 알려주세요.",
        )
    if event.event_status == "cancelled" or event.event_type.startswith(("health_", "location_")):
        return None
    ended = event.occurred_end or event.occurred_start
    if ended is None or instant(ended) >= now:
        return None
    if event.event_type == "calendar_event" and event.event_status in {"planned", "unknown"}:
        return (
            "occurrence",
            "예정된 일정의 실제 진행 여부가 기록되지 않았습니다. 진행했나요, 취소됐나요?",
        )
    if event.event_status == "occurred" and not event.body.strip():
        return "result", "진행된 일의 결과 기록이 없습니다. 기억해 둘 결과가 있나요?"
    return None


def issue(
    journal: LifeJournal,
    events: Sequence[LifeEventV1],
    *,
    opts: LifeSettingsV1,
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> list[JournalRow]:
    opts.require("gap_questions")
    if quiet(now, opts) or opts.question_budget == 0:
        return []
    local_day = now.astimezone(zone(opts.timezone)).date().isoformat()
    with journal.transaction():
        existing: list[JournalRow] = []
        for (qid,) in all_rows(
            journal.connection, "SELECT object_id FROM life_workflow_heads WHERE kind='question'"
        ):
            row = journal.raw("question", string(qid))
            owners = {s for s in scopes if s.startswith(("owner:", "principal:"))}
            if row is not None and (
                owners.intersection(row["scopes"]) or set(row["scopes"]).issubset(scopes)
            ):
                existing.append(row)
        used = sum(row["body"].get("issued_day") == local_day for row in existing)
        remaining = max(0, opts.question_budget - used)
        proposals: list[tuple[int, LifeEventV1, str, str]] = []
        for event in events:
            selected = candidate(event, now)
            if (
                selected is None
                or not set(event.scopes).issubset(scopes)
                or event.source_id not in source_ids
            ):
                continue
            kind, prompt = selected
            previous = [
                row["body"] for row in existing if row["body"].get("event_id") == event.event_id
            ]
            if any(p.get("state") == "muted" for p in previous):
                continue
            if any(
                now - instant(p["issued_at"]) < timedelta(hours=opts.question_cooldown_hours)
                for p in previous
            ):
                continue
            proposals.append((0 if kind == "conflict" else 1, event, kind, prompt))
        proposals.sort(key=lambda p: (p[0], p[1].occurred_start or "", p[1].event_id))
        result: list[JournalRow] = []
        for _, event, kind, prompt in proposals[:remaining]:
            qid = identity("question", [event.event_id, event.revision, kind])
            prior = journal.raw("question", string(qid))
            if prior is not None:
                continue
            body: JsonObject = {
                "event_id": event.event_id,
                "event_revision": event.revision,
                "question_kind": kind,
                "prompt": prompt,
                "state": "open",
                "issued_at": now.isoformat(),
                "issued_day": local_day,
                "title": event.title,
                "delivery_state": "not_attempted",
            }
            result.append(journal.put("question", qid, body, events=(event,), now=now))
        return result


def prepare_response(
    journal: LifeJournal,
    question_id: str,
    data: Mapping[str, JsonInput],
    *,
    events: Sequence[LifeEventV1],
    scopes: tuple[str, ...],
    source_ids: tuple[str, ...],
    now: datetime,
) -> tuple[JournalRow, EventMutation | None]:
    if set(data) - {"action", "answer", "event_status", "idempotency_key", "expected_revision"}:
        raise LifeInputError("LIFE_UNKNOWN_FIELD")
    action = data.get("action")
    if not isinstance(action, str) or action not in {"answer", "skip", "mute"}:
        raise LifeInputError("LIFE_RESPONSE_INVALID")
    key = text(data.get("idempotency_key"), maximum=256)
    request_digest = sha256(
        canonical_bytes({k: v for k, v in data.items() if k != "idempotency_key"})
    ).hexdigest()
    row = journal.get("question", question_id, scopes=scopes, source_ids=source_ids, events=events)
    if row["body"].get("response_key") == key:
        if row["body"].get("response_digest") != request_digest:
            raise LifeInputError("LIFE_IDEMPOTENCY_CONFLICT")
        return row, None
    if (
        row["body"]["state"] != "open"
        or type(data.get("expected_revision")) is not int
        or data.get("expected_revision") != row["revision"]
    ):
        raise LifeInputError("LIFE_REVISION_CONFLICT")
    event = next(e for e in events if e.event_id == row["body"]["event_id"])
    body: JsonObject = {
        **row["body"],
        "state": {"answer": "answered", "skip": "skipped", "mute": "muted"}[action],
        "response_key": key,
        "response_action": action,
        "response_digest": request_digest,
        "responded_at": now.isoformat(),
    }
    mutation: EventMutation | None = None
    if action == "answer":
        answer = text(data.get("answer"), maximum=10000)
        body["answer"] = answer
        original = decode_json(journal.store.evidence(event.event_id, scopes=scopes, now=now))
        if not isinstance(original, dict):
            raise LifeInputError("LIFE_RECORD_CORRUPT")
        original.update(
            body=answer,
            change_reason="사용자의 기록 확인 질문 응답",
            source_version="answer-" + identity("question", key).split(":", 1)[1],
            evidence_level="user_asserted",
            review_state="confirmed",
        )
        if "event_status" in data:
            original["event_status"] = string(data["event_status"], "LIFE_EVENT_STATUS_INVALID")
        mutation = {
            "source_id": event.source_id,
            "event_id": event.event_id,
            "idempotency_key": "question-response-" + key,
            "expected_revision": event.revision,
            "payload": original,
        }
    # Parent performs the event change and publishes it in the SAME writer stage.
    return {**row, "body": body}, mutation


def finish_response(
    journal: LifeJournal, prepared: JournalRow, *, evidence: LifeEventV1, now: datetime
) -> JournalRow:
    return journal.put(
        "question",
        prepared["object_id"],
        prepared["body"],
        events=(evidence,),
        now=now,
        expected_revision=prepared["revision"],
    )
