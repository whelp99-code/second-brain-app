"""Configured cosine floors filter semantic candidates without dropping literal evidence."""
from __future__ import annotations

from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import anyio
import pytest
from mcp.client import Client

from sb import embeddings
from sb.cli import main
from sb.config import Config, ConfigValueError, TomlValue, load_config
from sb.effect_values import JsonObject
from sb.mcp import build_server
from sb.search import SearchIndex
from tests.test_generation_vectors import (
    _build,  # pyright: ignore[reportPrivateUsage]
    _page,  # pyright: ignore[reportPrivateUsage]
    _store,  # pyright: ignore[reportPrivateUsage]
)
from tests.test_hybrid_filters import seeded
from tests.test_mcp_sealed_vectors import runtime_fixture
from tests.test_sealed_vectors import SemanticEncoder
from tests.test_web import (
    _request,  # pyright: ignore[reportPrivateUsage]
    _running,  # pyright: ignore[reportPrivateUsage]
)


@pytest.mark.parametrize("value", [True, False, "0.5", [], {}, None, float("nan"), float("inf"), -1.01, 1.01, 10**1000])
def test_invalid_similarity_is_rejected_without_vault_io(tmp_path: Path, value: object) -> None:
    config = Config(raw={"search": {"min_similarity": cast(TomlValue, value)}})
    with pytest.raises(ConfigValueError):
        _ = config.search_min_similarity
    with pytest.raises(ConfigValueError):
        _ = SearchIndex(tmp_path / "absent", min_similarity=cast(float, value))
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("value", [-1, 0, 0.55, 1])
def test_explicit_similarity_value_and_legacy_default(value: float) -> None:
    assert Config().search_min_similarity == -1.0
    assert Config(raw={"search": {"min_similarity": value}}).search_min_similarity == value


def test_cli_invalid_similarity_returns_error_not_empty_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.toml"
    _ = path.write_text('[search]\nmin_similarity = "0.5"\n')
    monkeypatch.setenv("SB_CONFIG", str(path))
    assert main(["search", "fixture", "--json"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "min_similarity" in captured.err


@pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional")
def test_sealed_floor_preserves_lexical_hits_and_applies_after_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "resolve_encoder", SemanticEncoder)
    store = _store(tmp_path)
    try:
        generation = _build(store, {"target": _page("회의는 월요일"),
                                    "noise": _page("비용은 만원").replace("status: active", "status: draft")})
        registry = tmp_path / "registry.sqlite"
        before = SearchIndex(generation.root, hybrid=True, registry_path=registry)
        after = SearchIndex(generation.root, hybrid=True, registry_path=registry, min_similarity=0.5)
        assert len(before.search("일정", 10, scope="reference")) == 2
        assert [hit.page_id for hit in after.search("일정", 10, scope="reference")] == ["wiki/target"]
        assert after.search("일정", 1, scope="reference", status="draft") == ()
        assert any(hit.page_id == "wiki/target" for hit in after.search("회의", 10, scope="reference"))
        # A literal hit may have low cosine; the floor is not a lexical veto.
        assert any(hit.page_id == "wiki/target" for hit in after.search('"회의"', 10, scope="reference"))
    finally:
        store.close()


def test_standalone_floor_filters_cosine_before_fusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = seeded(tmp_path, monkeypatch)
    before = SearchIndex(root, hybrid=True)
    after = SearchIndex(root, hybrid=True, min_similarity=0.99)
    assert before.search("absent semantic query", 10, scope="reference")
    assert after.search("absent semantic query", 10, scope="reference") == ()
    assert after.search("SemanticNeedle", 10, scope="reference")


@pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional")
@pytest.mark.parametrize("schema", [4, 5])
def test_mcp_frozen_response_obeys_configured_similarity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: int,
) -> None:
    _, service, generation = runtime_fixture(tmp_path, monkeypatch)
    path = tmp_path / "config.toml"
    _ = path.write_text(path.read_text() + "min_similarity = 0.5\n")
    server = build_server(contract_schema=4 if schema == 4 else 5)

    async def exercise() -> None:
        async with Client(server, mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_search", {"query": "일정", "limit": 10})
            assert not result.is_error
            payload = cast(JsonObject, result.structured_content)
            assert payload["generation_id"] == generation.generation_id
            rows = cast(list[JsonObject], payload["results"])
            assert len(rows) == 1 and rows[0]["snippet"] == "회의는 월요일"

    try:
        anyio.run(exercise)
    finally:
        service.close()


@pytest.mark.skipif(not embeddings.sqlite_vec_available(), reason="sqlite-vec optional")
@pytest.mark.parametrize("setting,expected_status", [("0.5", 200), ('"bad"', 400)])
def test_http_similarity_setting_and_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str, expected_status: int,
) -> None:
    _, service, _ = runtime_fixture(tmp_path, monkeypatch)
    path = tmp_path / "config.toml"
    _ = path.write_text(path.read_text() + "min_similarity = " + setting + "\n")
    try:
        with _running(load_config(path)) as base:
            status, payload = _request(base + "/api/search?" + urlencode({"q": "일정", "limit": 10}))
        assert status == expected_status
        if status == 200:
            rows = cast(list[dict[str, object]], cast(dict[str, object], payload)["results"])
            assert len(rows) == 1 and rows[0]["snippet"] == "회의는 월요일"
        else:
            assert "min_similarity" in str(payload)
    finally:
        service.close()
