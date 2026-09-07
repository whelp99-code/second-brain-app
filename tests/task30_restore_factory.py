from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_requests import accept_effect_request
from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.restore import GenerationRestoreSanitizer
from sb.restore_models import (
    RestoreArchiveSource,
    RestoreRequest,
    build_restore_archive_manifest,
)
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = "ExampleAlpha 예시기록"


@dataclass(frozen=True, slots=True)
class RestoreFixture:
    executor: RequestExecutor
    sanitizer: GenerationRestoreSanitizer
    request: RestoreRequest
    active_generation_id: str
    unrelated: bytes


def restore_fixture(tmp_path: Path) -> RestoreFixture:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        request_root=tmp_path / "requests",
        state_root=tmp_path / "state",
        share_root=tmp_path / "share",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40,
        provider_signing_key_id="provider:key",
        provider_signing_key=key,
        jarvis_public_keys={"jarvis:fixture": key.public_key()},
    )
    _ = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    assert executor.apply_once(now=NOW).state == "proved"
    source_generation = executor.generations.active()
    archive = tmp_path / "archive"
    _ = shutil.copytree(source_generation.root / "wiki", archive / "wiki")
    for path in archive.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    unrelated = b"unrelated-restore-record\n"
    unrelated_path = archive / "wiki" / "unrelated.md"
    _ = unrelated_path.write_bytes(unrelated)
    unrelated_path.chmod(0o600)
    source_high_water = executor.store.tombstone_high_water()
    archive_manifest = build_restore_archive_manifest(
        archive,
        RestoreArchiveSource(
            provider_instance_id="provider:fixture",
            source_generation_id=source_generation.generation_id,
            source_generation_manifest_digest=source_generation.manifest.generation_digest,
            source_tombstone_sequence=source_high_water[0],
            source_tombstone_set_root=source_high_water[1],
            created_at=NOW,
        ),
    )
    effect_time = NOW + timedelta(minutes=1)
    forget = effect_request(
        source_generation,
        "forget",
        OLD,
        effect_time,
        source_high_water,
        key,
        "7",
    )
    _ = accept_effect_request(
        config.request_root,
        forget,
        effect_time + timedelta(seconds=1),
        public_keys=config.jarvis_public_keys,
        provider_instance_id=config.provider_instance_id,
    )
    assert executor.apply_once(now=effect_time + timedelta(seconds=1)).state == "proved"
    sequence, set_root = executor.store.tombstone_high_water()
    fence_time = effect_time + timedelta(minutes=1)
    fence = create_read_fence(
        provider_instance_id=config.provider_instance_id,
        purpose="memory_status",
        operation="status",
        sequence=sequence,
        set_root=set_root,
        issued_at=format_instant(fence_time),
        not_before=format_instant(fence_time),
        expires_at=format_instant(fence_time + timedelta(minutes=5)),
        nonce="nonce:" + "f" * 64,
        signing_key_id="jarvis:fixture",
        private_key=key,
    )
    request = RestoreRequest(
        archive=archive,
        archive_manifest=archive_manifest,
        jarvis_fence=fence,
        now=fence_time,
        request_id="restore:fixture",
    )
    return RestoreFixture(
        executor=executor,
        sanitizer=GenerationRestoreSanitizer(
            tmp_path / "restore",
            config.provider_instance_id,
            config.jarvis_public_keys,
        ),
        request=request,
        active_generation_id=executor.generations.active().generation_id,
        unrelated=unrelated,
    )
