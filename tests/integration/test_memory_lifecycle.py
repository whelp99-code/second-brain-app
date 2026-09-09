from __future__ import annotations

import base64
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.client import Client
from pydantic import BaseModel, ConfigDict
from pytest import MonkeyPatch

from sb.delegations import create_read_fence
from sb.effect_values import JsonObject, digest, format_instant, is_json_object, strict_loads
from sb.effect_write_requests import accept_effect_request
from sb.effect_write_values import model_object
from sb.mcp import build_server
from sb.mcp_contract import write_fixture_request
from sb.pipeline import audit_citations
from sb.provider_observation_models import ProviderLifecycleObservationsV1
from sb.request_executor import ExecutorConfig, RequestExecutor
from sb.search import git_run
from sb.stable_requests import accept_stable_v1_request
from tests.task30_effect_factory import effect_request
from tests.test_generation_vectors import CountingEncoder

NOW = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
OLD = "ExampleAlpha 예시기록"
CORRECTED = "corrected runtime record"


class _StatusEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: JsonObject


@pytest.mark.parametrize("hybrid", [False, True])
@pytest.mark.parametrize("bound,binding_failure", [(False, False), (True, False), (True, True)])
def test_real_provider_lifecycle_remember_correct_export_forget(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    hybrid: bool,
    bound: bool,
    binding_failure: bool,
) -> None:
    from sb.bound_knowledge import BoundKnowledge
    from sb.knowledge_registry import KnowledgeRegistry
    from sb.remember_page import materialize_remember
    from sb.search import SearchIndex
    from sb.store.ledger import Ledger

    if bound:
        def materialize_bound(root, **kwargs):
            materialize_remember(root, **kwargs)
            # Seed the same explicit state as compilation before the real seal.
            with Ledger(root) as ledger:
                for page in (root / 'wiki').glob('*.md'):
                    ledger.bind_knowledge(BoundKnowledge(page.relative_to(root).as_posix().removesuffix('.md'),
                        'sha256:' + hashlib.sha256(page.read_bytes()).hexdigest(), 'ACTIVE', 'APPROVED'))
        monkeypatch.setattr('sb.request_executor.materialize_remember', materialize_bound)
    monkeypatch.setattr("sb.embeddings.resolve_encoder", CountingEncoder)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    config = ExecutorConfig(
        request_root=tmp_path / "requests", state_root=tmp_path / "state",
        share_root=tmp_path / "share", export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups", provider_instance_id="provider:fixture",
        provider_release_sha="a" * 40, provider_signing_key_id="provider:key",
        provider_signing_key=key, jarvis_public_keys={"jarvis:fixture": key.public_key()},
        search_hybrid=hybrid,
    )
    accepted = accept_stable_v1_request(config.request_root, write_fixture_request(), NOW)
    executor = RequestExecutor(config)
    remember = executor.apply_once(now=NOW)
    assert remember.request_id == accepted.request_id and remember.state == "proved"
    remembered_generation = executor.generations.active()
    registry = KnowledgeRegistry(tmp_path / 'knowledge.sqlite')
    if bound:
        index = SearchIndex(remembered_generation.root, hybrid=hybrid, registry_path=registry.path)
        hits = index.search(OLD, scope='active')
        assert len(hits) == 1 and hits[0].verification == 'VERIFIED'
        _ = registry.put(hits[0].page_id, knowledge_status='ACTIVE', approval_status='APPROVED')
    # The request memory carries its original CAS blob in addition to the page
    # and derived manifest, so citation validation also survives restoration.
    assert remembered_generation.manifest.file_count == 4
    assert remembered_generation.root.joinpath("log.md").is_file()
    assert git_run(remembered_generation.root, "ls-files", "raw") == ""
    assert remembered_generation.root.joinpath(".sb", "derived-manifest.json").is_file()
    if hybrid:
        with closing(sqlite3.connect(remembered_generation.root / ".sb/vectors.db")) as vectors:
            assert vectors.execute("SELECT enabled,row_count FROM generation_meta").fetchone() == (1, 1)
            assert vectors.execute("SELECT text FROM record_vectors").fetchone() == (OLD,)

    correction_time = NOW + timedelta(minutes=1)
    correction = effect_request(
        executor.generations.active(), "correct", OLD, correction_time,
        executor.store.tombstone_high_water(), key, "1",
    )
    correction_accepted = accept_effect_request(
        config.request_root, correction, correction_time + timedelta(seconds=1),
        public_keys=config.jarvis_public_keys, provider_instance_id="provider:fixture",
    )
    if binding_failure:
        def fail_binding(_ledger, _state):
            raise RuntimeError('INJECTED_CORRECTION_STATE_FAILURE')
        with monkeypatch.context() as failing:
            failing.setattr(Ledger, 'bind_knowledge', fail_binding)
            failed = executor.apply_once(now=correction_time + timedelta(seconds=1), lease_ms=1)
        assert failed.state == 'reconciling' and failed.code == 'EFFECT_KNOWLEDGE_REBIND_FAILED'
        assert executor.generations.active().generation_id == remembered_generation.generation_id
        high_water = executor.store.tombstone_high_water()
        assert high_water[0] > 0
        executor.close()
        executor = RequestExecutor(config)
        correction_result = executor.apply_once(now=correction_time + timedelta(seconds=1, microseconds=2000), lease_ms=1)
        assert executor.store.tombstone_high_water() == high_water
    else:
        correction_result = executor.apply_once(now=correction_time + timedelta(seconds=1))
    assert correction_result.state == "proved", correction_result
    assert audit_citations(executor.generations.active().root) == ()
    correction_observations = executor.store.observations(correction_accepted.request_id)
    assert correction_observations is not None
    provider_inventory = correction_observations.surface_manifest.provider_inventory
    assert provider_inventory.observed_surface_count == 40
    assert any(entry.file_count > 0 for entry in provider_inventory.entries)
    assert next(
        entry for entry in provider_inventory.entries if entry.surface_id == "git_objects"
    ).object_count > 0
    assert next(
        entry for entry in provider_inventory.entries if entry.surface_id == "request_journal"
    ).row_count > 0
    guards = correction_observations.surface_manifest.reingress_guards
    assert guards.observed_guard_count == 10
    assert all(entry.executed and entry.blocked for entry in guards.entries)
    assert correction_observations.artifact is not None
    assert correction_observations.artifact.match_count == 1
    assert correction_observations.absence is not None
    assert correction_observations.absence.match_count == 0
    correction_status = executor.store.get(correction_accepted.request_id)
    assert correction_status is not None and correction_status.proof_json is not None
    proof = strict_loads(correction_status.proof_json, 262_144)
    assert is_json_object(proof)
    assert proof["surface_manifest_digest"] == correction_observations.surface_manifest.manifest_digest
    assert proof["artifact_manifest_digest"] == correction_observations.artifact.manifest_digest
    serialized = correction_observations.model_dump_json()
    assert str(tmp_path) not in serialized and OLD not in serialized and CORRECTED not in serialized
    active = executor.generations.active()
    active_bytes = b"".join(path.read_bytes() for path in active.root.rglob("*") if path.is_file())
    assert OLD.encode() not in active_bytes and CORRECTED.encode() in active_bytes
    assert sum(page.read_text().count(CORRECTED) for page in active.root.joinpath("wiki").glob("*.md")) == 1
    if hybrid:
        with closing(sqlite3.connect(active.root / ".sb/vectors.db")) as vectors:
            assert vectors.execute("SELECT text FROM record_vectors").fetchall() == [(CORRECTED,)]

    if bound:
        index = SearchIndex(active.root, hybrid=hybrid, registry_path=registry.path)
        assert tuple(index.iter_lexical_hits(OLD, scope='reference')) == ()
        assert all(OLD not in hit.snippet for hit in index.search(OLD, scope='reference'))
        hits = index.search(CORRECTED, scope='active')
        assert len(hits) == 1 and hits[0].verification == 'VERIFIED'
    else:
        index = SearchIndex(active.root, hybrid=hybrid, registry_path=registry.path)
        assert index.search(CORRECTED, scope='active') == ()
        assert index.search(CORRECTED, scope='reference')[0].verification == 'UNVERIFIED'

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
    export_file = config.export_root / export_accepted.request_id / "memory.json"
    assert export_file.is_file()
    export_observations = executor.store.observations(export_accepted.request_id)
    assert export_observations is not None and export_observations.export is not None
    assert export_observations.export.file_count == 1
    assert export_observations.export.byte_count == export_file.stat().st_size
    assert export_observations.export.byte_count > 1
    export_status = executor.store.get(export_accepted.request_id)
    assert export_status is not None and export_status.proof_json is not None
    export_proof = strict_loads(export_status.proof_json, 262_144)
    assert is_json_object(export_proof)
    assert export_proof["export_manifest_digest"] == export_observations.export.manifest_digest
    retained_manifest = export_observations.export.manifest
    retained_body = model_object(retained_manifest)
    del retained_body["manifest_id"], retained_body["manifest_digest"]
    assert digest("export", retained_body) == export_proof["export_manifest_digest"]
    assert len(retained_manifest.files) == export_observations.export.file_count
    assert sum(entry.bytes for entry in retained_manifest.files) == export_observations.export.byte_count
    assert retained_manifest.record_count == export_observations.export.record_count
    export_wire = export_observations.model_dump_json()
    assert str(tmp_path) not in export_wire and CORRECTED not in export_wire

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
    assert audit_citations(executor.generations.active().root) == ()
    final_bytes = b"".join(
        path.read_bytes()
        for path in executor.generations.active().root.rglob("*")
        if path.is_file()
    )
    assert OLD.encode() not in final_bytes and CORRECTED.encode() not in final_bytes
    if bound:
        index = SearchIndex(executor.generations.active().root, hybrid=hybrid, registry_path=registry.path)
        assert index.search(CORRECTED, scope='reference') == ()
        assert index.search(CORRECTED, scope='active') == ()
    if hybrid:
        with closing(sqlite3.connect(executor.generations.active().root / ".sb/vectors.db")) as vectors:
            assert vectors.execute("SELECT count(*) FROM record_vectors").fetchone() == (0,)
    assert not (config.export_root / export_accepted.request_id).exists()
    assert all(
        executor.store.get(request_id) is not None
        for request_id in (
            correction_accepted.request_id,
            export_accepted.request_id,
            forget_accepted.request_id,
        )
    )

    public_key = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).rstrip(b"=").decode()
    config_path = tmp_path / "config.toml"
    _ = config_path.write_text("\n".join((
        f'vault_root = "{config.share_root / "vault"}"',
        f'request_root = "{config.request_root}"',
        f'state_root = "{config.state_root}"',
        f'share_root = "{config.share_root}"',
        f'export_root = "{config.export_root}"',
        f'backup_root = "{config.backup_root}"',
        'provider_instance_id = "provider:fixture"',
        f'provider_release_sha = "{"a" * 40}"',
        'jarvis_signing_key_id = "jarvis:fixture"',
        f'jarvis_public_key = "{public_key}"',
    )) + "\n", encoding="utf-8")
    monkeypatch.setenv("SB_CONFIG", str(config_path))
    sequence, set_root = executor.store.tombstone_high_water()
    observed_at = datetime.now(UTC)
    fence = create_read_fence(
        provider_instance_id="provider:fixture", purpose="memory_status", operation="status",
        sequence=sequence, set_root=set_root, issued_at=format_instant(observed_at),
        not_before=format_instant(observed_at),
        expires_at=format_instant(observed_at + timedelta(minutes=1)), nonce="status-observation",
        signing_key_id="jarvis:fixture", private_key=key,
    )

    async def request_status(request_id: str) -> str:
        async with Client(build_server(), mode="legacy", cache=None) as client:
            result = await client.call_tool("sb_request_status", {
                "request_id": request_id,
                "read_fence": model_object(fence),
            })
        return result.model_dump_json()

    status_envelope = _StatusEnvelope.model_validate_json(
        anyio.run(request_status, forget_accepted.request_id)
    )
    wire_observations = ProviderLifecycleObservationsV1.model_validate(
        status_envelope.structured_content.get("observations")
    )
    stored_observations = executor.store.observations(forget_accepted.request_id)
    assert stored_observations == wire_observations
    export_envelope = _StatusEnvelope.model_validate_json(
        anyio.run(request_status, export_accepted.request_id)
    )
    wire_export = ProviderLifecycleObservationsV1.model_validate(
        export_envelope.structured_content.get("observations")
    ).export
    assert wire_export is not None and wire_export.manifest == retained_manifest
    executor.close()
