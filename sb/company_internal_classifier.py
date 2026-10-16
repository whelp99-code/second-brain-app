from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from sb.company_memory import MemoryCandidate
from sb.effect_values import parse_instant

RecordKind = Literal["contact", "calendar", "progress"]
Classification = Literal["auto_internal", "human_required"]

_HEADER: Final = "sb-internal-mail/v1"
_KINDS: Final[frozenset[str]] = frozenset({"contact", "calendar", "progress"})
_CONTACT_KEYS: Final[tuple[str, ...]] = ("name", "email", "phone", "department")
_CALENDAR_KEYS: Final[tuple[str, ...]] = (
    "title",
    "starts_at",
    "ends_at",
    "timezone",
    "internal_assignee",
)
_PROGRESS_KEYS: Final[tuple[str, ...]] = (
    "subject",
    "status",
    "internal_assignee",
    "next_internal_action",
)
_OPTIONAL_CONTACT: Final[frozenset[str]] = frozenset({"phone", "department"})
_TIMEZONES: Final[frozenset[str]] = frozenset({"Asia/Seoul", "UTC"})
_STATUSES: Final[frozenset[str]] = frozenset({"noted", "in_progress", "waiting_internal"})
_EMAIL: Final = re.compile(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\Z")
_VETO: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "prompt_injection",
        re.compile(
            r"ignore previous|ignore all instructions|이 규칙을 무시|자동 승인|you are now",
            re.IGNORECASE,
        ),
    ),
    (
        "money",
        re.compile(
            r"금액|견적|할인|지급|결제|환불|청구|송금|정산|급여|수당|₩|[$£€¥]|"
            + r"\d+\s*(?:원|%|퍼센트)|\b(?:USD|KRW|EUR|GBP|JPY|CNY|"
            + r"payment|pay|paid|quote|quotation|discount|invoice|refund|"
            + r"salary|compensation|transfer funds|bank transfer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "contract",
        re.compile(r"계약|\b(?:contract|agreement|NDA|MOU|purchase order)\b", re.IGNORECASE),
    ),
    ("tax", re.compile(r"세금|세무|부가세|\btax\b|\bVAT\b", re.IGNORECASE)),
    ("invite", re.compile(r"초대|\binvite\b", re.IGNORECASE)),
    (
        "outgoing",
        re.compile(
            r"발송|송신|외부 참석|external attendee|"
            + r"\b(?:send|email|notify|contact|call)\s+(?:an?\s+|the\s+)?(?:customer|client|vendor|email)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "customer_deletion",
        re.compile(r"고객\s*삭제|고객정보\s*삭제|delete\s+customer|고객\s*비활성화", re.IGNORECASE),
    ),
)


@dataclass(frozen=True, slots=True)
class FieldSpan:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class InternalClassification:
    classification: Classification
    reason_codes: tuple[str, ...]
    record_kind: RecordKind | None
    fields: dict[str, str]
    spans: dict[str, FieldSpan]


def content_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def classify_mail_candidate(candidate: MemoryCandidate) -> InternalClassification:
    reasons: list[str] = []
    if candidate.source_system != "mail" or not candidate.source_event_id:
        reasons.append("source_unknown")
    if content_digest(candidate.content) != candidate.content_digest:
        reasons.append("source_unknown")
    text = candidate.content
    if "\x00" in text or "\r" in text:
        reasons.append("ambiguous")
    reasons.extend(code for code, pattern in _VETO if pattern.search(text))
    parsed = _parse_block(text)
    if parsed is None:
        reasons.append("ambiguous")
        return _human(tuple(dict.fromkeys(reasons)))
    kind, fields, spans = parsed
    structural = _structural_reasons(kind, fields)
    reasons.extend(structural)
    if reasons:
        return _human(tuple(dict.fromkeys(reasons)))
    return InternalClassification("auto_internal", (), kind, fields, spans)


def _human(reasons: tuple[str, ...]) -> InternalClassification:
    if not reasons:
        reasons = ("ambiguous",)
    return InternalClassification("human_required", reasons, None, {}, {})


def _parse_block(
    text: str,
) -> tuple[RecordKind, dict[str, str], dict[str, FieldSpan]] | None:
    if text.count(_HEADER) != 1 or not text.endswith("\n"):
        return None
    lines = text[:-1].split("\n")
    if len(lines) < 3 or lines[0] != _HEADER or not lines[-1]:
        return None
    kind_line = lines[1]
    if not kind_line.startswith("kind: "):
        return None
    kind = _kind(kind_line.removeprefix("kind: "))
    if kind is None:
        return None
    expected = _keys_for(kind)
    fields: dict[str, str] = {}
    spans: dict[str, FieldSpan] = {}
    cursor = len(lines[0]) + 1 + len(lines[1]) + 1
    for line in lines[2:]:
        if not line or ": " not in line:
            return None
        key, value = line.split(": ", 1)
        if key in fields or not value or value != value.strip():
            return None
        start = cursor + len(key) + 2
        end = start + len(value)
        if text[start:end] != value:
            return None
        fields[key] = value
        spans[key] = FieldSpan(start, end)
        cursor = end + 1
    if tuple(fields) != _present_keys(kind, fields, expected):
        return None
    return kind, fields, spans


def _keys_for(kind: RecordKind) -> tuple[str, ...]:
    match kind:
        case "contact":
            return _CONTACT_KEYS
        case "calendar":
            return _CALENDAR_KEYS
        case "progress":
            return _PROGRESS_KEYS


def _present_keys(
    kind: RecordKind, fields: dict[str, str], expected: tuple[str, ...]
) -> tuple[str, ...]:
    match kind:
        case "contact":
            required = tuple(key for key in expected if key not in _OPTIONAL_CONTACT)
            optional = tuple(key for key in expected if key in _OPTIONAL_CONTACT and key in fields)
            if not set(required) <= set(fields):
                return ()
            return required + optional
        case "calendar" | "progress":
            if set(fields) != set(expected):
                return ()
            return expected


def _structural_reasons(kind: RecordKind, fields: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    match kind:
        case "contact":
            email = fields.get("email", "")
            if _EMAIL.fullmatch(email) is None:
                reasons.append("ambiguous")
        case "calendar":
            if fields.get("timezone") not in _TIMEZONES:
                reasons.append("timezone_unknown")
            start = _instant(fields.get("starts_at", ""))
            end = _instant(fields.get("ends_at", ""))
            if start is None or end is None or end <= start:
                reasons.append("ambiguous")
        case "progress":
            if fields.get("status") not in _STATUSES:
                reasons.append("ambiguous")
    return reasons


def _kind(value: str) -> RecordKind | None:
    match value:
        case "contact" | "calendar" | "progress":
            return value
        case _:
            return None


def _instant(value: str) -> datetime | None:
    try:
        return parse_instant(value)
    except ValueError:
        return None
