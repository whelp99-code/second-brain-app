"""Actual isolated JARVIS issuer -> separate Python scoped stdio MCP."""
import base64
import json
import os
import runpy
import subprocess
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
search_bundle = None
if len(sys.argv) > 1:
    issued = subprocess.run(["node", str(Path(__file__).with_name("access-claim-production-sign.mjs")), sys.argv[1]],
        input=json.dumps({**setup["body"], "request": {"method": "sb_search", "arguments": {"query": "Cited", "limit": 2}}}),
        capture_output=True, text=True, check=True, timeout=60)
    search_bundle = json.loads(issued.stdout)
async def run():
    outputs = []
    for _ in range(2):
        params = StdioServerParameters(command=sys.executable, args=["-c", bootstrap],
            cwd=str(Path(__file__).resolve().parents[1]), env={**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp"})
        async with Client(params, mode="legacy", cache=None, read_timeout_seconds=60) as client:
            names = [tool.name for tool in (await client.list_tools()).tools]
            assert names == ["sb_read_page", "sb_search"], names
            args = {"id": page.page_id, "read_fence": setup["fence_value"], "access_claim": setup["claim"]}
            result = await client.call_tool("sb_read_page", args)
            assert not result.is_error, result
            assert result.structured_content["profile"] == "scoped-record-read-v1"
            assert len(result.structured_content["records"]) == 2
            if len(sys.argv) > 1:
                found = await client.call_tool("sb_search", {"query": "Cited", "limit": 2, **search_bundle})
                assert not found.is_error, found
                assert len(found.structured_content["results"]) == 2
                wrong = await client.call_tool("sb_search", {"query": "Cited", "limit": 1, **search_bundle})
                assert wrong.is_error
            for invalid in [{**args, "id": "wiki/other"}, {"id": page.page_id},
                {**args, "access_claim": {**setup["claim"], "projects": ["project:other"]}}]:
                denied = await client.call_tool("sb_read_page", invalid)
                assert denied.is_error, denied
                assert "Alpha fixture" not in str(denied)
            original = config.read_text()
            for replacement in ['revoked_jarvis_signing_key_ids = ["key:test"]\n' + original,
                original.replace('policy_revision = "policy:1"', 'policy_revision = "policy:changed"'),
                "not valid toml [", None]:
                if replacement is None:
                    config.unlink()
                else:
                    config.write_text(replacement)
                denied = await client.call_tool("sb_read_page", args)
                assert denied.is_error, denied
                assert "Alpha fixture" not in str(denied)
            config.write_text(original)
            restored = await client.call_tool("sb_read_page", args)
            assert not restored.is_error
            assert restored.structured_content == result.structured_content
            outputs.append(result.structured_content)
    assert outputs[0] == outputs[1]
    return {"work": str(work), "tools": ["sb_read_page", "sb_search"], "records": 2,
        "wrong_request_missing_claim_tampering_denied": True, "restart_equal": True,
        "production_issuer": len(sys.argv) > 1,
        "live_revocation_policy_change_invalid_missing_config_denied": True,
        "restored_policy_resumes_same_connection": True,
        "scope": "actual stdio and JARVIS issuer with fixture authority/scope/clock; record read only, not full operating ACL"}
report = anyio.run(run)
output = work / "scoped-mcp-result.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(output)
print(json.dumps(report))
