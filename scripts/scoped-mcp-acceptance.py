"""Actual isolated JARVIS issuer -> separate Python scoped stdio MCP."""
import base64
import json
import os
import runpy
import sys
from pathlib import Path

import anyio
from mcp import StdioServerParameters
from mcp.client import Client

setup = runpy.run_path(str(Path(__file__).with_name("access-claim-acceptance.py")))
work, page = setup["work"], setup["page"]
config = work / "config.toml"
key = base64.urlsafe_b64encode(setup["key"].public_key().public_bytes_raw()).rstrip(b"=").decode()
config.write_text('jarvis_public_keys = { "key:test" = "' + key + '" }\n' + config.read_text() + '''
[mcp_scoped_read]
principal = "principal:owner"
agent = "agent:test"
session = "session:test"
policy_revision = "policy:1"
''')
bootstrap = '''from datetime import datetime,UTC
import sb.mcp as m
class Clock(datetime):
 @classmethod
 def now(cls,tz=None): return datetime(2026,9,9,tzinfo=UTC)
m.datetime=Clock
m.main()
'''
async def run():
    outputs = []
    for _ in range(2):
        params = StdioServerParameters(command=sys.executable, args=["-c", bootstrap],
            cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp"})
        async with Client(params, mode="legacy", cache=None, read_timeout_seconds=60) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
            assert names == ["sb_read_page"], names
            args = {"id": page.page_id, "read_fence": setup["fence_value"], "access_claim": setup["claim"]}
            result = await client.call_tool("sb_read_page", args)
            assert not result.is_error, result
            assert result.structured_content["profile"] == "scoped-record-read-v1"
            assert len(result.structured_content["records"]) == 2
            for invalid in [{**args, "id": "wiki/other"}, {"id": page.page_id},
                {**args, "access_claim": {**setup["claim"], "projects": ["project:other"]}}]:
                denied = await client.call_tool("sb_read_page", invalid)
                assert denied.is_error, denied
                assert "Alpha fixture" not in str(denied)
            outputs.append(result.structured_content)
    assert outputs[0] == outputs[1]
    return {"work": str(work), "tools": ["sb_read_page"], "records": 2,
        "wrong_request_missing_claim_tampering_denied": True, "restart_equal": True,
        "production_issuer": len(sys.argv) > 1,
        "scope": "actual stdio and JARVIS issuer with fixture authority/scope/clock; record read only, not full operating ACL"}
report = anyio.run(run)
output = work / "scoped-mcp-result.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(output)
print(json.dumps(report))
