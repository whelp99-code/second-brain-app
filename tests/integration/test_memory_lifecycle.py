from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.effect_write_requests import accept_effect_request
from sb.mcp_contract import write_fixture_request
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = "ExampleAlpha 예시기록"
CORRECTED = "corrected runtime record"


def test_real_provider_lifecycle_remember_correct_export_forget(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        request_root=tmp_path / "requests", state_root=tmp_path / "state",
        share_root=tmp_path / "share", export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups", provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40, provider_signing_key_id="provider:key",
        provider_signing_key=key, jarvis_public_keys={"jarvis:fixture": key.public_key()},
    )
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    remember = executor.apply_once(now=NOW)
    assert remember.request_id == accepted.request_id and remember.state == "proved"
    remembered_generation = executor.generations.active()
    assert remembered_generation.manifest.file_count == 2
    assert remembered_generation.root.joinpath(".sb", "derived-manifest.json").is_file()

    correction_time = NOW + timedelta(minutes=1)
    correction = effect_request(
        executor.generations.active(), "correct", OLD, correction_time,
        executor.store.tombstone_high_water(), key, "1",
    )
    correction_accepted = accept_effect_request(
        config.request_root, correction, correction_time + timedelta(seconds=1),
        public_keys=config.jarvis_public_keys, provider_instance_id="provider:fixture",
    )
    assert executor.apply_once(now=correction_time + timedelta(seconds=1)).state == "proved"
    active = executor.generations.active()
    active_bytes = b"".join(path.read_bytes() for path in active.root.rglob("*") if path.is_file())
    assert OLD.encode() not in active_bytes and CORRECTED.encode() in active_bytes

    export_time = NOW + timedelta(minutes=2)
    export = effect_request(
        active, "export", CORRECTED, export_time,
        executor.store.tombstone_high_water(), key, "2",
    )
    export_accepted = accept_effect_request(
        config.request_root, export, export_time + timedelta(seconds=1),
        public_keys=config.jarvis_public_keys, provider_instance_id="provider:fixture",
    )
    high = export["tombstone_high_water"]
    assert isinstance(high, dict)
    assert executor.store.tombstone_high_water() == (high["sequence"], high["set_root"])
    export_result = executor.apply_once(now=export_time + timedelta(seconds=1))
    assert export_result.state == "proved", export_result
    assert (config.export_root / export_accepted.request_id / "memory.json").is_file()

    forget_time = NOW + timedelta(minutes=3)
    # Reuse the exact export target identity: target/scope/payload digests are bindings,
    # not globally unique replay aliases across distinct authorized operations.
    forget = effect_request(
        executor.generations.active(), "forget", CORRECTED, export_time,
        executor.store.tombstone_high_water(), key, "3",
    )
    forget_accepted = accept_effect_request(
        config.request_root, forget, forget_time + timedelta(seconds=1),
        public_keys=config.jarvis_public_keys, provider_instance_id="provider:fixture",
    )
    forget_result = executor.apply_once(now=forget_time + timedelta(seconds=1))
    assert forget_result.state == "proved", forget_result
    final_bytes = b"".join(
        path.read_bytes()
        for path in executor.generations.active().root.rglob("*")
        if path.is_file()
    )
    assert OLD.encode() not in final_bytes and CORRECTED.encode() not in final_bytes
    assert not (config.export_root / export_accepted.request_id).exists()
    assert all(
        executor.store.get(request_id) is not None
        for request_id in (
            correction_accepted.request_id,
            export_accepted.request_id,
            forget_accepted.request_id,
        )
    )
    executor.close()
