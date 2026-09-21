from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from sb.cancellation_result import (
    CancellationResultError,
    sign_cancellation_result,
    verify_cancellation_result,
)
from sb.cancellation_result_issuer import CancellationEvidenceError, CancellationResultIssuer
from sb.correction_cancellation_executor import apply_correction_cancellation
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import canonical_bytes, strict_loads
from sb.effect_write_values import model_object
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.request_executor import RequestExecutor
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import prepare
from tests.test_managed_copy_disposal import prepare_copies
from tests.test_request_executor import NOW, _config


def issue(executor, identity, callback=None):
    config=executor.config
    issuer=CancellationResultIssuer(executor.store,executor.generations,executor.reingress,executor.exports,
        config.backup_root,config.provider_release_sha,config.provider_signing_key_id,config.provider_signing_key,
        NOW+timedelta(hours=1))
    return apply_correction_cancellation(executor.mutations,executor.erasure,identity,now=issuer.now,
        backup_root=config.backup_root,historical_delegation_keys=config.jarvis_public_keys,
        current_cancellation_keys={'jarvis:current':CURRENT.public_key()},
        complete=issuer.complete if callback is None else lambda *args:callback(issuer,*args))


def intent_for(executor, identity):
    row=executor.store.db.execute('SELECT intent_json FROM correction_cancellations WHERE intent_id=?',(identity,)).fetchone()
    return CorrectionCancellationIntentV1.model_validate(strict_loads(row[0],16_384))


def test_result_has_actual_evidence_and_survives_response_loss_and_later_generation(tmp_path: Path):
    executor,identity,_archive,_export=prepare_copies(tmp_path,'cancel')
    def lost(issuer,*args):
        issuer.complete(*args)
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        issue(executor,identity,lost)
    saved=executor.store.db.execute('SELECT result_json FROM correction_cancellation_results').fetchone()[0]
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
        restarted.mutations.mutate(GenerationMutation(mutation_id='next-generation',operation=GenerationOperation.RUN,
            now=NOW+timedelta(hours=2),authority=GenerationAuthority(None,None),apply=lambda _root:None))
        assert not old.root.exists()
        assert issue(restarted,identity)==result
        with pytest.raises(sqlite3.IntegrityError):
            restarted.store.db.execute('DELETE FROM correction_cancellation_results')
        with pytest.raises(sqlite3.IntegrityError):
            restarted.store.db.execute("UPDATE correction_cancellation_results SET result_json='{}'")
    finally:
        restarted.close()


@pytest.mark.parametrize('field,value',[
    ('state','proved'),('disposition','all_managed_erased'),('original_request_id','other'),
    ('target_digest','sha256:'+'0'*64),('tombstone_sequence',2),('alias_count',7),
    ('completed_at','2099-01-01T00:00:00.000Z'),('activation_manifest_digest','sha256:'+'0'*64),
    ('result_generation_id','sbgen:v1:'+'0'*64),
])
def test_result_rejects_even_resigned_wrong_binding(tmp_path: Path,field,value):
    executor,identity,_=prepare(tmp_path)
    try:
        result=issue(executor,identity)
        body={key:val for key,val in result.items() if key not in {'result_id','result_digest','signature'}}
        body[field]=value
        with pytest.raises(ValueError):
            forged=model_object(sign_cancellation_result(body,executor.config.provider_signing_key))
            verify_cancellation_result(forged,intent_for(executor,identity),now=NOW+timedelta(hours=2),
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
                verify_cancellation_result(value,intent,now=NOW+timedelta(hours=2),provider_keys=keys)
    finally:
        executor.close()


def test_missing_alias_evidence_cannot_issue_result(tmp_path: Path):
    executor,identity,_=prepare(tmp_path)
    def corrupt(issuer,*args):
        executor.store.db.execute('DROP TRIGGER correction_cancellation_alias_no_delete')
        executor.store.db.execute("DELETE FROM correction_cancellation_aliases WHERE alias_kind='lane_id'")
        return issuer.complete(*args)
    try:
        with pytest.raises(CancellationEvidenceError,match='CANCELLATION_ALIASES_UNPROVED'):
            issue(executor,identity,corrupt)
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


def test_noop_suppression_cannot_issue_a_result(tmp_path: Path,monkeypatch):
    executor,identity,_=prepare(tmp_path)
    before=executor.generations.active().generation_id
    called=[]
    def noop(*_args):
        called.append(True)
        return ()
    monkeypatch.setattr(type(executor.erasure),'suppress_cancellation',noop)
    try:
        with pytest.raises(RuntimeError,match='MANAGED_COPY_REMAINS'):
            issue(executor,identity)
        assert called==[True]
        assert executor.generations.active().generation_id==before
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


@pytest.mark.parametrize('surface',['absence','copy','reingress'])
def test_missing_completion_evidence_cannot_be_replaced_by_a_signature(tmp_path: Path,surface):
    executor,identity,_=prepare(tmp_path)
    def corrupt(issuer,intent,*args):
        if surface=='absence':
            executor.store.db.execute('DROP TRIGGER cancellation_absence_no_delete')
            executor.store.db.execute('DELETE FROM correction_cancellation_absence')
        elif surface=='copy':
            executor.store.db.execute("UPDATE managed_copy_disposals SET inventory_digest='invalid'")
        else:
            executor.reingress.db.execute('INSERT INTO new_version_exceptions VALUES(?,?,?,?)',
                (intent.target.source_identity_full,intent.target.content_identity_full,'test-exception','2026-08-31T00:00:00.000Z'))
        return issuer.complete(intent,*args)
    try:
        with pytest.raises(RuntimeError):
            issue(executor,identity,corrupt)
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()


def test_shared_cross_runtime_result_fixture():
    import json

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    from sb.effect_values import parse_instant
    fixture=json.loads(Path('contracts/cancellation-result-v1.json').read_text())
    intent=CorrectionCancellationIntentV1.model_validate(fixture['intent'])
    public_key = load_pem_public_key(fixture['provider_public_key'].encode())
    assert isinstance(public_key, Ed25519PublicKey)
    result=verify_cancellation_result(fixture['result'],intent,now=parse_instant(fixture['now']),
        provider_keys={fixture['result']['signing_key_id']:public_key})
    assert result.result_digest==fixture['result']['result_digest']


def test_key_revoked_during_absence_scan_prevents_activation(tmp_path: Path,monkeypatch):
    from sb.correction_cancellation_executor import record_cancellation_absence
    executor,identity,_=prepare(tmp_path)
    before=executor.generations.active().generation_id
    keys={'jarvis:current':CURRENT.public_key()}
    def revoke(*args):
        result=record_cancellation_absence(*args)
        keys.clear()
        return result
    monkeypatch.setattr('sb.correction_cancellation_executor.record_cancellation_absence',revoke)
    try:
        with pytest.raises(ValueError,match='MEMORY_CANCELLATION_INTENT_INVALID'):
            assert isinstance(identity, str)
            apply_correction_cancellation(executor.mutations,executor.erasure,identity,now=NOW+timedelta(hours=1),
                backup_root=executor.config.backup_root,historical_delegation_keys=executor.config.jarvis_public_keys,
                current_cancellation_keys=keys)
        assert executor.generations.active().generation_id==before
        assert executor.store.db.execute('SELECT count(*) FROM correction_cancellation_results').fetchone()[0]==0
    finally:
        executor.close()
