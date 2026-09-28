"""Frozen pre-optimization policy oracle, including overlapping replacements."""

from __future__ import annotations

import random
import re

import pytest

from sb.redaction import redact_credentials
from sb.security import mask_sensitive


def _previous_mask(text: str) -> str:
    text = re.sub(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        "[REDACTED_PRIVATE_KEY]", text, flags=re.DOTALL,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [REDACTED_TOKEN]", text)
    # Widened on 2026-09-20 to reach compound and quoted keys; the oracle tracks the
    # policy so this file keeps proving that the fast-path guards in mask_sensitive
    # do not change its meaning, which is the only thing it was ever for.
    text = re.sub(
        r"(?im)([A-Za-z0-9_.-]*"
        + r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|password|passwd|secret))\b"
        + r"[\"\']?\s*[:=]\s*([^\s,;]{4,})",
        lambda match: f"{match.group(1)}=[REDACTED_SECRET]", text,
    )
    return re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[REDACTED_EMAIL]", text)


def _previous_redact(text: str) -> str:
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED:pem]", text, flags=re.DOTALL,
    )
    text = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED:aws]", text)
    text = re.sub(r"gh[pousr]_[A-Za-z0-9]{36,}", "[REDACTED:github]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED:openai]", text)
    labels = {"password": "password", "passwd": "password", "token": "token", "secret": "secret"}
    return re.sub(
        r"(?i)(password|passwd|token|secret)\s*[=:]\s*\S+",
        lambda match: f"[REDACTED:{labels.get(match.group(1).lower(), match.group(1).lower())}]",
        text,
    )


_FRAGMENTS = (
    "", "일반 기억과 결정", "no separators or identifiers", "@", "=", ":", "\x00", "\r\n",
    "İıſK", "owner@EXAMPLE.com", "ｂｅａｒｅｒ", "bEaReR\u2003abcdefghijkl",
    "Bearer\r\nabcdefghijklmnop", "XBearer abcdefghijklmnop", "Bearer abcdefghijk",
    "password=abcd", "PASSWORD : abcd", "paſſword=abcd", "api_Key=abcdefgh",
    "access-token : owner@example.com", "password=Bearer abcdefghijklmnop",
    "password=-----BEGIN PRIVATE KEY-----\nbody\n-----END PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----\nowner@example.com\n-----END RSA PRIVATE KEY-----",
    "-----BEGIN X9 PRIVATE KEY-----\x00body\n-----END X9 PRIVATE KEY-----",
    "-----begin PRIVATE KEY-----body-----end PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----unfinished", "secret=ab;cd", "token=xyz",
    "AKIA" + "A" * 16, "akIA" + "A" * 16, "ghp_" + "z" * 36,
    "gho_" + "z" * 35, "sk-" + "a" * 20, "SK-" + "a" * 20,
    "[REDACTED:pem]", "secret=password=123456", "010-1234-5678",
)


@pytest.mark.parametrize("text", _FRAGMENTS)
def test_known_boundaries_match_previous_policy(text: str) -> None:
    assert mask_sensitive(text) == _previous_mask(text)
    assert redact_credentials(text) == _previous_redact(text)


def test_seeded_unicode_and_overlaps_match_previous_policy() -> None:
    rng = random.Random(20260908)
    for _ in range(2000):
        text = "".join(rng.choices(_FRAGMENTS, k=rng.randrange(1, 15)))
        assert mask_sensitive(text) == _previous_mask(text)
        assert redact_credentials(text) == _previous_redact(text)


def test_storage_contacts_and_prompt_copy_remain_distinct() -> None:
    text = "담당 owner@example.com 010-1234-5678 password=abcdefgh"
    assert redact_credentials(text) == "담당 owner@example.com 010-1234-5678 [REDACTED:password]"
    assert mask_sensitive(text) == "담당 [REDACTED_EMAIL] 010-1234-5678 password=[REDACTED_SECRET]"
