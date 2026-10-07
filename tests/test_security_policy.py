"""Policy binding and rendered-prompt boundary regressions."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sb.compile import compile_pages
from sb.config import Config
from sb.security import SecurityPolicyError, llm_is_external, protect_compile_egress, protect_unit
from sb.source_access import require_current_source_access
from sb.store.ledger import Ledger
from tests.test_compile import RecordingLLM
from tests.test_source_egress_binding import ACCESS, egress_config, seed_source


def test_missing_binding_never_invents_a_trusted_revision() -> None:
    assert require_current_source_access(None, ACCESS) is None
    assert require_current_source_access(ACCESS, ACCESS) is ACCESS
    with pytest.raises(ValueError, match="^SOURCE_ACCESS_RECLASSIFICATION_REQUIRED$"):
        _ = require_current_source_access(ACCESS, replace(ACCESS, policy_revision="policy:2"))


def test_policy_revision_is_rechecked_at_generate(tmp_path: Path) -> None:
    raw = dict(egress_config(tmp_path).raw)
    config = Config(raw=raw)
    llm = RecordingLLM("unused")
    with Ledger(tmp_path) as ledger:
        unit, _ = seed_source(tmp_path, ledger, "Fact")
        gate = protect_compile_egress(llm, [unit], config, ledger,
                                      previous=None, untracked_context=False)
        # Change the trusted configuration between preparation and transport.
        raw["source_access"] = {"docs": {
            "owner": ACCESS.owner, "projects": list(ACCESS.projects), "policy_revision": "policy:2",
        }}
        with pytest.raises(ValueError, match="^SOURCE_ACCESS_RECLASSIFICATION_REQUIRED$"):
            _ = gate.generate("FORBIDDEN_PROMPT")
    assert llm.prompts == []


def test_credentials_in_title_origin_and_span_are_only_redacted_in_transport(tmp_path: Path) -> None:
    config = egress_config(tmp_path)
    llm = RecordingLLM("Compiled")
    with Ledger(tmp_path) as ledger:
        unit, source = seed_source(tmp_path, ledger, "Fact")
        source = replace(source, source_uri="api_key=FORBIDDEN_PATH.md")
        ledger.upsert_source_item(source)
        ledger.bind_source_access(source, ACCESS)
        unit = replace(unit, origin=f"docs:{source.source_uri}", span="token=FORBIDDEN_SPAN")
        pages = compile_pages([unit], ledger, llm, config)
    assert len(llm.prompts) == 1
    assert "FORBIDDEN" not in llm.prompts[0]
    assert pages[0].sources[0].origin == unit.origin
    assert pages[0].sources[0].spans == [unit.span]
    assert pages[0].title == "api_key=FORBIDDEN_PATH"


def test_explicit_external_declaration_can_only_tighten_transport() -> None:
    local = Config(raw={"llm": {"argv_template": ["/usr/bin/ollama"], "model_id": "model"}})
    assert not llm_is_external(local)
    external = replace(local, raw={"llm": {
        "argv_template": ["/usr/bin/ollama"], "external": True,
    }})
    assert llm_is_external(external)


def test_sensitive_deny_blocks_provider_tokens(tmp_path: Path) -> None:
    config = egress_config(tmp_path)
    config = replace(config, raw={**config.raw, "sources": [
        {"id": "docs", "llm_policy": "allow", "sensitive": "deny"},
    ]})
    with Ledger(tmp_path) as ledger:
        unit, _ = seed_source(tmp_path, ledger, "sk-" + "FORBIDDEN_TOKEN_" * 3)
        with pytest.raises(SecurityPolicyError, match="sensitive content denied"):
            _ = protect_unit(unit, config, ledger=ledger)
