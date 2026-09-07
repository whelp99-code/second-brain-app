"""Isolated real provider for the cross-repository memory acceptance probe."""
from __future__ import annotations

import argparse
import base64
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Self, override
from unittest.mock import patch

import anyio

from sb.generations import GenerationStore
from sb.mcp_contract import write_fixture_request
from sb.request_executor import RequestExecutor
from sb.request_store import RequestStore
from sb.stable_requests import accept_stable_v1_request
from tests.task30_process_harness import executor_config

NOW = datetime(2026, 8, 31, 3, 30, tzinfo=UTC)


class _Clock(datetime):
    @classmethod
    @override
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 8, 31, 3, 30, tzinfo=UTC if tz is None else tz)


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("mode", choices=("init", "serve", "apply", "seed"))
    _ = parser.add_argument("root", type=Path)
    values: dict[str, object] = vars(parser.parse_args())
    root = values["root"]
    mode = values["mode"]
    if not isinstance(root, Path) or not isinstance(mode, str):
        raise TypeError("invalid probe arguments")
    marker = root / ".jarvis-memory-probe"
    config = executor_config(root)
    if mode == "init":
        if any(root.iterdir()):
            raise ValueError("probe requires an empty isolated directory")
        root.chmod(0o700)
        _ = marker.write_text("isolated synthetic acceptance data\n")
        public = base64.urlsafe_b64encode(config.jarvis_public_keys["jarvis:fixture"].public_bytes_raw()).rstrip(b"=").decode()
        private = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
        values = {
            "vault_root": str(config.share_root / "vault"),
            "request_root": str(config.request_root), "state_root": str(config.state_root),
            "share_root": str(config.share_root), "export_root": str(config.export_root),
            "backup_root": str(config.backup_root), "provider_instance_id": config.provider_instance_id,
            "provider_release_sha": config.provider_release_sha,
            "provider_signing_key_id": config.provider_signing_key_id,
            "provider_private_key": private, "jarvis_signing_key_id": "jarvis:fixture",
            "jarvis_public_key": public,
        }
        path = root / "config.toml"
        _ = path.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n")
        path.chmod(0o600)
        requests = RequestStore(config.request_root)
        store = GenerationStore(config.state_root, config.share_root,
                                provider_instance_id=config.provider_instance_id,
                                provider_release_sha=config.provider_release_sha, requests=requests)
        try:
            water = requests.tombstone_high_water()
            generation = store.build(request_id="probe-genesis", parent=None,
                                     tombstone_sequence=water[0], tombstone_set_root=water[1],
                                     created_at=NOW, allowed=lambda _path: True, mutate=lambda _root: None)
            store.activate(generation, None, NOW)
        finally:
            store.close()
            requests.close()
        return
    if not marker.is_file():
        raise ValueError("not an isolated probe directory")
    if mode == "seed":
        _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    if mode in {"apply", "seed"}:
        executor = RequestExecutor(config)
        try:
            print(json.dumps(asdict(executor.apply_once(now=NOW))))
        finally:
            executor.close()
        return
    os.environ["SB_CONFIG"] = str(root / "config.toml")
    from sb import mcp
    # Only the test host clock is injected; publication/locks/storage/transport are real.
    with patch.object(mcp, "datetime", _Clock):
        anyio.run(mcp.build_server().run_stdio_async)


if __name__ == "__main__":
    main()
