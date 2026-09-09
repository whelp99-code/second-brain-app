"""Shared credential-only redaction; contact details are preserved."""

from __future__ import annotations

import re
from typing import Final

_AWS: Final = re.compile(r"AKIA[0-9A-Z]{16}")
_GITHUB: Final = re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")
_OPENAI: Final = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
_PEM: Final = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    flags=re.DOTALL,
)
_ASSIGN: Final = re.compile(r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+")
_ASSIGN_LABELS: Final[dict[str, str]] = {
    "password": "password",
    "passwd": "password",
    "token": "token",
    "secret": "secret",
}

def _assignment_repl(match: re.Match[str]) -> str:
    raw = match.group(1).lower()
    return f"[REDACTED:{_ASSIGN_LABELS.get(raw, raw)}]"


def redact_credentials(text: str) -> str:
    # Necessary literal gates only; preserve regexes and replacement order.
    redacted = text
    if "-----BEGIN " in redacted:
        redacted = _PEM.sub("[REDACTED:pem]", redacted)
    if "AKIA" in redacted:
        redacted = _AWS.sub("[REDACTED:aws]", redacted)
    if "gh" in redacted:
        redacted = _GITHUB.sub("[REDACTED:github]", redacted)
    if "sk-" in redacted:
        redacted = _OPENAI.sub("[REDACTED:openai]", redacted)
    if "=" in redacted or ":" in redacted:
        redacted = _ASSIGN.sub(_assignment_repl, redacted)
    return redacted


