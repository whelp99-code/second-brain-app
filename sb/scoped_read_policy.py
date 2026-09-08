"""Per-request scoped MCP policy snapshots from the fixed startup config path."""
from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.config import Config, load_config
from sb.source_access import SourceAccess


@dataclass(frozen=True, slots=True)
class ScopedReadPolicy:
    identity: tuple[str, str, str, str]
    encoded_keys: tuple[tuple[str, str], ...]
    routing: tuple[str, str, str, str, str]

    def public_keys(self) -> dict[str, Ed25519PublicKey]:
        return {name: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(value + "=="))
                for name, value in self.encoded_keys}


def scoped_policy(config: Config) -> ScopedReadPolicy:
    raw = config.raw.get("mcp_scoped_read")
    if not isinstance(raw, dict) or set(raw) != {"principal", "agent", "session", "policy_revision"}:
        raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")
    if any(not isinstance(value, str) or not value for value in raw.values()):
        raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")
    identity = (str(raw["principal"]), str(raw["agent"]), str(raw["session"]), str(raw["policy_revision"]))
    _ = SourceAccess(identity[0], (), identity[3])
    keys = tuple(sorted((name, value) for name, value in config.jarvis_public_keys.items()
                        if name not in config.revoked_jarvis_signing_key_ids))
    if not keys:
        raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")
    result = ScopedReadPolicy(identity, keys, (config.provider_instance_id, config.vault_root, config.state_root, config.share_root, config.request_root))
    _ = result.public_keys()
    return result


def current_scoped_policy(startup: Config, initial: ScopedReadPolicy) -> ScopedReadPolicy:
    """Topology or session changes require a new connection; revocations do not.

    In-memory Config callers may supply a changed raw mapping. File-backed servers
    re-read only their fixed startup path, never a fresh environment search path.
    Missing or malformed configuration cannot fall back to legacy access.
    """
    current = startup if startup.source_path is None else load_config(startup.source_path)
    if (current.provider_instance_id, current.vault_root, current.state_root, current.share_root, current.request_root) != initial.routing:
        raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")
    policy = scoped_policy(current)
    if policy.identity[:3] != initial.identity[:3]:
        raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")
    return policy
