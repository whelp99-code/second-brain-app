from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from sb.cancellation_absence import record_cancellation_absence
from sb.cancellation_result import (
    CancellationResultError,
    sign_cancellation_result,
    verify_cancellation_result,
)
from sb.cancellation_result_issuer import CancellationEvidenceError, CancellationResultIssuer
from sb.correction_cancellation_executor import apply_correction_cancellation
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, strict_loads
from sb.effect_write_values import model_object
from sb.erasure import ErasureEngine
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.request_executor import RequestExecutor
from tests.json_fixtures import parse_object
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import prepare
from tests.test_managed_copy_disposal import prepare_copies
from tests.test_request_executor import NOW
from tests.test_request_executor import config as _config

type CompleteCallback = Callable[[CancellationResultIssuer, CorrectionCancellationIntentV1, str, str], JsonObject]


def issue(executor: RequestExecutor, identity: str, callback: CompleteCallback | None = None) -> JsonObject:
    config=executor.config
    issuer=CancellationResultIssuer(executor.store,executor.generations,executor.reingress,executor.exports,
        config.backup_root,config.provider_release_sha,config.provider_signing_key_id,config.provider_signing_key,
        NOW+timedelta(hours=1))
    def complete(intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
        return issuer.complete(intent, generation_id, generation_digest) if callback is None else callback(issuer, intent, generation_id, generation_digest)

    return apply_correction_cancellation(executor.mutations,executor.erasure,identity,now=issuer.now,
        backup_root=config.backup_root,historical_delegation_keys=config.jarvis_public_keys,
        current_cancellation_keys={'jarvis:current':CURRENT.public_key()},
        complete=complete)


def intent_for(executor: RequestExecutor, identity: str) -> CorrectionCancellationIntentV1:
    raw=TypeAdapter(str).validate_python(executor.store.db.execute('SELECT intent_json FROM correction_cancellations WHERE intent_id=?',(identity,)).fetchone()[0], strict=True)
    return CorrectionCancellationIntentV1.model_validate(strict_loads(raw,16_384))


def test_result_has_actual_evidence_and_survives_response_loss_and_later_generation(tmp_path: Path):
    executor,identity,_archive,_export=prepare_copies(tmp_path,'cancel')
    def lost(issuer: CancellationResultIssuer, intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
        _ = issuer.complete(intent, generation_id, generation_digest)
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _ = issue(executor,identity,lost)
    saved=TypeAdapter(str).validate_python(executor.store.db.execute('SELECT result_json FROM correction_cancellation_results').fetchone()[0], strict=True)
    executor.close()
    restarted=RequestExecutor(_config(tmp_path))
    try:
        result=issue(restarted,identity)
        assert canonical_bytes(result).decode()==saved
        intent=intent_for(restarted,identity)
        verified=verify_cancellation_result(result,intent,now=NOW+timedelta(hours=2),
            provider_keys={restarted.config.provider_signing_key_id:restarted.config.provider_signing_key.public_key()})
        assert verified.state=='provider_local_suppressed' and verified.alias_count==8
        old=restarted.generations.active()
        _ = restarted.mutations.mutate(GenerationMutation(mutation_id='next-generation',operation=GenerationOperation.RUN,
            now=NOW+timedelta(hours=2),authority=GenerationAuthority(None,None),apply=lambda _root:None))
        assert not old.root.exists()
        assert issue(restarted,identity)==result
        with pytest.raises(sqlite3.IntegrityError):
            _ = restarted.store.db.execute('DELETE FROM correction_cancellation_results')
        with pytest.raises(sqlite3.IntegrityError):
            _ = restarted.store.db.execute("UPDATE correction_cancellation_results SET result_json='{}'")
    finally:
        restarted.close()


@pytest.mark.parametrize('field,value',[
    ('state','proved'),('disposition','all_managed_erased'),('original_request_id','other'),
    ('target_digest','sha256:'+'0'*64),('tombstone_sequence',2),('alias_count',7),
    ('completed_at','2099-01-01T00:00:00.000Z'),('activation_manifest_digest','sha256:'+'0'*64),
    ('result_generation_id','sbgen:v1:'+'0'*64),
])
def test_result_rejects_even_resigned_wrong_binding(tmp_path: Path,field: str,value: JsonValue):
    executor,identity,_=prepare(tmp_path)
    try:
        result=issue(executor,identity)
        body={key:val for key,val in result.items() if key not in {'result_id','result_digest','signature'}}
        body[field]=value
        with pytest.raises(ValueError):
            forged=model_object(sign_cancellation_result(body,executor.config.provider_signing_key))
            _ = verify_cancellation_result(forged,intent_for(executor,identity),now=NOW+timedelta(hours=2),
                provider_keys={executor.config.provider_signing_key_id:executor.config.provider_signing_key.public_key()})
    finally:
        executor.close()


def test_unknown_provider_key_and_wrong_signature_are_rejected(tmp_path: Path):
    executor,identity,_=prepare(tmp_path)
    try:
        result=issue(executor,identity);intent=intent_for(executor,identity)
        for value,keys in [(result,{}),({**result,'signature':'A'*86},
            {executor.config.provider_signing_key_id:executor.config.provider_signing_key.public_key()})]:
            with pytest.raises(CancellationResultError):
                _ = verify_cancellation_result(value,intent,now=NOW+timedelta(hours=2),provider_keys=keys)
    finally:
        executor.close()


def test_missing_alias_evidence_cannot_issue_result(tmp_path: Path):
    executor,identity,_=prepare(tmp_path)
    def corrupt(issuer: CancellationResultIssuer, intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
        _ = executor.store.db.execute('DROP TRIGGER correction_cancellation_alias_no_delete')
        _ = executor.store.db.execute("DELETE FROM correction_cancellation_aliases WHERE alias_kind='lane_id'")
        return issuer.complete(intent, generation_id, generation_digest)
    try:
        with pytest.raises(CancellationEvidenceError,match='CANCELLATION_ALIASES_UNPROVED'):
            _ = issue(executor,identity,corrupt)
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


def test_noop_suppression_cannot_issue_a_result(tmp_path: Path,monkeypatch: pytest.MonkeyPatch):
    executor,identity,_=prepare(tmp_path)
    before=executor.generations.active().generation_id
    called: list[bool]=[]
    def noop(_self: ErasureEngine, _root: Path, _intent: CorrectionCancellationIntentV1, _now: datetime) -> tuple[str, ...]:
        called.append(True)
        return ()
    monkeypatch.setattr(type(executor.erasure),'suppress_cancellation',noop)
    try:
        with pytest.raises(RuntimeError,match='MANAGED_COPY_REMAINS'):
            _ = issue(executor,identity)
        assert called==[True]
        assert executor.generations.active().generation_id==before
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


@pytest.mark.parametrize('surface',['absence','copy','reingress'])
def test_missing_completion_evidence_cannot_be_replaced_by_a_signature(tmp_path: Path,surface: str):
    executor,identity,_=prepare(tmp_path)
    def corrupt(issuer: CancellationResultIssuer, intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
        if surface=='absence':
            _ = executor.store.db.execute('DROP TRIGGER cancellation_absence_no_delete')
            _ = executor.store.db.execute('DELETE FROM correction_cancellation_absence')
        elif surface=='copy':
            _ = executor.store.db.execute("UPDATE managed_copy_disposals SET inventory_digest='invalid'")
        else:
            _ = executor.reingress.db.execute('INSERT INTO new_version_exceptions VALUES(?,?,?,?)',
                (intent.target.source_identity_full,intent.target.content_identity_full,'test-exception','2026-08-31T00:00:00.000Z'))
        return issuer.complete(intent, generation_id, generation_digest)
    try:
        with pytest.raises(RuntimeError):
            _ = issue(executor,identity,corrupt)
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


def test_shared_cross_runtime_result_fixture():

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    from sb.effect_values import parse_instant
    fixture=parse_object(Path('contracts/cancellation-result-v1.json').read_text())
    provider_public_key, now, result_body = fixture['provider_public_key'], fixture['now'], fixture['result']
    assert isinstance(provider_public_key, str) and isinstance(now, str) and isinstance(result_body, dict)
    signing_key_id = result_body['signing_key_id']
    assert isinstance(signing_key_id, str)
    intent=CorrectionCancellationIntentV1.model_validate(fixture['intent'])
    public_key = load_pem_public_key(provider_public_key.encode())
    assert isinstance(public_key, Ed25519PublicKey)
    result=verify_cancellation_result(result_body,intent,now=parse_instant(now),
        provider_keys={signing_key_id:public_key})
    assert result.result_digest==result_body['result_digest']


def test_key_revoked_during_absence_scan_prevents_activation(tmp_path: Path,monkeypatch: pytest.MonkeyPatch):
    executor,identity,_=prepare(tmp_path)
    before=executor.generations.active().generation_id
    keys={'jarvis:current':CURRENT.public_key()}
    def revoke(db: sqlite3.Connection, intent_id: str, generation_id: str, generation_digest: str, root: Path, needles: tuple[bytes, ...] | None) -> str:
        result=record_cancellation_absence(db, intent_id, generation_id, generation_digest, root, needles)
        keys.clear()
        return result
    monkeypatch.setattr('sb.correction_cancellation_executor.record_cancellation_absence',revoke)
    try:
        with pytest.raises(ValueError,match='MEMORY_CANCELLATION_INTENT_INVALID'):
            assert isinstance(identity, str)
            _ = apply_correction_cancellation(executor.mutations,executor.erasure,identity,now=NOW+timedelta(hours=1),
                backup_root=executor.config.backup_root,historical_delegation_keys=executor.config.jarvis_public_keys,
                current_cancellation_keys=keys)
        assert executor.generations.active().generation_id==before
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()
