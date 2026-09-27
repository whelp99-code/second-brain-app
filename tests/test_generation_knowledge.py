"""Knowledge bindings must survive sealing and participate in its identity."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.effect_values import JsonObject
from sb.generation_access import access_bound_ledger_digest, verified_ledger_digest
from sb.generation_integrity import GenerationIntegrityError, load_verified_manifest
from sb.generations import Generation, GenerationStore
from sb.store.ledger import Ledger
from tests.json_fixtures import parse_object

BODY = '검증용 본문'
STATE = BoundKnowledge('wiki/검증', 'sha256:' + hashlib.sha256(BODY.encode()).hexdigest(), 'ACTIVE', 'APPROVED')


def build(root: Path, states: tuple[BoundKnowledge, ...]) -> Generation:
    store = GenerationStore(root / 'state', root / 'share', provider_instance_id='provider:fixture', provider_release_sha='a' * 40)
    try:
        def materialize(path: Path) -> None:
            page = path / 'wiki' / '검증.md'
            page.parent.mkdir(parents=True, exist_ok=True)
            _ = page.write_text(BODY)
            with Ledger(path) as ledger:
                for state in states:
                    ledger.bind_knowledge(state)
        return store.build(request_id='fixture:knowledge', parent=None, tombstone_sequence=0,
            tombstone_set_root='sha256:' + '0' * 64, created_at=datetime(2026, 9, 10, tzinfo=UTC),
            allowed=lambda _: True, mutate=materialize)
    finally:
        store.close()


def test_state_changes_identity_and_order_does_not(tmp_path: Path):
    other = replace(STATE, content_digest='sha256:' + 'b' * 64)
    groups = [(STATE, other), (other, STATE), (replace(STATE, approval_status='PENDING'), other), ()]
    results = [build(tmp_path / str(i), states) for i, states in enumerate(groups)]
    assert results[0].generation_id == results[1].generation_id
    assert len({g.generation_id for g in (results[0], results[2], results[3])}) == 3
    for generation in results:
        manifest = load_verified_manifest(generation.root)
        assert verified_ledger_digest(generation.root, manifest) == manifest['ledger_manifest_digest']


@pytest.mark.parametrize('sql', [
    "UPDATE bound_knowledge SET approval_status='PENDING'",
    "UPDATE bound_knowledge SET content_digest='sha256:' || replace(hex(zeroblob(32)), '0', 'b')",
    "UPDATE bound_knowledge SET page_id='wiki/other'",
    "UPDATE bound_knowledge SET knowledge_status='RETIRED'",
    "UPDATE bound_knowledge SET approval_status='garbage'",
    'DELETE FROM bound_knowledge',
    'DROP TABLE bound_knowledge',
])
def test_tampering_rejected_after_inventory_refresh(tmp_path: Path, sql: str):
    generation = build(tmp_path, (STATE,))
    folder = generation.root / '.sb'
    folder.chmod(0o700)
    path = folder / 'ledger.db'
    path.chmod(0o600)
    with closing(sqlite3.connect(path)) as connection:
        _ = connection.execute(sql)
        connection.commit()
    inventory_path = folder / 'derived-manifest.json'
    inventory = parse_object(inventory_path.read_text())
    stores = inventory['stores']
    assert isinstance(stores, list)
    for row in stores:
        assert isinstance(row, dict)
        if row['name'] == 'ledger.db':
            row['digest'] = 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
            row['bytes'] = path.stat().st_size
    inventory_path.chmod(0o600)
    _ = inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(GenerationIntegrityError, match='GENERATION_SPLIT_BRAIN'):
        _ = load_verified_manifest(generation.root)


def test_empty_and_absent_table_preserve_legacy_digest(tmp_path: Path):
    with Ledger(tmp_path):
        pass
    legacy = 'sha256:' + 'c' * 64
    assert access_bound_ledger_digest(tmp_path, legacy) == legacy
    with closing(sqlite3.connect(tmp_path / '.sb' / 'ledger.db')) as connection:
        _ = connection.execute('DROP TABLE bound_knowledge')
        connection.commit()
    assert access_bound_ledger_digest(tmp_path, legacy) == legacy


def test_sealed_binding_readable_in_fresh_process(tmp_path: Path):
    import subprocess
    import sys

    generation = build(tmp_path, (STATE,))
    result = subprocess.run([sys.executable, '-c',
        ('import sys; from pathlib import Path; '
        'from sb.generation_integrity import load_verified_manifest; '
        'print(load_verified_manifest(Path(sys.argv[1]))["generation_id"])'),
        str(generation.root)], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == generation.generation_id


def test_old_body_binding_is_not_projected_onto_current_body(tmp_path: Path):
    from sb.knowledge_registry import KnowledgeState
    from sb.sealed_knowledge import sealed_knowledge_states

    generation = build(tmp_path, (replace(STATE, content_digest='sha256:' + 'f' * 64),))
    assert sealed_knowledge_states(generation.root, (KnowledgeState(STATE.page_id, 'ACTIVE', 'APPROVED'),)) == ()


def test_knowledge_projection_rejects_ledger_change_after_initial_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sb.sealed_knowledge as module
    from sb.search_errors import GenerationIndexError

    generation = build(tmp_path, (replace(STATE, approval_status='PENDING'),))
    verify = load_verified_manifest
    calls = 0

    def change_after_validation(root: Path) -> JsonObject:
        nonlocal calls
        manifest = verify(root)
        calls += 1
        if calls == 1:
            ledger = root / '.sb/ledger.db'
            ledger.parent.chmod(0o700)
            ledger.chmod(0o600)
            with closing(sqlite3.connect(ledger)) as connection:
                _ = connection.execute("UPDATE bound_knowledge SET approval_status='APPROVED'")
                connection.commit()
        return manifest

    monkeypatch.setattr(module, 'load_verified_manifest', change_after_validation)
    with pytest.raises(GenerationIndexError):
        _ = module.sealed_knowledge_states(generation.root, ())
