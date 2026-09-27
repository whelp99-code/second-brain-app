"""Frozen schema-4 readiness can bootstrap after a local-owner tombstone."""
from pathlib import Path

import anyio
from mcp.client import Client
from pytest import MonkeyPatch

from sb.contract_digest import TASK32_CONTRACT_DIGEST
from sb.mcp import K5_TOOLS, build_server
from sb.owner_effects import apply_page_effect, page_receipt
from tests.mcp_test_support import json_content
from tests.test_web_lifecycle import PAGE, ready


def test_schema4_status_bootstraps_after_owner_effect_without_unfencing_content(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    config, root = ready(tmp_path)
    page = page_receipt(root, PAGE)
    rows = page['records']
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    record_id = rows[0]['record_id']
    assert isinstance(record_id, str)
    _ = apply_page_effect(config, PAGE, 'correct', page['receipt'],
                          record_id=record_id, content='replacement after owner effect')
    monkeypatch.setattr('sb.mcp.load_config', lambda: config)
    server = build_server(contract_schema=4)

    async def probe() -> None:
        async with Client(server, mode='legacy', cache=None) as client:
            listed = await client.list_tools()
            assert tuple(sorted(tool.name for tool in listed.tools)) == K5_TOOLS
            result = await client.call_tool('sb_generation_status', {'read_fence': None})
            assert not result.is_error, result
            status = json_content(result)
            assert status['contract_schema_version'] == 4
            assert status['contract_digest'] == TASK32_CONTRACT_DIGEST
            assert status['tombstone_sequence'] == 1
            assert status['pointer_health'] == status['journal_health'] == 'healthy'
            assert not {'body', 'records', 'results', 'proof'} & status.keys()
            # A supplied invalid fence is not downgraded to a bootstrap call.
            invalid = await client.call_tool('sb_generation_status', {'read_fence': {}})
            assert invalid.is_error
            for name, args in (
                ('sb_search', {'query': 'replacement', 'read_fence': None}),
                ('sb_read_page', {'id': PAGE, 'read_fence': None}),
                ('sb_request_status', {'request_id': 'unknown', 'read_fence': None}),
            ):
                denied = await client.call_tool(name, args)
                assert denied.is_error and 'TOMBSTONE_FENCE_REQUIRED' in denied.model_dump_json()
    anyio.run(probe)
