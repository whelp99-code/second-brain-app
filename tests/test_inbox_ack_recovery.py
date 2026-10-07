from pathlib import Path

from sb.config import Config
from sb.pipeline import run_ingest
from sb.store import load_ledger_tables


def test_ack_failure_is_reported_and_retry_uses_committed_input(tmp_path: Path):
    inbox = tmp_path / 'intake'
    inbox.mkdir()
    note = inbox / 'note.md'
    _ = note.write_text('Committed source remains retryable')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (inbox / '.done').symlink_to(outside, target_is_directory=True)
    config = Config(raw={'vault_root': str(tmp_path / 'share/vault'),
        'share_root': str(tmp_path / 'share'), 'state_root': str(tmp_path / 'state'),
        'request_root': str(tmp_path / 'requests'), 'export_root': str(tmp_path / 'exports'),
        'knowledge_registry': str(tmp_path / 'registry.sqlite'),
        'sources': [{'id': 'inbox', 'adapter': 'inbox-documents', 'root': str(inbox)}]})
    failed = run_ingest(config, ('inbox',))
    assert failed.failure == "SOURCE_ACKNOWLEDGEMENT_FAILED"
    assert failed.errors == 1
    assert failed.exit_code != 0
    assert note.read_text() == 'Committed source remains retryable'
    assert list(outside.iterdir()) == []
    before = load_ledger_tables(Path(config.vault_root).resolve() / ".sb/ledger.db").source_items
    assert len(before) == 1
    (inbox / '.done').unlink()
    recovered = run_ingest(config, ('inbox',))
    assert recovered.errors == 0 and recovered.exit_code == 0
    assert recovered.written == 0
    assert not note.exists()
    assert (inbox / '.done/note.md').read_text() == 'Committed source remains retryable'
    assert load_ledger_tables(Path(config.vault_root).resolve() / ".sb/ledger.db").source_items == before
