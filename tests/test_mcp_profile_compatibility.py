from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import StdioServerParameters
from mcp.client import Client
from pytest import MonkeyPatch

from sb.mcp import LEGACY_TOOLS, build_server
from sb.vault import init_vault


def _configured_runtime(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()
    vault = tmp_path / "vault"
    _ = init_vault(vault)
    config = tmp_path / "config.toml"
    _ = config.write_text(
        "\n".join(
            (
                f'vault_root = "{vault}"',
                f'request_root = "{tmp_path / "requests"}"',
                f'state_root = "{tmp_path / "state"}"',
                f'share_root = "{tmp_path / "share"}"',
                'provider_instance_id = "provider:fixture"',
                'jarvis_signing_key_id = "jarvis:fixture"',
                f'jarvis_public_key = "{public_key}"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SB_CONFIG", str(config))


def test_absent_contract_profile_exposes_exact_legacy_tool_set(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a fully Task-30-configured provider launched by an old client.
    _configured_runtime(tmp_path, monkeypatch)
    monkeypatch.delenv("SB_MCP_CONTRACT_PROFILE", raising=False)

    async def listed_names() -> tuple[str, ...]:
        async with Client(build_server(), mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            return tuple(sorted(tool.name for tool in listed.tools))

    # When: the old client performs tools/list without the new selector.
    names = anyio.run(listed_names)

    # Then: configuration cannot silently upgrade its six-tool schema-2 surface.
    assert names == LEGACY_TOOLS


def test_real_stdio_process_selects_legacy_and_strict_profiles(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: one configured provider release launched twice through real stdio children.
    _configured_runtime(tmp_path, monkeypatch)
    config_path = os.environ["SB_CONFIG"]

    async def listed(profile: str | None) -> tuple[tuple[str, ...], str]:
        env = {"SB_CONFIG": config_path}
        if profile is not None:
            env["SB_MCP_CONTRACT_PROFILE"] = profile
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sb.mcp"],
            env=env,
        )
        async with Client(
            parameters,
            mode="legacy",
            cache=None,
            read_timeout_seconds=20,
        ) as client:
            tools = await client.list_tools()
            write = next(tool for tool in tools.tools if tool.name == "sb_write_request")
            return (
                tuple(sorted(tool.name for tool in tools.tools)),
                json.dumps(write.input_schema, sort_keys=True),
            )

    # When: an old client omits the selector and a new client sends the exact selector.
    legacy_names, legacy_write = anyio.run(listed, None)
    strict_names, strict_write = anyio.run(listed, "task30-schema3")

    # Then: schema-2 remains six/V1-only while schema-3 remains strict nine/V2-capable.
    assert legacy_names == LEGACY_TOOLS
    assert "MemoryEffectWriteRequestV2" not in legacy_write
    assert len(strict_names) == 9
    assert "MemoryEffectWriteRequestV2" in strict_write


def test_unknown_contract_profile_fails_before_server_composition(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: a configured provider with an unrecognized selector.
    _configured_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "task30-schema4")

    # When / Then: server composition fails closed before MCP initialization.
    with pytest.raises(RuntimeError, match="SECOND_BRAIN_CONTRACT_PROFILE_INVALID"):
        _ = build_server()
