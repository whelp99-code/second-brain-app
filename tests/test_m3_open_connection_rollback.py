"""H1: live scoped MCP connections deny after revoke; old config cannot revive keys."""
from __future__ import annotations

import base64
import importlib.util
import os
import sys
from pathlib import Path

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import StdioServerParameters
from mcp.client import Client

from sb.access_claims import access_request_digest
from sb.config import load_config
from sb.delegations import create_read_fence
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_values import GENESIS_TOMBSTONE_ROOT, model_object
from sb.revoked_keys import record_revoked_key_ids
from sb.scoped_read_policy import scoped_policy
from tests.test_access_claims import KEY, signed
from tests.test_memory_access import classified  # noqa: F401
from tests.test_rollback_compat import SCRIPT, _fake_release, _run

NEXT_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))


def _signed_with(body: JsonObject, key: Ed25519PrivateKey) -> JsonObject:
    value = {name: item for name, item in body.items() if name != "signature"}
    value["signature"] = base64.urlsafe_b64encode(key.sign(
        b"orca-jarvis/memory-access-claim/v1\0" + canonical_bytes(value),
    )).rstrip(b"=").decode()
    return value


def _b64(key: Ed25519PrivateKey) -> str:
    return base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()


def _write_config(path: Path, *, vault: Path, share: Path, state: Path, provider: str, keys: str) -> None:
    path.write_text(
        f'vault_root = "{vault}"\n'
        f'share_root = "{share}"\n'
        f'state_root = "{state}"\n'
        f'request_root = "{path.parent / "requests"}"\n'
        f'provider_instance_id = "{provider}"\n'
        f"jarvis_public_keys = {{ {keys} }}\n"
        "[mcp_scoped_read]\n"
        'principal = "principal:owner"\n'
        'agent = "agent:test"\n'
        'session = "session:test"\n'
        'policy_revision = "1"\n',
        encoding="utf-8",
    )


def _claim_args(generation, page_id: str, *, key_id: str, key: Ed25519PrivateKey) -> dict[str, object]:
    fence = create_read_fence(
        provider_instance_id=generation.provider_instance_id, purpose="memory_read",
        operation="read", sequence=0, set_root=GENESIS_TOMBSTONE_ROOT,
        issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
        expires_at="2026-09-09T00:01:00.000Z", nonce=f"nonce:{key_id}",
        signing_key_id=key_id, private_key=key,
    )
    body: JsonObject = {
        "schema_version": 1, "provider_instance_id": generation.provider_instance_id,
        "principal_id": "principal:owner", "agent_id": "agent:test", "session_id": "session:test",
        "projects": ["project:a"], "policy_revision": "1", "purpose": "memory_read",
        "request_digest": access_request_digest("sb_read_page", {"id": page_id}),
        "read_fence_digest": fence.fence_digest, "issued_at": "2026-09-09T00:00:00.000Z",
        "expires_at": "2026-09-09T00:00:30.000Z", "nonce": f"nonce:claim:{key_id}",
        "signing_key_id": key_id,
    }
    claim = signed(body) if key is KEY else _signed_with(body, key)
    return {"id": page_id, "read_fence": model_object(fence), "access_claim": claim}


def test_two_stdio_sessions_deny_after_revoke(classified, tmp_path: Path) -> None:  # noqa: F811
    root, name, generation = classified
    work = root.parents[2]
    config_path = tmp_path / "config.toml"
    keys = f'"key:test" = "{_b64(KEY)}", "key:next" = "{_b64(NEXT_KEY)}"'
    _write_config(
        config_path, vault=work / "share" / "vault", share=work / "share",
        state=work / "state", provider=generation.provider_instance_id, keys=keys,
    )
    program = (
        "from datetime import UTC, datetime\n"
        "import sb.mcp as mcp\n"
        "class Frozen(datetime):\n"
        "    @classmethod\n"
        "    def now(cls, tz=None):\n"
        "        return datetime(2026, 9, 9, tzinfo=UTC)\n"
        "mcp.datetime = Frozen\n"
        "mcp.build_server().run()\n"
    )
    env = {
        **os.environ,
        "SB_CONFIG": str(config_path),
        "SB_MCP_CONTRACT_PROFILE": "scoped-record-read-v1",
        "PYTHONPATH": os.pathsep.join(sys.path),
    }
    params = StdioServerParameters(command=sys.executable, args=["-c", program], env=env)
    old = _claim_args(generation, name, key_id="key:test", key=KEY)

    async def run() -> None:
        async with (
            Client(params, mode="legacy", cache=None) as first,
            Client(params, mode="legacy", cache=None) as second,
        ):
                for client in (first, second):
                    allowed = await client.call_tool("sb_read_page", old)
                    assert not allowed.is_error, allowed
                record_revoked_key_ids(work / "state", ["key:test"])
                text = config_path.read_text(encoding="utf-8")
                config_path.write_text(
                    'revoked_jarvis_signing_key_ids = ["key:test"]\n' + text, encoding="utf-8",
                )
                for client in (first, second):
                    denied = await client.call_tool("sb_read_page", old)
                    assert denied.is_error
                    assert "Alpha fixture" not in str(denied)
                    assert "MEMORY_SCOPED_READ_DENIED" in str(denied) or denied.is_error
                recovered = _claim_args(generation, name, key_id="key:next", key=NEXT_KEY)
                ok = await first.call_tool("sb_read_page", recovered)
                assert not ok.is_error, ok

    anyio.run(run)


def test_old_config_cannot_revive_revoked_signing_key(classified, tmp_path: Path) -> None:  # noqa: F811
    root, _name, generation = classified
    work = root.parents[2]
    state = work / "state"
    record_revoked_key_ids(state, ["key:test"])
    dest = tmp_path / "restored"
    dest.mkdir()
    old_config = dest / "config.toml"
    _write_config(
        old_config, vault=work / "share" / "vault", share=work / "share",
        state=state, provider=generation.provider_instance_id,
        keys=f'"key:test" = "{_b64(KEY)}"',
    )
    with pytest.raises(ValueError, match="MEMORY_SCOPED_CONFIG_INVALID"):
        scoped_policy(load_config(old_config))
    recovered = dest / "recovered.toml"
    _write_config(
        recovered, vault=work / "share" / "vault", share=work / "share",
        state=state, provider=generation.provider_instance_id,
        keys=f'"key:test" = "{_b64(KEY)}", "key:next" = "{_b64(NEXT_KEY)}"',
    )
    policy = scoped_policy(load_config(recovered))
    assert "key:test" not in policy.public_keys()
    assert "key:next" in policy.public_keys()


def test_rollback_compat_allowed_false_when_store_present(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("check_rollback_compat", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = tmp_path / "state"
    state.mkdir()
    (state / "revoked-jarvis-signing-key-ids").write_text("key:old\n", encoding="utf-8")
    old = _fake_release(tmp_path / "old", reads=False)
    payload = module.check_rollback(state, old)
    assert payload["allowed"] is False
    assert payload["reason"] == "ROLLBACK_UNSAFE_REVOCATION_STORE"
    done = _run(state, old)
    assert done.returncode == 2
