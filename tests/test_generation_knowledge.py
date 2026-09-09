"""Knowledge bindings must survive sealing and participate in its identity."""
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.generation_access import access_bound_ledger_digest, verified_ledger_digest
from sb.generation_integrity import GenerationIntegrityError, load_verified_manifest
from sb.generations import GenerationStore
from sb.store.ledger import Ledger

BODY = '검증용 본문'
STATE = BoundKnowledge('wiki/검증', 'sha256:' + hashlib.sha256(BODY.encode()).hexdigest(), 'ACTIVE', 'APPROVED')


def build(root, states):
    store = GenerationStore(root / 'state', root / 'share', provider_instance_id='provider:fixture', provider_release_sha='a' * 40)
    try:
        def materialize(path):
            page = path / 'wiki' / '검증.md'
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(BODY)
            with Ledger(path) as ledger:
                for state in states:
                    ledger.bind_knowledge(state)
        return store.build(request_id='fixture:knowledge', parent=None, tombstone_sequence=0,
            tombstone_set_root='sha256:' + '0' * 64, created_at=datetime(2026, 9, 10, tzinfo=UTC),
            allowed=lambda _: True, mutate=materialize)
    finally:
        store.close()


def test_state_changes_identity_and_order_does_not(tmp_path):
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
def test_tampering_rejected_after_inventory_refresh(tmp_path, sql):
    generation = build(tmp_path, (STATE,))
    folder = generation.root / '.sb'
    folder.chmod(0o700)
    path = folder / 'ledger.db'
    path.chmod(0o600)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(sql)
        connection.commit()
    inventory_path = folder / 'derived-manifest.json'
    inventory = json.loads(inventory_path.read_text())
    for row in inventory['stores']:
        if row['name'] == 'ledger.db':
            row['digest'] = 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
            row['bytes'] = path.stat().st_size
    inventory_path.chmod(0o600)
    inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(GenerationIntegrityError, match='GENERATION_SPLIT_BRAIN'):
        load_verified_manifest(generation.root)


def test_empty_and_absent_table_preserve_legacy_digest(tmp_path):
    with Ledger(tmp_path):
        pass
    legacy = 'sha256:' + 'c' * 64
    assert access_bound_ledger_digest(tmp_path, legacy) == legacy
    with closing(sqlite3.connect(tmp_path / '.sb' / 'ledger.db')) as connection:
        connection.execute('DROP TABLE bound_knowledge')
        connection.commit()
    assert access_bound_ledger_digest(tmp_path, legacy) == legacy


def test_sealed_binding_readable_in_fresh_process(tmp_path):
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


def test_old_body_binding_is_not_projected_onto_current_body(tmp_path):
    from sb.knowledge_registry import KnowledgeState
    from sb.sealed_knowledge import sealed_knowledge_states

    generation = build(tmp_path, (replace(STATE, content_digest='sha256:' + 'f' * 64),))
    assert sealed_knowledge_states(generation.root, (KnowledgeState(STATE.page_id, 'ACTIVE', 'APPROVED'),)) == ()
