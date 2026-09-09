"""Read-only CLI binding must preserve the loaded config's path context."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sb.config import load_config
from sb.runtime_access import read_config
from sb.security import source_policy_snapshot
from sb.vault import init_vault


@pytest.mark.parametrize("root", ["notes", "$SB_TEST_SOURCE"])
def test_source_diagnostics_match_configured_collection_paths(tmp_path, monkeypatch, root):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "notes").mkdir()
    monkeypatch.setenv("SB_TEST_SOURCE", "notes")
    monkeypatch.chdir(tmp_path)
    path = settings / "config.toml"
    path.write_text('[[sources]]\nid="notes"\nadapter="markdown_vault"\nroot=' + json.dumps(root))
    config = load_config(path)
    row = source_policy_snapshot(config)[0]
    assert row["root"] == config.source_roots[0]["root"]
    assert row["root_exists"] is True


def test_read_config_preserves_loaded_path_context(tmp_path, monkeypatch):
    settings = tmp_path / "settings"
    settings.mkdir()
    path = settings / "config.toml"
    path.write_text('vault_root="vault"\nknowledge_registry="registry.json"\n')
    config = load_config(path)
    monkeypatch.chdir(tmp_path)
    with read_config(config) as pinned:
        assert pinned.knowledge_registry == config.knowledge_registry
        assert pinned.base_dir == config.base_dir
        assert pinned.source_path == config.source_path
        assert pinned.vault_root == config.vault_root


def test_actual_cli_doctor_resolves_source_relative_to_config(tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "notes").mkdir()
    init_vault(settings / "vault")
    path = settings / "config.toml"
    path.write_text('vault_root="vault"\n[[sources]]\nid="local-notes"\n'
                    'adapter="markdown_vault"\nroot="notes"\n')
    repo = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "-m", "sb.cli", "doctor", "--json"],
        cwd=tmp_path, env={**os.environ, "SB_CONFIG": str(path), "PYTHONPATH": str(repo)},
        text=True, capture_output=True, timeout=20, check=False,
    )
    checks = json.loads(done.stdout)
    source = next(check for check in checks if check["name"] == "source:local-notes")
    assert source["status"] == "pass", source
    assert source["detail"] == str(settings / "notes")
    listed = subprocess.run(
        [sys.executable, "-m", "sb.cli", "sources", "--json"],
        cwd=tmp_path, env={**os.environ, "SB_CONFIG": str(path), "PYTHONPATH": str(repo)},
        text=True, capture_output=True, timeout=20, check=True,
    )
    sources = json.loads(listed.stdout)
    assert sources[0]["root"] == source["detail"]
    assert sources[0]["root_exists"] is True
