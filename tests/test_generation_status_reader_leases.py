"""sb_generation_status must survive leftover reader leases when the writer is idle."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import anyio
from mcp.client import Client
from pytest import MonkeyPatch

from sb.generation_locks import generation_writer
from sb.generation_runtime_models import generation_runtime_paths
from sb.mcp import build_server
from sb.request_store import RequestStore
from tests.mcp_test_support import json_content
from tests.test_web_lifecycle import ready


def test_generation_status_returns_when_reader_leases_exist_and_writer_lock_is_free(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config, _root = ready(tmp_path)
    paths = generation_runtime_paths(config)
    with generation_writer(paths.state / "generation.lock", blocking=False):
        pass
    journal = RequestStore(paths.requests)
    try:
        journal.register_reader(
            "desktop-read:dead",
            "sbgen:v1:" + "ab" * 32,
            2**31 - 1,
            datetime(2026, 9, 28, tzinfo=UTC),
        )
        assert journal.db.row_factory is sqlite3.Row
        assert journal.readers("sbgen:v1:" + "ab" * 32) == (("desktop-read:dead", 2**31 - 1),)
    finally:
        journal.close()
    monkeypatch.setattr("sb.mcp.load_config", lambda: config)
    server = build_server(contract_schema=4)

    async def probe() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_generation_status", {"read_fence": None})
            assert result.is_error is False, result
            status = json_content(result)
            assert isinstance(status.get("generation_id"), str)
            assert status.get("journal_health") == "healthy"

    anyio.run(probe)
