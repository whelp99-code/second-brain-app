"""The real Task29 consumer freezes four search-result fields, not later metadata."""

from pathlib import Path

import anyio
from mcp.client import Client
from pydantic import BaseModel

from sb.mcp import build_server
from sb.vault import init_vault


class Definition(BaseModel):
    required: list[str]


class SearchSchema(BaseModel):
    definitions: dict[str, Definition]


def test_legacy_search_advertises_only_task29_result_fields(tmp_path: Path) -> None:
    # Given: a provider launched without a schema-3/4 selector.
    root = init_vault(tmp_path / "vault").root
    async def required_fields() -> list[str]:
        async with Client(build_server(root, task30=False), mode="legacy", cache=None) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools.tools if tool.name == "sb_search")
            assert tool.output_schema is not None
            schema = SearchSchema.model_validate({"definitions": tool.output_schema["$defs"]})
            return schema.definitions["SearchHitDict"].required
    # When: the old client's frozen machine schema is checked.
    required = anyio.run(required_fields)
    # Then: later knowledge metadata must not upgrade the legacy schema silently.
    assert required == ["page_id", "section", "snippet", "score"]
