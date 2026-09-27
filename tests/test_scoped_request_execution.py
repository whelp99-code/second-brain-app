from datetime import datetime
from pathlib import Path

import pytest

from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.request_executor import RequestExecutor
from sb.scoped_request_acceptance import accept_scoped_request
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1
from sb.task30_barriers import BarrierEvent
from tests.json_fixtures import parse_object
from tests.task30_process_harness import executor_config


def fixture(tmp_path: Path):
    raw = parse_object((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    created_at = raw["created_at"]
    assert isinstance(created_at, str)
    now = datetime.fromisoformat(created_at)
    config = executor_config(tmp_path)
    accepted = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
        clock=lambda: now, validate_authority=lambda _: True)
    return raw, now, config, accepted


def test_internal_v4_execution_proves_and_preserves_scoped_records(tmp_path: Path):
    raw, now, config, accepted = fixture(tmp_path)
    expires_at = raw["expires_at"]
    assert isinstance(expires_at, str)
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "proved", result
        status = executor.store.get(accepted.request_id)
        assert status is not None
        assert status.proof_json is not None
        proof = parse_object(status.proof_json)
        assert proof["schema_version"] == 4
        assert proof["request_id"] == accepted.request_id
        assert proof["request_digest"] == raw["request_digest"]
        preparation = raw["preparation"]
        assert isinstance(preparation, dict)
        binding = preparation["binding"]
        assert isinstance(binding, dict)
        assert proof["scope_digest"] == binding["identity_digest"]
        generation = executor.generations.active()
        manifest = parse_object((generation.root / "generation.json").read_text())
        identity = GenerationIdentityV1(*(str(manifest[k]) for k in (
            "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
        page_id = next((generation.root / "wiki").glob("*.md")).stem
        page = classified_page(generation.root, page_id, identity)
        assert len(page.records) == 4
        require_scope(page, SourceAccess("principal:owner", ("project:shared-memory",), "policy:fixture"))
        with pytest.raises(MemoryAccessError):
            require_scope(page, SourceAccess("principal:owner", ("project:other",), "policy:fixture"))
        assert executor.apply_once(worker="fixture:worker", now=now).state == "idle"
        assert not list((config.request_root / "pending").glob("*.json"))
        assert not list((config.request_root / "processing").glob("*.json"))
    finally:
        executor.close()


@pytest.mark.parametrize("tamper", [False, True])
def test_execution_denies_revoked_authority_or_changed_envelope(tmp_path: Path, tamper: bool):
    _, now, config, accepted = fixture(tmp_path)
    if tamper:
        _ = (config.request_root / accepted.inbox_path).write_bytes(b"{}\n")
    executor = RequestExecutor(config, scoped_authority=lambda _: tamper)
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "failed", result
        assert not executor.generations.active_link.exists()
        status = executor.store.get(accepted.request_id)
        assert status is not None
        assert status.proof_json is None
    finally:
        executor.close()


def test_expired_request_cannot_start_despite_a_true_authority_callback(tmp_path: Path):
    raw, _, config, accepted = fixture(tmp_path)
    expires_at = raw["expires_at"]
    assert isinstance(expires_at, str)
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    try:
        result = executor.apply_once(worker="fixture:worker", now=datetime.fromisoformat(expires_at))
        assert result.state == "failed" and result.code == "SCOPED_WRITE_REQUEST_EXPIRED"
        assert not executor.generations.active_link.exists()
        status = executor.store.get(accepted.request_id)
        assert status is not None
        assert status.proof_json is None
    finally:
        executor.close()


def test_revocation_after_sealing_prevents_activation(tmp_path: Path):
    _, now, config, accepted = fixture(tmp_path)
    authorized = [True]
    class Revoke:
        def reach(self, event: BarrierEvent) -> None:
            if event.barrier_id.value == "sealed_manifest":
                authorized[0] = False
    executor = RequestExecutor(config, scoped_authority=lambda _: authorized[0], barrier_sink=Revoke())
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "failed", result
        assert not authorized[0]
        assert not executor.generations.active_link.exists()
        status = executor.store.get(accepted.request_id)
        assert status is not None
        assert status.proof_json is None
    finally:
        executor.close()


@pytest.mark.parametrize("barrier", ["sealed_manifest", "pointer_parent_fsync"])
@pytest.mark.parametrize("reason", ["expired", "revoked"])
def test_crash_recovery_distinguishes_applied_result_from_new_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, barrier: str, reason: str):
    import subprocess
    import sys
    from datetime import timedelta

    raw, now, config, accepted = fixture(tmp_path)
    expires_at = raw["expires_at"]
    assert isinstance(expires_at, str)
    child = '''
import os, sys
from datetime import datetime
from pathlib import Path
from sb.request_executor import RequestExecutor
from tests.task30_process_harness import executor_config
class Stop:
    def reach(self, event):
        if event.barrier_id.value == sys.argv[3]:
            os._exit(73)
executor = RequestExecutor(executor_config(Path(sys.argv[1])),
    scoped_authority=lambda _: True, barrier_sink=Stop())
executor.apply_once(worker="fixture:crash", now=datetime.fromisoformat(sys.argv[2]), lease_ms=1000)
'''
    process = subprocess.run([sys.executable, "-c", child, str(tmp_path), now.isoformat(), barrier],
        timeout=40, check=False)
    assert process.returncode == 73
    later = datetime.fromisoformat(expires_at) if reason == "expired" else now + timedelta(seconds=2)
    executor = RequestExecutor(config, scoped_authority=lambda _: reason != "revoked")
    def no_new_materialization(
        _root: Path, *, content: str, candidate_id: str, created_at: str, release_sha: str,
        sensitivity: str = "personal", source_access: SourceAccess | None = None,
    ) -> None:
        del content, candidate_id, created_at, release_sha, sensitivity, source_access
        pytest.fail("Recovery must never materialize a new memory")
    monkeypatch.setattr("sb.request_executor.materialize_remember", no_new_materialization)
    try:
        applied = barrier == "pointer_parent_fsync"
        before = executor.store.get(accepted.request_id)
        assert before is not None
        generation_id = executor.generations.active().generation_id if applied else None
        generations = set(executor.generations.generations.iterdir())
        result = executor.apply_once(worker="fixture:resume", now=later)
        if applied:
            assert before.phase == "switch_intent"
            assert before.result_generation_id == generation_id
            assert result.state == "proved", result
            status = executor.store.get(accepted.request_id)
            assert status is not None
            assert status.proof_json is not None
            proof = parse_object(status.proof_json)
            assert proof["generation_id"] == generation_id
            assert proof["request_id"] == raw["request_id"]
            preparation = raw["preparation"]
            assert isinstance(preparation, dict)
            binding = preparation["binding"]
            assert isinstance(binding, dict)
            assert proof["scope_digest"] == binding["identity_digest"]
            assert executor.generations.active().generation_id == generation_id
            assert set(executor.generations.generations.iterdir()) == generations
            assert executor.apply_once(worker="fixture:replay", now=later).state == "idle"
        else:
            assert result.state == "failed", result
            expected = "SCOPED_WRITE_REQUEST_EXPIRED" if reason == "expired" else "SCOPED_WRITE_AUTHORITY_INVALID"
            assert result.code == expected
            assert not executor.generations.active_link.exists()
            status = executor.store.get(accepted.request_id)
            assert status is not None
            assert status.proof_json is None
    finally:
        executor.close()
