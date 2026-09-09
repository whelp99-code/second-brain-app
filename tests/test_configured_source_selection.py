"""Explicit source configuration must bound implicit batch collection."""
from sb.config import Config
from sb.pipeline import _select_adapters


def test_implicit_selection_excludes_unconfigured_adapters(monkeypatch, tmp_path):
    class Adapter:
        def __init__(self, source_id):
            self.source_id = source_id
    chosen = {'inbox': Adapter('inbox'), 'sessions-codex': Adapter('sessions-codex')}
    monkeypatch.setattr('sb.connectors.discover_adapters', lambda config: chosen)
    config = Config(raw={'vault_root': str(tmp_path), 'sources': [{'id': 'inbox', 'adapter': 'inbox-documents'}]})
    assert [a.source_id for a in _select_adapters(chosen, None, config)] == ['inbox']


def test_explicit_empty_source_list_does_not_enable_default_sources(tmp_path):
    class Adapter:
        source_id = 'sessions-codex'
    config = Config(raw={'vault_root': str(tmp_path), 'sources': []})
    assert _select_adapters({'sessions-codex': Adapter()}, None, config) == []


def test_legacy_defaults_and_explicit_request_remain_available(tmp_path):
    class Adapter:
        source_id = 'sessions-codex'
    chosen = {'sessions-codex': Adapter()}
    legacy = Config(raw={'vault_root': str(tmp_path)})
    assert _select_adapters(chosen, None, legacy) == list(chosen.values())
    explicit_empty = Config(raw={'vault_root': str(tmp_path), 'sources': []})
    assert _select_adapters(chosen, ['sessions-codex'], explicit_empty) == list(chosen.values())


def test_unknown_configured_source_is_rejected_before_scan(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr('sb.connectors.discover_adapters', lambda config: {})
    config = Config(raw={'vault_root': str(tmp_path), 'sources': [{'id': 'typo-source', 'adapter': 'missing-adapter'}]})
    with pytest.raises(ValueError, match='SOURCE_NOT_FOUND: typo-source'):
        _select_adapters({}, None, config)
