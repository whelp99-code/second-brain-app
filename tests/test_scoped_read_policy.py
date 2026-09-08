from __future__ import annotations

import base64
from pathlib import Path

import pytest

from sb.config import load_config
from sb.scoped_read_policy import current_scoped_policy, scoped_policy
from tests.test_access_claims import KEY


def test_fixed_path_refreshes_revocation_and_policy_without_rebinding_session(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    encoded = base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()
    original = f'''jarvis_public_keys = {{ "key:test" = "{encoded}" }}
[mcp_scoped_read]
principal = "principal:owner"
agent = "agent:test"
session = "session:test"
policy_revision = "policy:1"
'''
    path.write_text(original)
    config = load_config(path)
    initial = scoped_policy(config)
    other = tmp_path / "other.toml"
    other.write_text(original.replace("policy:1", "policy:other"))
    monkeypatch.setenv("SB_CONFIG", str(other))
    assert current_scoped_policy(config, initial) == initial
    path.write_text(original.replace("policy:1", "policy:2"))
    assert current_scoped_policy(config, initial).identity[-1] == "policy:2"
    for changed in ['revoked_jarvis_signing_key_ids = ["key:test"]\n' + original,
                    original.replace("session:test", "session:other"),
                    'vault_root = "different"\n' + original, "invalid [", ""]:
        path.write_text(changed)
        with pytest.raises(ValueError):
            current_scoped_policy(config, initial)
    path.unlink()
    with pytest.raises(ValueError):
        current_scoped_policy(config, initial)
    path.write_text(original)
    assert current_scoped_policy(config, initial) == initial
