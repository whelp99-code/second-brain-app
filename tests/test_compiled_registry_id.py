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
