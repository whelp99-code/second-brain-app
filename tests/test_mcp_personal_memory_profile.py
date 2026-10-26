"""personal-memory-v1 is opt-in, sb_recall-only, and digest-frozen."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.server.mcpserver import MCPServer

from sb.config import load_config
from sb.effect_values import JsonInput, JsonObject, JsonValue
from sb.life_config import policies
from sb.mcp import LEGACY_TOOLS, build_server
from sb.mcp_contract import (
    PERSONAL_MEMORY_PROFILE,
    PERSONAL_MEMORY_UNSUPPORTED,
    canonical_bytes,
    personal_memory_contract,
    recall_response_schema,
    require_supported_profile,
)
from sb.personal_observation import parse_scan_receipt
from sb.source_coverage import record_scan_receipt
from sb.store.ledger import Ledger
from sb.vault import init_vault
from tests.mcp_test_support import json_content
from tests.test_life_contracts import payload
from tests.test_mcp_contract import (
    test_contract_freezes_stable_error_codes_and_classes,
    test_contract_has_exact_tools_and_version,
    test_export_is_canonical_deterministic_and_matches_sidecar,
)
from tests.test_mcp_profile_compatibility import (
    test_absent_contract_profile_exposes_exact_legacy_tool_set,
    test_unknown_contract_profile_fails_before_server_composition,
)

BASE = "518c7b3dfe4182c232a18f7994aca9b59720488e"
NOW = datetime(2026, 9, 26, 3, 0, tzinfo=UTC)
FROZEN = (
    "contracts/second-brain-mcp-v1.json",
    "contracts/second-brain-mcp-v3.json",
    "contracts/second-brain-mcp-v4.json",
    "contracts/second-brain-mcp-v5.json",
    "contracts/second-brain-scoped-read-v1.json",
    "contracts/second-brain-scoped-read-v2.json",
    "contracts/second-brain-scoped-read-v3.json",
    "contracts/second-brain-scoped-read-v4.json",
    "contracts/second-brain-scoped-read-v5.json",
    "contracts/second-brain-scoped-status-v1.json",
    "contracts/second-brain-scoped-write-v1.json",
    "contracts/memory-integration-ids-v1.json",
    "contracts/cancellation-result-v1.json",
)
SCHEMA = Draft202012Validator(recall_response_schema())


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, recall: bool) -> Path:
    root = init_vault(tmp_path / "vault").root
    text = "\n".join(
        (
            f'vault_root = "{root}"',
            f'request_root = "{tmp_path / "requests"}"',
            f'state_root = "{tmp_path / "state"}"',
            f'share_root = "{tmp_path / "share"}"',
            'provider_instance_id = "provider:fixture"',
            "",
            "[life]",
            "life_events = true",
            f"contextual_recall = {str(recall).lower()}",
            "",
            "[life.sources.test-notes]",
            "enabled = true",
            "",
            "[source_access.test-notes]",
            'owner = "principal:owner"',
            "projects = []",
            'policy_revision = "test-v1"',
            "",
        )
    )
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("SB_CONFIG", str(path))
    return root


def _exhaust(root: Path) -> None:
    receipt = parse_scan_receipt(
        {
            "scan_id": "scan-1",
            "source_id": "test-notes",
            "account_id": "synthetic-account",
            "started_at": "2026-09-23T00:00:00.000Z",
            "finished_at": "2026-09-23T00:01:00.000Z",
            "state": "ok",
            "checkpoint_before": "cursor-1",
            "checkpoint_after": "cursor-1",
            "scanned": 0,
            "accepted": 0,
            "unchanged": 0,
            "filtered": 0,
            "quarantined": 0,
            "deferred": 0,
            "retryable_errors": 0,
            "permanent_errors": 0,
            "coverage_start": None,
            "coverage_end": None,
            "next_scan_at": None,
            "remaining_known": 0,
            "exhausted": True,
            "budget": 100,
            "upstream_end_evidence": "scan-proof:continuation-end",
        }
    )
    with Ledger(root) as ledger:
        _ = ledger.life_store()
        record_scan_receipt(ledger, receipt, cursor_updated_at="2026-09-23T00:01:00.000Z")


def _accept(root: Path, **changes: JsonValue) -> None:
    policy = policies(load_config())["test-notes"]
    with Ledger(root) as ledger:
        ledger.life_store().accept(payload(**changes), policy, key=str(changes["source_item_id"]), now=NOW)


async def _call(server: MCPServer, arguments: Mapping[str, JsonInput]) -> JsonObject:
    async with Client(server, mode="legacy", cache=None) as client:
        result = await client.call_tool("sb_recall", dict(arguments))
    assert result.is_error is False, result
    body = json_content(result)
    SCHEMA.validate(body)
    return body


def test_profile_env_gate_defaults_off_and_old_profiles_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _config(tmp_path, monkeypatch, recall=True)
    monkeypatch.delenv("SB_MCP_CONTRACT_PROFILE", raising=False)

    async def names() -> tuple[str, ...]:
        async with Client(build_server(root), mode="legacy", cache=None) as client:
            listed = await client.list_tools()
        return tuple(sorted(tool.name for tool in listed.tools))

    listed = anyio.run(names)
    assert "sb_recall" not in listed
    assert listed == tuple(sorted({*LEGACY_TOOLS, "sb_generation_status", "sb_request_status", "sb_resolve_memory_target"}))
    for rel in FROZEN:
        committed = subprocess.check_output(["git", "show", f"{BASE}:{rel}"])
        assert Path(rel).read_bytes() == committed
        sidecar = Path(rel + ".sha256")
        if sidecar.is_file():
            committed_side = subprocess.check_output(["git", "show", f"{BASE}:{rel}.sha256"])
            assert sidecar.read_bytes() == committed_side


def test_sb_recall_returns_k5_states_answered_ambiguous_not_found_coverage_incomplete_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _config(tmp_path, monkeypatch, recall=True)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", PERSONAL_MEMORY_PROFILE)
    server = build_server()

    unavailable = anyio.run(_call, server, {"query": "AlphaEngineer", "namespace": "company"})
    assert unavailable["state"] == "unavailable"
    assert unavailable["answer"] is None

    with Ledger(root):
        pass
    incomplete = anyio.run(_call, server, {"query": "AlphaEngineer"})
    assert incomplete["state"] == "coverage_incomplete"

    _exhaust(root)
    missing = anyio.run(_call, server, {"query": "MissingToken"})
    assert missing["state"] == "not_found"
    assert missing["evidence_refs"] == []

    _accept(root, source_item_id="item-1", title="AlphaEngineer note", body="AlphaEngineer builds tools")
    answered = anyio.run(_call, server, {"query": "AlphaEngineer"})
    assert answered["state"] == "answered"
    assert answered["answer"] == "AlphaEngineer builds tools"
    answered_refs = answered["evidence_refs"]
    assert isinstance(answered_refs, list)
    assert len(answered_refs) == 1
    assert answered["uncertainty_reasons"] == []

    _accept(root, source_item_id="item-2", title="AlphaEngineer other", body="AlphaEngineer also appears")
    ambiguous = anyio.run(_call, server, {"query": "AlphaEngineer"})
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["answer"] is None
    ambiguous_refs = ambiguous["evidence_refs"]
    assert isinstance(ambiguous_refs, list)
    assert len(ambiguous_refs) == 2
    uncertainty = ambiguous["uncertainty_reasons"]
    assert isinstance(uncertainty, list)
    assert "MULTIPLE_MATCHES" in uncertainty


def test_profile_sidecar_digest_frozen() -> None:
    documents = {
        "contracts/recall-response-v1.json": recall_response_schema(),
        "contracts/second-brain-personal-memory-v1.json": personal_memory_contract(),
    }
    for rel, document in documents.items():
        payload = Path(rel).read_bytes()
        assert payload == canonical_bytes(document)
        digest = hashlib.sha256(payload).hexdigest()
        assert Path(rel + ".sha256").read_text(encoding="ascii") == f"{digest}\n"
    profile = json.loads(Path("contracts/second-brain-personal-memory-v1.json").read_text())
    assert profile["tools"] == ["sb_recall"]
    assert profile["deferred_tools"] == [
        "sb_obligation_event",
        "sb_obligation_status",
        "sb_recommendations",
    ]
    assert profile["recall_response_sha256"] == hashlib.sha256(
        Path("contracts/recall-response-v1.json").read_bytes()
    ).hexdigest()


def test_unsupported_server_returns_explicit_error_for_new_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = _config(tmp_path, monkeypatch, recall=False)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", PERSONAL_MEMORY_PROFILE)
    with pytest.raises(RuntimeError, match=f"^{PERSONAL_MEMORY_UNSUPPORTED}$"):
        _ = build_server()
    with pytest.raises(RuntimeError, match=f"^{PERSONAL_MEMORY_UNSUPPORTED}$"):
        require_supported_profile(("task30-schema3", "scoped-record-read-v5"), PERSONAL_MEMORY_PROFILE)
    require_supported_profile((PERSONAL_MEMORY_PROFILE,), PERSONAL_MEMORY_PROFILE)


def test_existing_task30_and_scoped_contract_tests_still_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_contract_has_exact_tools_and_version()
    test_contract_freezes_stable_error_codes_and_classes()
    test_export_is_canonical_deterministic_and_matches_sidecar(tmp_path / "export")
    test_absent_contract_profile_exposes_exact_legacy_tool_set(tmp_path / "absent", monkeypatch)
    monkeypatch.delenv("SB_MCP_CONTRACT_PROFILE", raising=False)
    test_unknown_contract_profile_fails_before_server_composition(tmp_path / "unknown", monkeypatch)
    for rel in FROZEN:
        if "scoped" not in rel and "mcp-v1" not in rel:
            continue
        digest = hashlib.sha256(Path(rel).read_bytes()).hexdigest()
        assert Path(rel + ".sha256").read_text(encoding="ascii") == f"{digest}\n"
