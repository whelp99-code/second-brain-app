"""Opt-in MCP schema5 while old profiles continue rejecting new write bodies."""

import os
from pathlib import Path

import anyio
import pytest
from mcp.client import Client

import sb.mcp as mcp_module
from sb.mcp import build_server
from sb.mcp_contract import build_contract, canonical_bytes
from sb.mcp_remember_contract import build_remember_contract, remember_fixture_request
from sb.vault import init_vault
from tests.mcp_test_support import json_content
from tests.task30_clock import FrozenTask30DateTime
from tests.test_mcp_profile_compatibility import configured_runtime


@pytest.mark.parametrize("profile,accepted", [("task32-schema4", False), ("remember-schema5", True), ("cancellation-schema6", True)])
def test_only_explicit_new_profile_accepts_multiline_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, accepted: bool,
) -> None:
    configured_runtime(tmp_path, monkeypatch)
    # Strict profiles use the managed runtime path, unlike the legacy fixture.
    config_path = Path(os.environ["SB_CONFIG"])
    _ = init_vault(tmp_path / "share" / "vault")
    _ = config_path.write_text(config_path.read_text().replace(
        f'vault_root = "{tmp_path / "vault"}"', f'vault_root = "{tmp_path / "share" / "vault"}"'
    ))
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", profile)
    monkeypatch.setattr(mcp_module, "datetime", FrozenTask30DateTime)
    request = remember_fixture_request()

    async def exercise() -> None:
        async with Client(build_server(), mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            write = next(tool for tool in listed.tools if tool.name == "sb_write_request")
            assert ("MemoryRememberRequestV3Model" in str(write.input_schema)) is accepted
            result = await client.call_tool("sb_write_request", {"request": request})
            assert result.is_error is not accepted
            if accepted:
                value = json_content(result)
                assert value["schema_version"] == 3
                assert value["request_id"] == request["request_id"] and value["replayed"] is False
                replay = await client.call_tool("sb_write_request", {"request": request})
                observed = json_content(replay)
                assert observed == {**value, "replayed": True}

    anyio.run(exercise)
    pending = tmp_path / "requests" / "pending"
    files = tuple(pending.glob("*.json")) if pending.exists() else ()
    assert len(files) == int(accepted)


def test_old_and_new_contract_artifacts_are_independently_reproducible() -> None:
    contracts = Path(__file__).resolve().parent.parent / "contracts"
    assert canonical_bytes(build_contract()) == (contracts / "second-brain-mcp-v1.json").read_bytes()
    assert canonical_bytes(build_remember_contract()) == (contracts / "second-brain-mcp-v3.json").read_bytes()
