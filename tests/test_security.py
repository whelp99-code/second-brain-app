"""Source-scoped LLM egress and prompt-time masking policy."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest

from sb.compile import compile_pages
from sb.config import Config, TomlValue
from sb.conflict import check
from sb.contracts import BriefingInputs, Unit
from sb.security import (
    SecurityPolicyError,
    llm_is_external,
    mask_sensitive,
    protect_briefing_inputs,
    protect_unit,
    source_policy_snapshot,
)
from sb.store.ledger import Ledger


class RecordingLLM:
    response: str
    prompts: list[str]

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts = []

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        del system, json_mode, timeout
        self.prompts.append(prompt)
        return self.response


def _unit(text: str, source_id: str = "private", unit_id: str = "unit-a") -> Unit:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Unit(unit_id, digest, "0-100", text, f"{source_id}:note.md")


def _config(
    root: Path,
    *,
    external: bool,
    llm_policy: str | None = "allow",
    sensitive: str = "mask",
) -> Config:
    source: dict[str, object] = {
        "id": "private",
        "adapter": "markdown-vault",
        "root": str(root / "source"),
        "sensitive": sensitive,
    }
    if llm_policy is not None:
        source["llm_policy"] = llm_policy
    return Config(
        raw=cast(
            dict[str, TomlValue],
            {
                "vault_root": str(root),
                "caps": {
                    "max_llm_calls_compile": 10,
                    "max_llm_calls_conflict": 10,
                    "max_llm_calls_briefing": 10,
                },
                "llm": {
                    "argv_template": ["claude", "-p", "{prompt}"],
                    "prompt_version": "v1",
                    "model_id": "remote-model" if external else "fake",
                    "external": external,
                },
                "sources": [source],
            },
        )
    )


def test_allowed_external_compile_masks_prompt_but_preserves_source_unit(tmp_path: Path) -> None:
    secret = "owner@example.com api_key=abcdefghijklmnop"
    unit = _unit(f"계약 담당자 {secret}")
    config = _config(tmp_path, external=True)
    llm = RecordingLLM(f"계약 사실.[^{unit.content_hash[:8]}]")

    with Ledger(tmp_path) as ledger:
        pages = compile_pages([unit], ledger, llm, config)

    assert pages
    assert llm.prompts
    prompt = llm.prompts[0]
    assert "owner@example.com" not in prompt
    assert "abcdefghijklmnop" not in prompt
    assert "[REDACTED_EMAIL]" in prompt
    assert "[REDACTED_SECRET]" in prompt
    assert secret in unit.text


def test_external_source_without_explicit_permission_is_denied_before_llm(tmp_path: Path) -> None:
    config = _config(tmp_path, external=True, llm_policy=None)
    unit = _unit("외부 전송 금지 자료")
    llm = RecordingLLM("unused")

    with Ledger(tmp_path) as ledger:
        pages = compile_pages([unit], ledger, llm, config)

    assert llm.prompts == []
    assert pages
    assert "외부 전송 금지 자료" in pages[0].body_md
    assert pages[0].model_id == "local-deny"


def test_local_only_source_rejects_external_model_and_allows_local_model(tmp_path: Path) -> None:
    unit = _unit("로컬 모델만 허용")
    external = _config(tmp_path, external=True, llm_policy="local-only")
    with pytest.raises(SecurityPolicyError, match="local model"):
        _ = protect_unit(unit, external)

    local = _config(tmp_path, external=False, llm_policy="local-only")
    assert protect_unit(unit, local).text == unit.text
    assert not llm_is_external(local)


def test_sensitive_deny_rejects_secret_while_allow_preserves_prompt_copy(tmp_path: Path) -> None:
    unit = _unit("password=hunter2")
    denied = _config(tmp_path, external=False, sensitive="deny")
    with pytest.raises(SecurityPolicyError, match="sensitive content denied"):
        _ = protect_unit(unit, denied)

    allowed = _config(tmp_path, external=False, sensitive="allow")
    assert protect_unit(unit, allowed).text == "password=hunter2"


def test_conflict_llm_receives_masked_units(tmp_path: Path) -> None:
    left = _unit("보존 기간 30일 owner@example.com", unit_id="left")
    right = _unit("보존 기간 90일 api_key=abcdefghijklmnop", unit_id="right")
    config = _config(tmp_path, external=True)
    verdict = (
        '{"relation":"contradicts","confidence":0.99,'
        '"rationale":"기간 상충","cites":["left","right"]}'
    )
    llm = RecordingLLM(verdict)

    with Ledger(tmp_path) as ledger:
        findings = check([left, right], [], ledger, llm, config, finalize=False)

    assert findings
    assert llm.prompts
    prompt = llm.prompts[0]
    assert "owner@example.com" not in prompt
    assert "abcdefghijklmnop" not in prompt
    assert "REDACTED" in prompt


def test_briefing_inputs_enforce_source_policy_and_mask_sensitive_lines(tmp_path: Path) -> None:
    config = _config(tmp_path, external=True)
    digest = "a" * 64
    line = (
        f"origin=private:note.md hash={digest} [^{digest[:8]}] "
        "text=owner@example.com access_token=abcdefghijklmnop"
    )
    protected = protect_briefing_inputs(
        BriefingInputs((line,), (), (), (), None, "ok"),
        config,
    )
    assert "owner@example.com" not in protected.yesterday_items[0]
    assert "abcdefghijklmnop" not in protected.yesterday_items[0]
    assert "REDACTED" in protected.yesterday_items[0]


def test_private_keys_bearer_tokens_and_emails_are_masked() -> None:
    raw = (
        "Bearer abcdefghijklmnop\n"
        "owner@example.com\n"
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    )
    protected = mask_sensitive(raw)
    assert "abcdefghijklmnop" not in protected
    assert "owner@example.com" not in protected
    assert "BEGIN PRIVATE KEY" not in protected
    assert "[REDACTED_TOKEN]" in protected
    assert "[REDACTED_EMAIL]" in protected
    assert "[REDACTED_PRIVATE_KEY]" in protected


def test_source_policy_snapshot_contains_no_source_content(tmp_path: Path) -> None:
    config = _config(tmp_path, external=True)
    rows = source_policy_snapshot(config)
    assert len(rows) == 1
    assert rows[0]["id"] == "private"
    assert rows[0]["llm_policy"] == "allow"
    assert rows[0]["sensitive"] == "mask"
    assert "content" not in rows[0]
