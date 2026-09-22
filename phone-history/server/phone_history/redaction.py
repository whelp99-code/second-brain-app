"""Conservative redaction and untrusted-content risk labelling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    redaction_count: int
    risk_flags: tuple[str, ...]


_REDACT_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        "credential_assignment",
        re.compile(
            r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\b"
            r"\s*[:=]\s*[^\s,;]{6,}",
            re.IGNORECASE,
        ),
        "[REDACTED_CREDENTIAL]",
    ),
    (
        "resident_number",
        re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)"),
        "[REDACTED_RESIDENT_ID]",
    ),
    (
        "phone",
        re.compile(r"(?<!\d)(?:\+?82[- ]?)?0?1[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
        "[REDACTED_PHONE]",
    ),
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[REDACTED_EMAIL]",
    ),
)

_RISK_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "ignore_instructions",
        re.compile(
            r"(?:ignore|disregard|forget).{0,40}(?:previous|above|prior).{0,30}instructions?",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(r"(?:system|developer).{0,20}prompt|reveal.{0,30}instructions", re.IGNORECASE),
    ),
    (
        "tool_execution",
        re.compile(
            r"(?:run|execute|invoke|call).{0,25}(?:shell|terminal|command|tool|script)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"(?:send|upload|post|expose|reveal).{0,30}"
            r"(?:token|password|secret|credential|api key)",
            re.IGNORECASE,
        ),
    ),
    (
        "policy_bypass",
        re.compile(
            r"(?:bypass|disable|evade).{0,30}(?:safety|security|policy|guard)",
            re.IGNORECASE,
        ),
    ),
)


def redact_text(value: str | None) -> RedactionResult:
    if not value:
        return RedactionResult(text="", redaction_count=0, risk_flags=())
    text = value
    count = 0
    for _name, pattern, replacement in _REDACT_PATTERNS:
        text, substitutions = pattern.subn(replacement, text)
        count += substitutions
    flags = tuple(name for name, pattern in _RISK_PATTERNS if pattern.search(value))
    return RedactionResult(text=text, redaction_count=count, risk_flags=flags)


def redact_fields(*values: str | None) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
    """Redact fields and merge stable, de-duplicated risk flags."""
    outputs: list[str] = []
    count = 0
    flags: set[str] = set()
    for value in values:
        result = redact_text(value)
        outputs.append(result.text)
        count += result.redaction_count
        flags.update(result.risk_flags)
    return tuple(outputs), count, tuple(sorted(flags))
