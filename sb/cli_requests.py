"""Stable provider request-executor CLI boundary."""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import asdict
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.config import Config
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.scoped_provider_runtime import configured_scoped_provider_authority
from sb.task30_barriers import UnixBarrierSink


def apply_requests_once(config: Config, control_path: str | None) -> int:
    """Apply at most one stable request with an optional acknowledged test barrier."""
    configured_jarvis_keys = config.jarvis_public_keys
    if (
        not configured_jarvis_keys
        or config.provider_signing_key_id is None
        or config.provider_private_key is None
    ):
        print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
        return 1
    try:
        jarvis_keys = {
            key_id: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(encoded + "=="))
            for key_id, encoded in configured_jarvis_keys.items()
            if key_id not in config.revoked_jarvis_signing_key_ids
        }
        external_keys = {
            key_id: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(encoded + "=="))
            for key_id, encoded in config.external_erasure_public_keys.items()
        }
        provider_key = Ed25519PrivateKey.from_private_bytes(
            base64.urlsafe_b64decode(config.provider_private_key + "==")
        )
    except ValueError:
        print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
        return 1
    if not jarvis_keys:
        print("REQUEST_EXECUTOR_KEY_CONFIG_INVALID", file=sys.stderr)
        return 1
    try:
        scoped_authority = configured_scoped_provider_authority(config)
    except ValueError:
        print("SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID", file=sys.stderr)
        return 1
    barrier_sink = None if control_path is None else UnixBarrierSink(Path(control_path))
    if barrier_sink is not None:
        barrier_sink.await_trigger("apply-requests")
    executor = RequestExecutor(
        ExecutorConfig(
            request_root=Path(config.request_root),
            state_root=Path(config.state_root),
            share_root=Path(config.share_root),
            export_root=Path(config.export_root),
            backup_root=Path(config.backup_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
            provider_signing_key_id=config.provider_signing_key_id,
            provider_signing_key=provider_key,
            jarvis_public_keys=jarvis_keys,
            external_public_keys=external_keys,
            legacy_request_roots=tuple(Path(root) for root in config.legacy_request_roots),
            search_hybrid=config.search_hybrid,
        ),
        barrier_sink=barrier_sink,
        scoped_authority=scoped_authority,
    )
    try:
        result = executor.apply_once()
    finally:
        executor.close()
        if barrier_sink is not None:
            barrier_sink.close()
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0 if result.state in {"idle", "proved", "reconciling"} else 1
