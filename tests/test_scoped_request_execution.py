import json
from datetime import datetime
from pathlib import Path

import pytest

from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.request_executor import RequestExecutor
from sb.scoped_request_acceptance import accept_scoped_request
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1
from tests.task30_process_harness import executor_config


def fixture(tmp_path):
    raw = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    now = datetime.fromisoformat(raw["created_at"])
    config = executor_config(tmp_path)
    accepted = accept_scoped_request(config.request_root, raw, expected_provider=config.provider_instance_id,
        clock=lambda: now, validate_authority=lambda _: True)
    return raw, now, config, accepted


def test_internal_v4_execution_proves_and_preserves_scoped_records(tmp_path):
    raw, now, config, accepted = fixture(tmp_path)
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "proved", result
        status = executor.store.get(accepted.request_id)
        proof = json.loads(status.proof_json)
        assert proof["schema_version"] == 4
        assert proof["request_id"] == accepted.request_id
        assert proof["request_digest"] == raw["request_digest"]
        assert proof["scope_digest"] == raw["preparation"]["binding"]["identity_digest"]
        generation = executor.generations.active()
        manifest = json.loads((generation.root / "generation.json").read_text())
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
def test_execution_denies_revoked_authority_or_changed_envelope(tmp_path, tamper):
    _, now, config, accepted = fixture(tmp_path)
    if tamper:
        (config.request_root / accepted.inbox_path).write_bytes(b"{}\n")
    executor = RequestExecutor(config, scoped_authority=lambda _: tamper)
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "failed", result
        assert not executor.generations.active_link.exists()
        assert executor.store.get(accepted.request_id).proof_json is None
    finally:
        executor.close()


def test_expired_request_cannot_start_despite_a_true_authority_callback(tmp_path):
    raw, _, config, accepted = fixture(tmp_path)
    executor = RequestExecutor(config, scoped_authority=lambda _: True)
    try:
        result = executor.apply_once(worker="fixture:worker", now=datetime.fromisoformat(raw["expires_at"]))
        assert result.state == "failed" and result.code == "SCOPED_WRITE_REQUEST_EXPIRED"
        assert not executor.generations.active_link.exists()
        assert executor.store.get(accepted.request_id).proof_json is None
    finally:
        executor.close()


def test_revocation_after_sealing_prevents_activation(tmp_path):
    _, now, config, accepted = fixture(tmp_path)
    authorized = [True]
    class Revoke:
        def reach(self, event):
            if event.barrier_id.value == "sealed_manifest":
                authorized[0] = False
    executor = RequestExecutor(config, scoped_authority=lambda _: authorized[0], barrier_sink=Revoke())
    try:
        result = executor.apply_once(worker="fixture:worker", now=now)
        assert result.state == "failed", result
        assert not authorized[0]
        assert not executor.generations.active_link.exists()
        assert executor.store.get(accepted.request_id).proof_json is None
    finally:
        executor.close()
