from __future__ import annotations

import base64
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Literal, override

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mcp.client import Client

import sb.mcp as mcp_module
from sb.effect_values import JsonObject
from sb.mcp import build_server
from sb.mcp_cancellation_contract import build_cancellation_contract
from sb.mcp_contract import build_contract, canonical_bytes
from sb.mcp_remember_contract import build_remember_contract
from sb.request_executor import RequestExecutor
from tests.mcp_test_support import json_content
from tests.test_cancellation_result import issue
from tests.test_cancellation_status import OBSERVED, arguments
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import prepare


class StatusClock(datetime):
    @classmethod
    @override
    def now(cls, tz: tzinfo | None = None) -> datetime:
        return OBSERVED if tz is None else OBSERVED.astimezone(tz)


def configure(executor: RequestExecutor, path: Path, *, revoked: bool = False, malformed: bool = False) -> None:
    config = executor.config
    def public(key: Ed25519PublicKey) -> str:
        return base64.urlsafe_b64encode(key.public_bytes_raw()).rstrip(b"=").decode()
    _ = path.write_text("\n".join([
        f'vault_root = "{config.share_root / "vault"}"',
        f'request_root = "{config.request_root}"', f'state_root = "{config.state_root}"',
        f'share_root = "{config.share_root}"', f'export_root = "{config.export_root}"',
        f'backup_root = "{config.backup_root}"', 'provider_instance_id = "provider:fixture"',
        f'provider_release_sha = "{config.provider_release_sha}"',
        'revoked_provider_result_key_ids = ["provider:key"]' if revoked else 'revoked_provider_result_key_ids = []',
        '[jarvis_public_keys]', f'reader = "{public(CURRENT.public_key())}"',
        '[provider_result_public_keys]',
        f'"provider:key" = "{"bad" if malformed else public(config.provider_signing_key.public_key())}"',
    ]) + "\n")


@pytest.mark.parametrize("revoked,malformed", [(False, False), (True, False), (False, True)])
def test_status_profile_reads_exact_result_without_private_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revoked: bool, malformed: bool):
    executor, identity, _ = prepare(tmp_path)
    try:
        expected = issue(executor, identity)
        args = arguments(executor, identity)
        path = tmp_path / "config.toml"
        configure(executor, path, revoked=revoked, malformed=malformed)
        monkeypatch.setenv("SB_CONFIG", str(path))
        monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "cancellation-schema6")
        monkeypatch.setattr(mcp_module, "datetime", StatusClock)
        before = list(executor.store.db.iterdump())

        async def exercise() -> None:
            async with Client(build_server(), mode="legacy", cache=None) as client:
                listed = await client.list_tools()
                assert len(listed.tools) == 10
                write = next(tool for tool in listed.tools if tool.name == "sb_write_request")
                assert "MemoryRememberRequestV3Model" in str(write.input_schema)
                call: JsonObject = {"intent_id": args["intent_id"], "intent_digest": args["intent_digest"], "read_fence": args["read_fence"]}
                result = await client.call_tool("sb_cancellation_status", call)
                assert result.is_error is (revoked or malformed)
                if revoked or malformed:
                    assert "MEMORY_CANCELLATION_RESULT_INVALID" in str(result.content)
                else:
                    assert json_content(result)["result"] == expected
                    replay = await client.call_tool("sb_cancellation_status", call)
                    assert json_content(replay) == json_content(result)
                denied = await client.call_tool("sb_cancellation_status", {**call, "read_fence": None})
                assert denied.is_error and "TOMBSTONE_FENCE_REQUIRED" in str(denied.content)
                missing = await client.call_tool("sb_cancellation_status", {**call,
                    "intent_id": "memcancel:intent:v1:" + "0" * 64, "intent_digest": "sha256:" + "0" * 64})
                assert not missing.is_error and json_content(missing)["state"] == "not_found"
        anyio.run(exercise)
        assert list(executor.store.db.iterdump()) == before
        assert "provider_private_key" not in path.read_text()
    finally:
        executor.close()


@pytest.mark.parametrize("schema", [3, 4, 5])
def test_old_profiles_do_not_expose_cancellation_status(tmp_path: Path, schema: Literal[3, 4, 5, 6]):
    async def exercise() -> None:
        async with Client(build_server(tmp_path / "vault", contract_schema=schema), mode="legacy", cache=None) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert len(names) == 9 and "sb_cancellation_status" not in names
    anyio.run(exercise)


def test_all_contract_artifacts_remain_reproducible():
    root = Path(__file__).resolve().parent.parent / "contracts"
    for name, builder in [("v1", build_contract), ("v3", build_remember_contract), ("v4", build_cancellation_contract)]:
        assert canonical_bytes(builder()) == (root / f"second-brain-mcp-{name}.json").read_bytes()


def test_schema6_generation_status_advertises_the_pinned_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    executor, identity, _ = prepare(tmp_path)
    try:
        _ = issue(executor, identity)
        args = arguments(executor, identity)
        path = tmp_path / "config.toml"
        configure(executor, path)
        monkeypatch.setenv("SB_CONFIG", str(path))
        monkeypatch.setenv("SB_MCP_CONTRACT_PROFILE", "cancellation-schema6")
        monkeypatch.setattr(mcp_module, "datetime", StatusClock)

        async def exercise() -> None:
            async with Client(build_server(), mode="legacy", cache=None) as client:
                result = await client.call_tool("sb_generation_status", {"read_fence": args["read_fence"]})
                assert not result.is_error
                value = json_content(result)
                assert value["contract_schema_version"] == 6
                assert value["contract_digest"] == "8be1ca195f60cb73f05c989d3d5f3e62053020988ccd8bb028cd4d8b442063b4"
                features = value["features"]
                assert isinstance(features, list)
                assert "memory_cancellation_status_v1" in features
                assert "memory_remember_v3" in features
        anyio.run(exercise)
    finally:
        executor.close()
