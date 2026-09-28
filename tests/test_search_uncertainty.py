"""Partial parses surface uncertainty on the search hit, not as empty success."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from sb.config import Config
from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef
from sb.parsers import parse_document
from sb.pipeline import run_compile, run_ingest
from sb.search import SearchIndex
from sb.vault import init_vault


class _Adapter:
    source_id = "docs"
    accepted_adapters = frozenset({"fixture"})

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def scan(self, cursor: str | None):
        del cursor
        meta: ItemMeta = {"relative_path": "sheet.xlsx"}
        yield SourceRef("docs", "sheet.xlsx", "v1"), self.payload, meta

    def next_cursor(self) -> str:
        return "done"


def test_partial_parse_surfaces_uncertainty_in_search_hit(tmp_path: Path, monkeypatch) -> None:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet["A1"] = "known-partial-cell"
    sheet["B1"] = "=1+1"
    payload = BytesIO()
    workbook.save(payload)
    raw = payload.getvalue()
    parsed = parse_document(raw, ".xlsx")
    assert parsed.partial_reason == "formula_unavailable"
    root = tmp_path / "vault"
    init_vault(root)
    monkeypatch.setattr("sb.connectors.discover_adapters", lambda config: {"fixture": _Adapter(raw)})
    config = Config(raw={
        "vault_root": str(root),
        "knowledge_registry": str(tmp_path / "registry.sqlite"),
        "sources": [{"id": "docs", "adapter": "fixture"}],
        "llm": {"prompt_version": "v1", "model_id": "fake"},
    })
    assert run_ingest(config, ("docs",)).exit_code == 0
    compiled = run_compile(config, llm_mode="fake")
    assert compiled.exit_code == 0, compiled
    hits = SearchIndex(vault_root=root, registry_path=tmp_path / "registry.sqlite").search("formula_unavailable")
    assert hits
    assert hits[0].uncertainty == "formula_unavailable"
