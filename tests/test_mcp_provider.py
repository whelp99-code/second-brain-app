"""Provider MCP profile smoke and typed health/error coverage."""
# pyright: reportAny=none

from __future__ import annotations

from pathlib import Path

import anyio
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult

from sb.contracts import TerminalWorkSummaryV1
from sb.mcp import build_server
from sb.vault import init_vault
from sb.write_requests import digest_json


def _call(server: MCPServer, name: str, arguments: dict[str, object]) -> CallToolResult:
    async def run() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(run)


def _summary() -> dict[str, object]:
    return TerminalWorkSummaryV1(
        memory_candidate_id="mem_mcp",
        jarvis_closeout_id="close_mcp",
        jarvis_receipt_digest=digest_json("receipt"),
        project_id="second-brain-app",
        host_scope=("jm-cloud",),
        terminal_count=1,
        started_at="2026-08-29T10:00:00Z",
        finished_at="2026-08-29T10:01:00Z",
        outcome="success",
        verified=True,
        purpose="MCP provider smoke",
    ).as_dict()


def test_provider_profile_lists_health_and_reconciliation_tools(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    server = build_server(root, provider=True)

    async def run() -> tuple[set[str], CallToolResult, CallToolResult]:
        async with Client(server, mode="legacy", cache=None) as client:
            listed = await client.list_tools()
            health = await client.call_tool("sb_provider_health", {})
            missing = await client.call_tool("sb_request_status", {"request_id": "unknown"})
            return {tool.name for tool in listed.tools}, health, missing

    names, health, missing = anyio.run(run)
    assert {"sb_write_request", "sb_request_status", "sb_reconcile_write", "sb_observe_artifact"} <= names
    assert health.is_error is False
    assert missing.is_error is False
    assert missing.structured_content == {"kind": "no_data", "reason": "request_not_found"}


def test_provider_mcp_applies_approved_request(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    _ = init_vault(root)
    request = {
        "schema": "second-brain-write-request-v1",
        "operation": "remember",
        "candidate_id": "mem_mcp",
        "closeout_id": "close_mcp",
        "receipt_digest": digest_json("receipt"),
        "purpose": "MCP provider smoke",
        "sensitivity": "normal",
        "retention": "durable",
        "expected_prior_digest": None,
        "idempotency_key": "mcp-key-1",
        "summary": _summary(),
    }
    result = _call(build_server(root, provider=True), "sb_write_request", {"request": request})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == "applied"
