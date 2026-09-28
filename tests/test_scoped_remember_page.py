import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.effect_values import JsonObject
from sb.generations import GenerationStore
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.remember_page import materialize_remember
from sb.scoped_write_preparation import ScopedWritePreparation, decode_scoped_write_preparation
from sb.source_access import SourceAccess
from sb.store.ledger import Ledger
from sb.targets import GenerationIdentityV1
from tests.json_fixtures import parse_object

NOW = datetime(2026, 8, 28, tzinfo=UTC)


def preparation():
    value = parse_object((Path(__file__).parent / "fixtures/scoped_write_preparation_v1.json").read_text())
    return decode_scoped_write_preparation(value, now=NOW)


def write(root: Path, value: ScopedWritePreparation, access: SourceAccess | None) -> None:
    candidate = parse_object(value.identity.canonical)["candidate_id"]
    assert isinstance(candidate, str)
    materialize_remember(root, content=value.content,
        candidate_id=candidate,
        created_at=NOW.isoformat(), release_sha="a" * 40,
        sensitivity=value.sensitivity, source_access=access)


def test_remember_scope_survives_sealing_and_denies_other_project(tmp_path: Path):
    value = preparation()
    store = GenerationStore(tmp_path / "state", tmp_path / "share",
        provider_instance_id="provider:test", provider_release_sha="a" * 40)
    try:
        generation = store.build(request_id="request-scoped-materialization", parent=None,
            tombstone_sequence=0, tombstone_set_root="sha256:" + "0" * 64,
            created_at=NOW, allowed=lambda _path: True,
            mutate=lambda root: write(root, value, value.source_access))
        store.activate(generation, None, NOW)
        manifest = parse_object((generation.root / "generation.json").read_text())
        identity = GenerationIdentityV1(*(str(manifest[name]) for name in (
            "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
        name = next((generation.root / "wiki").glob("*.md")).stem
        before = hashlib.sha256((generation.root / ".sb/ledger.db").read_bytes()).hexdigest()
        page = classified_page(generation.root, name, identity)
        assert len(page.records) == 4
        assert page.requirements == (value.source_access,)
        require_scope(page, value.source_access)
        with pytest.raises(MemoryAccessError, match="MEMORY_ACCESS_DENIED"):
            require_scope(page, SourceAccess("principal:owner", ("project:other",), "policy:fixture"))
        assert hashlib.sha256((generation.root / ".sb/ledger.db").read_bytes()).hexdigest() == before
        assert next((generation.root / "raw").glob("*/*")).read_bytes() == value.content.encode()
    finally:
        store.close()


def test_equal_retry_preserves_scope_and_reclassification_rolls_back(tmp_path: Path):
    value = preparation()
    write(tmp_path, value, value.source_access)
    page = next((tmp_path / "wiki").glob("*.md"))
    original = page.read_bytes()
    write(tmp_path, value, value.source_access)
    with pytest.raises(ValueError, match="SOURCE_ACCESS_RECLASSIFICATION_REQUIRED"):
        write(tmp_path, value, SourceAccess("principal:owner", ("project:other",), "policy:fixture"))
    assert page.read_bytes() == original
    with Ledger(tmp_path) as ledger:
        items = ledger.list_source_items()
        assert len(items) == 1
        assert ledger.source_access_for(items[0]) == value.source_access
        binding = ledger.page_access_for("wiki/" + page.stem, "sha256:" + hashlib.sha256(original).hexdigest())
        assert binding is not None and binding.complete and len(binding.source_refs) == 1


def test_identical_content_keeps_distinct_candidate_lineage_and_scope(tmp_path: Path):
    from sb.scoped_search import search_scoped_records

    content = 'SharedLineage 동일한 업무 결정'
    candidates = ('memcand:pos:v1:' + 'a' * 64, 'memcand:pos:v1:' + 'b' * 64)
    scopes = tuple(SourceAccess('principal:owner', (f'project:{name}',), '1') for name in ('a', 'b'))
    store = GenerationStore(tmp_path / 'state', tmp_path / 'share',
        provider_instance_id='provider:test', provider_release_sha='a' * 40)

    def materialize(root: Path) -> None:
        for candidate, scope in zip(candidates, scopes, strict=True):
            materialize_remember(root, content=content, candidate_id=candidate,
                created_at=NOW.isoformat(), release_sha='a' * 40, source_access=scope)

    try:
        generation = store.build(request_id='distinct-lineage', parent=None,
            tombstone_sequence=0, tombstone_set_root='sha256:' + '0' * 64,
            created_at=NOW, allowed=lambda _path: True, mutate=materialize)
        store.activate(generation, None, NOW)
        with store.pin() as pin:
            manifest = pin.generation.manifest
            identity = GenerationIdentityV1(manifest.provider_instance_id, generation.generation_id,
                manifest.generation_digest, generation.head, generation.tree)
            results: list[JsonObject] = []
            for candidate, scope in zip(candidates, scopes, strict=True):
                rows = TypeAdapter(list[JsonObject]).validate_python(
                    search_scoped_records(generation.root, identity, scope, 'SharedLineage', 10),
                    strict=True,
                )
                assert len(rows) == 1
                assert isinstance(rows[0], dict)
                record = rows[0]['record']
                assert isinstance(record, dict)
                expected = hashlib.sha256(f'memory-candidate:{candidate}'.encode()).hexdigest()
                assert record['source_identity_full'] == expected
                assert isinstance(rows[0]['page_id'], str)
                page = classified_page(generation.root, rows[0]['page_id'], identity)
                assert page.requirements == (scope,)
                assert len(page.source_refs) == 1
                results.append(rows[0])
            first_record, second_record = results[0]['record'], results[1]['record']
            assert isinstance(first_record, dict) and isinstance(second_record, dict)
            assert first_record['record_text'] == second_record['record_text']
            assert results[0]['page_id'] != results[1]['page_id']
            assert first_record['record_id'] != second_record['record_id']
            combined = SourceAccess('principal:owner', ('project:a', 'project:b'), '1')
            assert len(search_scoped_records(generation.root, identity, combined, 'SharedLineage', 10)) == 2
            assert len(tuple((generation.root / 'raw').glob('*/*'))) == 1
    finally:
        store.close()
