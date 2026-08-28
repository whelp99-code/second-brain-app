"""Given/When/Then tests for deterministic normalize chunking and redaction."""

from __future__ import annotations

import hashlib

import pytest

from sb.contracts import Blob
from sb.normalize import NORMALIZER_VERSION, normalize

_ORIGIN: str = "me-wiki:notes.md"
_AWS_KEY: str = "AKIA0123456789ABCDEF"
_AWS_SHORT: str = "AKIA0123456789ABCDE"
_GITHUB_TOKEN: str = "ghp_" + ("A" * 36)
_GITHUB_QA: str = "ghp_" + ("B" * 40)
_GITHUB_WRONG: str = "gha_" + ("C" * 40)
_OPENAI_KEY: str = "sk-" + ("D" * 20)
_OPENAI_SHORT: str = "sk-" + ("E" * 19)
_PEM_PRIVATE: str = (
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEfakeprivatekeymaterial\n-----END RSA PRIVATE KEY-----"
)
_PEM_PUBLIC: str = "-----BEGIN PUBLIC KEY-----\nMIIBfakepublic\n-----END PUBLIC KEY-----"
_EMAIL: str = "owner@example.com"
_PHONE: str = "+1-555-0100"
_PHONE_KR: str = "010-1234-5678"
_FIXTURE_SPANS: tuple[str, ...] = (
    "0-3716",
    "3206-7008",
    "6505-10338",
    "9820-11736",
)
_FIXTURE_HEADS: tuple[str, ...] = (
    "## Notes 1\n\nPersonal vault note 1 record",
    "Personal vault note 6 records the daily ",
    "Personal vault note 12 records the daily",
    "Personal vault note 17 records the daily",
)


def _blob(text: str) -> Blob:
    payload = text.encode()
    return Blob(hash=hashlib.sha256(payload).hexdigest(), size=len(payload))


def _long_markdown() -> str:
    sentence = "Personal vault note {i} records the daily briefing and cited wiki pages. "
    parts = [f"## Notes {i}\n\n{sentence.format(i=i) * 8}" for i in range(1, 21)]
    return "\n\n".join(parts)


def _ids(text: str, origin: str = _ORIGIN) -> list[str]:
    units = normalize(_blob(text), text, origin)
    return [unit.unit_id for unit in units]


def test_unit_ids_match_when_normalized_twice() -> None:
    text = _long_markdown()
    first = _ids(text)
    second = _ids(text)
    assert first == second
    assert first != []


def test_unit_ids_match_when_normalized_twice_on_short_text() -> None:
    text = "A single cited sentence about the personal vault."
    first = _ids(text, origin="inbox:note.md")
    second = _ids(text, origin="inbox:note.md")
    assert first == second
    assert len(first) == 1


def test_chunk_spans_and_heads_match_fixture_when_long_markdown() -> None:
    text = _long_markdown()
    units = normalize(_blob(text), text, _ORIGIN)
    assert [unit.span for unit in units] == list(_FIXTURE_SPANS)
    assert [unit.text[:40] for unit in units] == list(_FIXTURE_HEADS)
    assert [unit.content_hash for unit in units] == [_blob(text).hash] * len(units)


def test_unit_ids_change_when_normalizer_version_bumps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sb.normalize as normalize_mod

    text = "Version bump must rewrite unit identity."
    before = _ids(text)
    monkeypatch.setattr(normalize_mod, "NORMALIZER_VERSION", "v3")
    after = _ids(text)
    assert before != after
    first = normalize(_blob(text), text, _ORIGIN)
    second = normalize(_blob(text), text, _ORIGIN)
    assert [unit.text for unit in first] == [unit.text for unit in second]


def test_duplicate_chunk_text_is_dropped_when_same_run() -> None:
    sentence = "Personal vault note records the daily briefing and cited wiki pages. "
    block = sentence * 40
    text = block + "\n\n\n" + block
    units = normalize(_blob(text), text, _ORIGIN)
    texts = [unit.text for unit in units]
    assert texts != []
    assert len(texts) == len(set(texts))
    assert len(units) == 1


