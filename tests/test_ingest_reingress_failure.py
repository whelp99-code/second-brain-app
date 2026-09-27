import sqlite3
from pathlib import Path

import pytest

from sb.config import Config
from sb.pipeline import run_ingest
from sb.reingress import ReingressGate
from sb.store.ledger import load_ledger_tables


def test_unavailable_reingress_query_is_failed_and_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    note = inbox / 'note.md'
    _ = note.write_text('Original must remain until deletion checks can complete.')
    config = Config(raw={'vault_root': str(tmp_path / 'share/vault'),
        'share_root': str(tmp_path / 'share'), 'state_root': str(tmp_path / 'state'),
        'sources': [{'id': 'fixture', 'adapter': 'inbox-documents', 'root': str(inbox)}]})
    original = ReingressGate.check_content

    def unavailable(self: ReingressGate, content: bytes) -> None:
        previous = self.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 0)
        try:
            return original(self, content)
        finally:
            _ = self.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous)

    with monkeypatch.context() as patch:
        patch.setattr(ReingressGate, 'check_content', unavailable)
        result = run_ingest(config, ('fixture',))
    assert result.exit_code == 1 and result.errors == 1
    assert result.failure == 'REINGRESS_VERIFICATION_FAILED'
    tables = load_ledger_tables(Path(config.vault_root) / '.sb/ledger.db')
    assert not tables.source_items and not tables.cursors
    assert note.exists()
    recovered = run_ingest(config, ('fixture',))
    assert recovered.exit_code == 0 and recovered.written == 1
    assert len(load_ledger_tables(Path(config.vault_root) / '.sb/ledger.db').source_items) == 1
