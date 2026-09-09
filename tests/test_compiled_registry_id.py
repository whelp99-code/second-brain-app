from pathlib import Path

from sb.contracts import PageSpec
from sb.knowledge_registry import KnowledgeRegistry
from sb.pipeline import _register_compiled


def test_compiled_bare_id_registers_committed_path(tmp_path: Path, monkeypatch):
    registry = tmp_path / 'registry.sqlite'
    monkeypatch.setenv('SB_KNOWLEDGE_REGISTRY', str(registry))
    monkeypatch.setenv('SB_CONFIG', str(tmp_path / 'absent-config.toml'))
    _register_compiled(tmp_path, [PageSpec('한글-기억', '제목', '본문', [], 'active')], project=False)
    states = KnowledgeRegistry(registry).read_snapshot()
    assert [row.page_id for row in states] == ['wiki/한글-기억']


def test_explicit_config_registry_overrides_global(tmp_path: Path, monkeypatch):
    from sb.config import Config

    target = tmp_path / 'chosen.sqlite'
    unrelated = tmp_path / 'global.sqlite'
    monkeypatch.setenv('SB_KNOWLEDGE_REGISTRY', str(unrelated))
    config = Config(raw={'knowledge_registry': str(target)})
    _register_compiled(tmp_path, [PageSpec('isolated', 'Title', 'body', [], 'active')],
                       project=False, config=config)
    assert [r.page_id for r in KnowledgeRegistry(target).read_snapshot()] == ['wiki/isolated']
    assert not unrelated.exists()
