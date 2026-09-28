import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from sb.bound_knowledge import BoundKnowledge
from sb.store.ledger import Ledger, ledger_schema_version, migrate_ledger

STATE = BoundKnowledge('wiki/검증', 'sha256:' + 'a' * 64, 'ACTIVE', 'APPROVED')


@pytest.mark.parametrize('field,value', [
    ('page_id', '../secret'), ('page_id', 'wiki/../secret'),
    ('page_id', 'wiki/_proposed/test'), ('page_id', 'wiki/Upper'),
    ('page_id', 'wiki/'), ('page_id', 'wiki/a\x00b'),
    ('content_digest', 'a' * 64), ('content_digest', 'sha256:' + 'A' * 64),
    ('knowledge_status', 'anything'), ('approval_status', 'anything'),
    ('knowledge_status', []), ('approval_status', None),
    ('page_id', None), ('content_digest', None),
])
def test_invalid_binding_rejected(field: str, value: str | list[str] | None) -> None:
    with pytest.raises(ValueError, match='BOUND_KNOWLEDGE_'):
        _ = replace(STATE, **{field: value})


def test_binding_survives_reopen_and_never_transfers_to_other_content(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        ledger.bind_knowledge(STATE)
        ledger.bind_knowledge(STATE)
        with pytest.raises(ValueError, match='BOUND_KNOWLEDGE_CONFLICT'):
            ledger.bind_knowledge(replace(STATE, approval_status='REJECTED'))
    with Ledger(tmp_path) as ledger:
        assert ledger.knowledge_for(STATE.page_id, STATE.content_digest) == STATE
        assert ledger.knowledge_for(STATE.page_id, 'sha256:' + 'b' * 64) is None
        with pytest.raises(RuntimeError), ledger.transaction():
            ledger.bind_knowledge(replace(STATE, content_digest='sha256:' + 'b' * 64))
            raise RuntimeError('rollback')
        assert ledger.knowledge_for(STATE.page_id, 'sha256:' + 'b' * 64) is None


def test_v4_migration_preserves_existing_data_and_backup(tmp_path: Path) -> None:
    # Reconstruct the previous schema by removing only the new additive table.
    with Ledger(tmp_path):
        pass
    path = tmp_path / '.sb' / 'ledger.db'
    with closing(sqlite3.connect(path)) as conn:
        _ = conn.execute('DROP TABLE bound_knowledge')
        _ = conn.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
        _ = conn.execute("INSERT INTO run VALUES ('existing', '2026-09-10T00:00:00Z', NULL, NULL, 'ok')")
        conn.commit()
    backup = migrate_ledger(path)
    assert backup is not None
    assert ledger_schema_version(backup) == 4
    assert ledger_schema_version(path) == 5
    with closing(sqlite3.connect(backup)) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='bound_knowledge'").fetchone() is None
        assert conn.execute('SELECT run_id FROM run').fetchall() == [('existing',)]
    with Ledger(tmp_path) as ledger:
        ledger.bind_knowledge(STATE)
        assert ledger.knowledge_for(STATE.page_id, STATE.content_digest) == STATE
    assert migrate_ledger(path) is None
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT run_id FROM run').fetchall() == [('existing',)]
        assert conn.execute('SELECT COUNT(*) FROM bound_knowledge').fetchone() == (1,)
