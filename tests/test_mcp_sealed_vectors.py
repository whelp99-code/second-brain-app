"""MCP schemas 4/5 bind semantic results to the exact pinned cited record."""
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import anyio
import pytest
from mcp.client import Client
from pydantic import TypeAdapter

from sb import embeddings
from sb.config import Config, load_config
from sb.contracts import PageSpec, SourceCite
from sb.effect_values import JsonObject, JsonValue, is_json_object
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.generations import Generation
from sb.mcp import build_server
from sb.pipeline import audit_citations
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault
from tests.test_generation_vectors import NOW
from tests.test_sealed_vectors import SemanticEncoder

pytestmark = pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional")


class _NoPreviousPage:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def runtime_fixture(base: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, GenerationMutationService, Generation]:
    values = {"vault_root": str(base / "share/vault"), "share_root": str(base / "share"),
              "state_root": str(base / "state"), "request_root": str(base / "requests"),
              "export_root": str(base / "exports"), "backup_root": str(base / "backups"),
              "knowledge_registry": str(base / "registry.sqlite"),
              "provider_instance_id": "provider:fixture", "provider_release_sha": "a" * 40}
    path = base / "config.toml"
    _ = path.write_text("\n".join(key + " = " + json.dumps(value) for key, value in values.items())
                        + "\n[search]\nhybrid = true\n")
    monkeypatch.setenv("SB_CONFIG", str(path))
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    config = load_config(path)
    service = GenerationMutationService.from_config(config)

    def materialize(root: Path) -> None:
        cas = ContentAddressedStore(root)
        texts = ("비용은 만원", "회의는 월요일")
        digests = [cas.put(text.encode()) for text in texts]
        cites = [SourceCite(digest[:8], "inbox:fixture-" + str(i), digest) for i, digest in enumerate(digests)]
        page = PageSpec("wiki/memory-fixture", "결정", "# 결정\n" + "\n".join(
            text + "[^" + cite.sid + "]" for text, cite in zip(texts, cites, strict=True)), cites, "active")
        _ = init_vault(root).write_pages([page], "semantic-fixture", _NoPreviousPage())

    result = service.mutate(GenerationMutation(mutation_id="semantic-fixture", operation=GenerationOperation.COMPILE,
                            now=NOW, authority=GenerationAuthority(None, None), apply=materialize))
    assert audit_citations(result.generation.root) == ()
    return config, service, result.generation


@pytest.mark.parametrize("schema", [4, 5])
def test_mcp_semantic_record_identity_and_deduplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: int,
) -> None:
    _, service, generation = runtime_fixture(tmp_path, monkeypatch)
    server = build_server(contract_schema=4 if schema == 4 else 5)

    async def exercise() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            async def call(name: str, args: JsonObject) -> JsonObject:
                result = await client.call_tool(name, args)
                assert not result.is_error, result
                value = TypeAdapter[JsonValue](JsonValue).validate_python(cast(object, result.structured_content))
                assert is_json_object(value)
                return value

            searched = await call("sb_search", {"query": "일정", "limit": 1})
            rows = searched["results"]
            assert isinstance(rows, list) and len(rows) == 1
            row = rows[0]
            assert is_json_object(row) and row["snippet"] == "회의는 월요일"
            page = await call("sb_read_page", {"id": "wiki/memory-fixture"})
            records = page["records"]
            assert isinstance(records, list)
            matched = [record for record in records if is_json_object(record) and record["record_id"] == row["record_id"]]
            assert len(matched) == 1 and is_json_object(matched[0])
            assert matched[0]["record_digest"] == row["record_digest"]
            assert matched[0]["record_text"] == row["snippet"]
            assert searched["generation_id"] == page["generation_id"] == generation.generation_id
            both = await call("sb_search", {"query": "월요일", "limit": 1})
            assert isinstance(both["results"], list) and len(both["results"]) == 1
            assert (await call("sb_search", {"query": '"일정"', "limit": 1}))["results"] == []

    try:
        anyio.run(exercise)
    finally:
        service.close()