def test_aws_key_is_redacted_when_akia_plus_sixteen() -> None:
    text = f"aws key {_AWS_KEY} stored"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:aws]" in joined
    assert _AWS_KEY not in joined


def test_aws_key_is_kept_when_too_short() -> None:
    text = f"aws key {_AWS_SHORT} stored"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _AWS_SHORT in joined
    assert "[REDACTED:aws]" not in joined


def test_github_token_is_redacted_when_ghp_plus_thirty_six() -> None:
    text = f"token line {_GITHUB_TOKEN} done"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:github]" in joined
    assert _GITHUB_TOKEN not in joined


def test_github_token_is_kept_when_wrong_prefix() -> None:
    text = f"token line {_GITHUB_WRONG} done"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _GITHUB_WRONG in joined
    assert "[REDACTED:github]" not in joined


def test_openai_key_is_redacted_when_sk_plus_twenty() -> None:
    text = f"openai {_OPENAI_KEY} here"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:openai]" in joined
    assert _OPENAI_KEY not in joined


def test_openai_key_is_kept_when_too_short() -> None:
    text = f"openai {_OPENAI_SHORT} here"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _OPENAI_SHORT in joined
    assert "[REDACTED:openai]" not in joined


def test_pem_block_is_redacted_when_private_key() -> None:
    text = f"keyfile\n{_PEM_PRIVATE}\nend"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:pem]" in joined
    assert "BEGIN RSA PRIVATE KEY" not in joined
    assert "MIIEfakeprivatekeymaterial" not in joined


def test_pem_block_is_kept_when_public_key() -> None:
    text = f"keyfile\n{_PEM_PUBLIC}\nend"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _PEM_PUBLIC in joined
    assert "[REDACTED:pem]" not in joined


def test_password_assignment_is_redacted_when_equals() -> None:
    text = "login password=hunter2-ok"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:password]" in joined
    assert "hunter2-ok" not in joined


def test_passwd_assignment_is_redacted_when_equals() -> None:
    text = "login passwd=hunter2-ok"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:password]" in joined
    assert "hunter2-ok" not in joined


def test_password_phrase_is_kept_when_no_assignment() -> None:
    text = "the password is rotated quarterly"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "the password is rotated quarterly" in joined
    assert "[REDACTED:password]" not in joined


def test_token_assignment_is_redacted_when_colon() -> None:
    text = "auth token: s3cretvalue"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:token]" in joined
    assert "s3cretvalue" not in joined


def test_token_word_is_kept_when_no_assignment() -> None:
    text = "the token was rotated"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "the token was rotated" in joined
    assert "[REDACTED:token]" not in joined


def test_secret_assignment_is_redacted_when_equals() -> None:
    text = "cfg secret=topsecretvalue"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:secret]" in joined
    assert "topsecretvalue" not in joined


def test_secret_word_is_kept_when_no_assignment() -> None:
    text = "no secret remains here"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "no secret remains here" in joined
    assert "[REDACTED:secret]" not in joined


def test_email_is_preserved_when_present() -> None:
    text = f"contact {_EMAIL} please"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _EMAIL in joined


def test_phone_is_preserved_when_present() -> None:
    text = f"call {_PHONE} or {_PHONE_KR}"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert _PHONE in joined
    assert _PHONE_KR in joined


def test_github_token_bytes_do_not_leak_when_redacted() -> None:
    text = f"agent log used {_GITHUB_QA} yesterday"
    units = normalize(_blob(text), text, _ORIGIN)
    joined = "\n".join(unit.text for unit in units)
    assert "[REDACTED:github]" in joined
    assert _GITHUB_QA not in joined
    assert "ghp_" not in joined


def test_unit_id_is_sha256_of_hash_span_and_version() -> None:
    text = "Stable identity payload."
    blob = _blob(text)
    units = normalize(blob, text, _ORIGIN)
    assert len(units) == 1
    expected = hashlib.sha256(
        f"{blob.hash}{units[0].span}{NORMALIZER_VERSION}".encode()
    ).hexdigest()
    assert units[0].unit_id == expected


def test_empty_text_returns_no_units() -> None:
    units = normalize(_blob(""), "", _ORIGIN)
    assert units == []
