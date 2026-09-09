from sb.config import Config
from sb.pipeline import run_compile, run_ingest


def test_fake_compile_handles_conflict_checks_after_source_updates(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    note = source / 'notes.md'
    config = Config(raw={'vault_root': str(tmp_path / 'share/vault'),
        'share_root': str(tmp_path / 'share'), 'state_root': str(tmp_path / 'state'),
        'knowledge_registry': str(tmp_path / 'registry.sqlite'),
        'sources': [{'id': 'docs', 'adapter': 'markdown-vault', 'root': str(source)}]})
    for body in ('Alpha fixture memory', 'Updated Alpha fixture memory with additional detail.'):
        note.write_text(body)
        assert run_ingest(config, ['docs']).exit_code == 0
        result = run_compile(config, llm_mode='fake')
        assert result.exit_code == 0, result
    assert run_compile(config, llm_mode='fake').exit_code == 0
