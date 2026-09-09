"""The read-only estimator counts distinct pages, even with identical content."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sb.config import load_config
from sb.pipeline import run_compile, run_ingest


def test_estimate_counts_pages_then_recognizes_completed_keys(tmp_path):
    root = Path(__file__).resolve().parents[1]
    vault = tmp_path / "share/vault"
    config_path = tmp_path / "config.toml"
    text = f'vault_root = "{vault}"\nshare_root = "{tmp_path / "share"}"\nstate_root = "{tmp_path / "state"}"\nknowledge_registry = "{tmp_path / "registry.db"}"\n'
    for name in ("a", "b"):
        source = tmp_path / name
        source.mkdir()
        (source / "same.md").write_text("동일 문서 내용")
        text += f'[[sources]]\nid = "{name}"\nadapter = "markdown-vault"\nroot = "{source}"\n'
    config_path.write_text(text)
    config = load_config(config_path)
    assert run_ingest(config, ["a", "b"]).exit_code == 0

    def estimate():
        database = vault / ".sb/ledger.db"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        result = subprocess.check_output(
            [
                sys.executable,
                str(root / "deploy/estimate-compile-key-upgrade.py"),
                str(config_path),
            ],
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": str(root)},
            text=True,
            timeout=30,
        )
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before
        return json.loads(result)

    first = estimate()
    assert first["page_groups"] == first["eligible_page_calls"] == 2
    assert first["distinct_legacy_keys"] == 1
    assert first["model_calls_made"] == 0
    assert run_compile(config, llm_mode="fake").exit_code == 0
    second = estimate()
    assert second["eligible_page_calls"] == 0
    assert second["new_key_states"]["done"] == 2
