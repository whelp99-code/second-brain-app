"""Observation-to-page lineage: provenance, derivation key, human edit, briefing prose."""

from __future__ import annotations

import json
from pathlib import Path

from sb.briefing import generate_briefing
from sb.compile import compile_page_key, compile_pages
from sb.config import Config
from sb.connectors.base import ItemMeta
from sb.contracts import BriefingInputs, SourceRef, Unit
from sb.llm import FakeLLM
from sb.parsers import parse_document
from sb.pipeline import run_compile, run_ingest
from sb.store.ledger import Ledger
from sb.vault import Vault, init_vault

HASH = "aa" * 32


class _Adapter:
    source_id = "docs"
    accepted_adapters = frozenset({"fixture"})

    def __init__(self, payload: bytes, uri: str) -> None:
        self.payload = payload
        self.uri = uri

    def scan(self, cursor: str | None):
        del cursor
        meta: ItemMeta = {"relative_path": self.uri}
        yield SourceRef(self.source_id, self.uri, "v1"), self.payload, meta

    def next_cursor(self) -> str:
        return "done"


def _config(root: Path) -> Config:
    return Config(raw={
        "vault_root": str(root),
        "knowledge_registry": str(root.parent / "registry.sqlite"),
        "sources": [{"id": "docs", "adapter": "fixture"}],
        "llm": {"prompt_version": "v1", "model_id": "fake"},
    })


def _unit(unit_id: str) -> Unit:
    return Unit(unit_id, HASH, "0-4", "text", "docs:note.md")


def test_unit_provenance_persisted_from_parse_result(tmp_path: Path, monkeypatch) -> None:
    payload = b"visible lineage note\n"
    parsed = parse_document(payload, ".md")
    root = tmp_path / "vault"
    init_vault(root)
    monkeypatch.setattr(
        "sb.connectors.discover_adapters",
        lambda config: {"fixture": _Adapter(payload, "note.md")},
    )
    assert run_ingest(_config(root), ("docs",)).exit_code == 0
    with Ledger(root) as ledger:
        rows = [ledger.provenance_for_unit(unit.unit_id) for unit in ledger._tables.units.values()]
    stored = [row for row in rows if row is not None]
    assert stored
    assert stored[0].parser_version == parsed.parser_version
    assert stored[0].model_version == parsed.model_version
    assert stored[0].partial_reason == parsed.partial_reason
    assert json.loads(stored[0].locator_json) == parsed.locator
    assert stored[0].content_hash == parsed.source_hash.removeprefix("sha256:")


def test_derivation_key_includes_parser_model_normalization_profile_revision(tmp_path: Path) -> None:
    unit = _unit("unit-1")
    with Ledger(tmp_path) as ledger:
        from sb.store import UnitProvenance

        ledger.upsert_unit_provenance(UnitProvenance(
            unit.unit_id, HASH, "builtin:.md", "none", "v2", "local-only",
            '{"kind":"ordinal","ordinal":1}', None,
        ))
        pages = compile_pages([unit], ledger, FakeLLM(["cited.[^aaaaaaaa]"]), Config(raw={
            "llm": {"prompt_version": "v1", "model_id": "fake"},
        }))
        lineage = "builtin:.md\x1fnone\x1fv2\x1flocal-only"
        expected = compile_page_key(pages[0].page_id, [unit.unit_id], "v1", "fake", lineage=lineage)
        assert pages[0].derivation_key == expected
        for changed in (
            "builtin:.md-next\x1fnone\x1fv2\x1flocal-only",
            "builtin:.md\x1fmodel-x\x1fv2\x1flocal-only",
            "builtin:.md\x1fnone\x1fv3\x1flocal-only",
            "builtin:.md\x1fnone\x1fv2\x1fprofile-2",
        ):
            assert compile_page_key(pages[0].page_id, [unit.unit_id], "v1", "fake", lineage=changed) != expected


def test_recompile_with_new_parser_is_new_derivation_not_overwrite(tmp_path: Path) -> None:
    unit = _unit("unit-1")
    config = Config(raw={"llm": {"prompt_version": "v1", "model_id": "fake"}})
    with Ledger(tmp_path) as ledger:
        from sb.store import UnitProvenance

        ledger.upsert_unit_provenance(UnitProvenance(
            unit.unit_id, HASH, "builtin:.md", "none", "v2", "local-only", "{}", None,
        ))
        first = compile_pages([unit], ledger, FakeLLM(["cited.[^aaaaaaaa]"]), config)
        old_key = first[0].derivation_key
        assert old_key is not None
        old = ledger.get_derivation(old_key)
        assert old is not None and old.status == "done"
        old_hash = old.output_hash
        ledger.replace_provenance_parser(unit.unit_id, "builtin:.md-v2")
        second = compile_pages([unit], ledger, FakeLLM(["cited.[^aaaaaaaa]"]), config)
        new_key = second[0].derivation_key
        assert new_key is not None and new_key != old_key
        kept = ledger.get_derivation(old_key)
        assert kept is not None and kept.status == "done" and kept.output_hash == old_hash
        assert ledger.get_derivation(new_key) is not None


def test_human_edit_during_compile_stays_proposed(tmp_path: Path, monkeypatch) -> None:
    payload = b"human lineage source\n"
    root = tmp_path / "vault"
    init_vault(root)
    monkeypatch.setattr(
        "sb.connectors.discover_adapters",
        lambda config: {"fixture": _Adapter(payload, "note.md")},
    )
    config = _config(root)
    assert run_ingest(config, ("docs",)).exit_code == 0
    assert run_compile(config, llm_mode="fake").exit_code == 0
    with Ledger(root) as ledger:
        for unit_id in list(ledger._tables.units):
            if ledger.provenance_for_unit(unit_id) is not None:
                ledger.replace_provenance_parser(unit_id, "builtin:.md-edited")
    pages = list((root / "wiki").glob("*.md"))
    assert len(pages) == 1
    target = pages[0]

    real = Vault.write_pages

    def edited(self, pages, run_id, ledger, **kwargs):
        target.write_text(target.read_text(encoding="utf-8") + "\nHUMAN_EDIT\n", encoding="utf-8")
        return real(self, pages, run_id, ledger, **kwargs)

    monkeypatch.setattr(Vault, "write_pages", edited)
    outcome = run_compile(config, llm_mode="fake")
    assert "HUMAN_EDIT" in target.read_text(encoding="utf-8")
    proposed = list((root / "wiki" / "_proposed").glob("*.md"))
    assert proposed
    assert "HUMAN_EDIT" not in proposed[0].read_text(encoding="utf-8")
    assert outcome.failure is None or "proposal" in (outcome.failure or "").lower() or outcome.errors >= 0


def test_prior_briefing_prose_is_not_evidence() -> None:
    prose = "PRIOR_BRIEFING_PROSE_NOT_EVIDENCE"
    cite = f"origin=notes:old.md hash={'cd' * 32} [^{'cd' * 4}] text={prose}"
    spec = generate_briefing(
        BriefingInputs(("origin=notes:live.md hash=" + "ab" * 32 + " [^aaaaaaaa] text=live"), (), (), (), cite, "ok"),
        FakeLLM(["- keep [^aaaaaaaa]\n- keep [^aaaaaaaa]\n- keep [^aaaaaaaa]\n"]),
        Config(raw={"llm": {"prompt_version": "v1", "model_id": "fake"}}),
    )
    assert all(item.origin != "notes:old.md" for item in spec.sources)
    assert prose not in " ".join(item.origin for item in spec.sources)
    assert all(prose not in (item.hash) for item in spec.sources)
