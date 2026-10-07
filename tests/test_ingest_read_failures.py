import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from sb.config import Config
from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef
from sb.pipeline import run_ingest
from sb.store.ledger import load_ledger_tables


class Adapter:
    source_id: str = 'fixture'
    accepted_adapters: frozenset[str] = frozenset({'fixture-adapter'})

    def __init__(self, reason: str) -> None:
        self.reason: str | None = reason
        self.legacy: bool = False

    def scan(self, cursor: str | None) -> Iterator[tuple[SourceRef, bytes, ItemMeta]]:
        del cursor
        if self.reason:
            meta: ItemMeta = {'relative_path': 'bad', 'skip_reason': (
                'invalid-format' if self.legacy else self.reason)}
            yield SourceRef('fixture', 'bad', self.reason), b'', meta
        yield SourceRef('fixture', 'good', 'v1'), b'valid sibling', {'relative_path': 'good'}

    def next_cursor(self) -> str:
        return 'completed'


@pytest.mark.parametrize('reason', ['size-limit', 'database-limit',
                                    'unstable-session-file', 'unreadable-session-file'])
@pytest.mark.parametrize('legacy', [False, True])
def test_read_failure_is_visible_every_run_and_recovers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, legacy: bool):
    adapter = Adapter(reason)
    def discover(_config: Config) -> dict[str, Adapter]:
        return {'fixture-adapter': adapter}
    monkeypatch.setattr('sb.connectors.discover_adapters', discover)
    config = Config(raw={'vault_root': str(tmp_path / 'share/vault'),
        'share_root': str(tmp_path / 'share'), 'state_root': str(tmp_path / 'state'),
        'sources': [{'id': 'fixture', 'adapter': 'fixture-adapter'}]})
    if legacy:
        adapter.legacy = True
        assert run_ingest(config, ('fixture',)).exit_code == 0
        adapter.legacy = False
    initial = load_ledger_tables(Path(config.vault_root) / '.sb/ledger.db').cursors if legacy else {}
    for _ in range(2):
        outcome = run_ingest(config, ('fixture',))
        assert outcome.exit_code == 1 and outcome.errors == 1
        assert outcome.failure == f'SOURCE_READ_INCOMPLETE: fixture: {reason}'
        tables = load_ledger_tables(Path(config.vault_root) / '.sb/ledger.db')
        assert tables.cursors == initial
        assert len([item for item in tables.source_items.values() if item.source_uri == 'good']) == 1
        with closing(sqlite3.connect((Path(config.vault_root) / '.sb/ledger.db').as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            details = db.execute('SELECT detail FROM run_stage WHERE run_id=?', (outcome.run_id,)).fetchall()
        assert (outcome.failure,) in details
    adapter.reason = None
    recovered = run_ingest(config, ('fixture',))
    assert recovered.exit_code == 0 and recovered.errors == 0
    assert load_ledger_tables(Path(config.vault_root) / '.sb/ledger.db').cursors['fixture'][0] == 'completed'
