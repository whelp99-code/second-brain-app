from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.config import load_config
from sb.scoped_read_policy import current_scoped_policy, scoped_policy
from tests.test_access_claims import KEY


def test_fixed_path_refreshes_revocation_and_policy_without_rebinding_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.toml"
    encoded = base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()
    original = f'''state_root = "{tmp_path / "state"}"
jarvis_public_keys = {{ "key:test" = "{encoded}" }}
[mcp_scoped_read]
principal = "principal:owner"
agent = "agent:test"
session = "session:test"
policy_revision = "policy:1"
'''
    _ = path.write_text(original)
    config = load_config(path)
    initial = scoped_policy(config)
    other = tmp_path / "other.toml"
    _ = other.write_text(original.replace("policy:1", "policy:other"))
    monkeypatch.setenv("SB_CONFIG", str(other))
    assert current_scoped_policy(config, initial) == initial
    delegated = original.replace('session = "session:test"', 'session_mode = "issuer_authenticated"')
    _ = path.write_text(delegated)
    with pytest.raises(ValueError):
        _ = current_scoped_policy(config, initial)
    dynamic = scoped_policy(load_config(path))
    assert dynamic.identity[2] is None
    for bad in [delegated + 'session = "session:test"\n', delegated.replace('issuer_authenticated', 'any')]:
        _ = path.write_text(bad)
        with pytest.raises(ValueError):
            _ = scoped_policy(load_config(path))
    _ = path.write_text(original)
    _ = path.write_text(original.replace("policy:1", "policy:2"))
    assert current_scoped_policy(config, initial).identity[-1] == "policy:2"
    for changed in ['revoked_jarvis_signing_key_ids = ["key:test"]\n' + original,
                    original.replace("session:test", "session:other"),
                    'vault_root = "different"\n' + original, "invalid [", ""]:
        _ = path.write_text(changed)
        with pytest.raises(ValueError):
            _ = current_scoped_policy(config, initial)
    path.unlink()
    with pytest.raises(ValueError):
        _ = current_scoped_policy(config, initial)
    _ = path.write_text(original)
    with pytest.raises(ValueError, match="MEMORY_SCOPED_CONFIG_INVALID"):
        _ = current_scoped_policy(config, initial)
    other = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    other_encoded = base64.urlsafe_b64encode(other.public_key().public_bytes_raw()).rstrip(b"=").decode()
    _ = path.write_text(original.replace(
        f'"key:test" = "{encoded}"',
        f'"key:test" = "{encoded}", "key:next" = "{other_encoded}"',
    ))
    recovered = current_scoped_policy(config, initial)
    assert "key:test" not in recovered.public_keys()
    assert "key:next" in recovered.public_keys()
