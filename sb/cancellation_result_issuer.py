"""Issue/replay a local suppression result only from durable provider evidence."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.cancellation_absence import require_cancellation_absence
from sb.cancellation_result import sign_cancellation_result, verify_cancellation_result
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.effect_values import JsonObject, canonical_bytes, digest, format_instant, strict_loads
from sb.effect_write_values import model_object
from sb.exports import ExportPublisher
from sb.generations import GenerationStore
from sb.managed_copy_disposal import copy_disposal_binding, require_copy_disposal
from sb.reingress import ErasureError, IngressIdentity, ReingressGate
from sb.request_store import RequestStore


class CancellationEvidenceError(RuntimeError):
    pass


def _text(row: sqlite3.Row, index: int) -> str:
    value = cast(object, row[index])
    if not isinstance(value, str):
        raise CancellationEvidenceError('CANCELLATION_RESULT_CORRUPT')
    return value


@dataclass(frozen=True)
class CancellationResultIssuer:
    requests: RequestStore
    generations: GenerationStore
    reingress: ReingressGate
    exports: ExportPublisher
    backup_root: Path
    provider_release_sha: str
    signing_key_id: str
    signing_key: Ed25519PrivateKey
    now: datetime
    provider_keys: Mapping[str, Ed25519PublicKey] | None = None
    authority: Callable[[], None] | None = None

    def aliases_digest(self, intent: CorrectionCancellationIntentV1) -> str:
        old = intent.original_delegation
        expected = sorted((('request_id', old.request_id), ('request_digest', old.request_digest),
            ('envelope_digest', intent.original_envelope_digest), ('idempotency_key', intent.original_idempotency_key),
            ('lane_id', old.lane_id), ('delegation_id', old.delegation_id),
            ('delegation_digest', old.delegation_digest), ('delegation_nonce', old.nonce)))
        rows = cast(list[tuple[str, str]], self.requests.db.execute('SELECT alias_kind,alias_value FROM correction_cancellation_aliases WHERE intent_id=? ORDER BY alias_kind,alias_value',
            (intent.intent_id,)).fetchall())
        if [tuple(row) for row in rows] != expected:
            raise CancellationEvidenceError('CANCELLATION_ALIASES_UNPROVED')
        return digest('surface', {'aliases': [{'kind':kind,'value':value} for kind,value in expected]})

    def _reingress(self, intent: CorrectionCancellationIntentV1) -> str:
        target = intent.target
        records: list[JsonObject] = []
        for kind, identity in (('source', target.source_identity_full), ('content', target.content_identity_full),
            ('citation', target.citation_identity_full), ('subject', target.subject_digest)):
            row = cast(tuple[int, str] | None, self.reingress.db.execute(
                'SELECT tombstone_sequence,tombstone_set_root FROM blocked_identities WHERE identity_kind=? AND identity_digest=?',
                (kind,identity)).fetchone())
            if row is None or row[0] > intent.tombstone.sequence or self.requests.tombstone_root_at(row[0]) != row:
                raise CancellationEvidenceError('CANCELLATION_REINGRESS_UNPROVED')
            records.append({'kind':kind,'identity':identity,'sequence':row[0],'root':row[1]})
        try:
            self.reingress.check(IngressIdentity(target.source_identity_full,target.content_identity_full,
                target.subject_digest,target.citation_identity_full))
        except ErasureError as exc:
            if str(exc) != 'TOMBSTONE_REINGRESS_BLOCKED':
                raise
        else:
            raise CancellationEvidenceError('CANCELLATION_REINGRESS_UNPROVED')
        return digest('surface', {'guards':records})

    def complete(self, intent: CorrectionCancellationIntentV1, generation_id: str, generation_digest: str) -> JsonObject:
        """Caller holds pending and generation writer locks, including on first-issuance replay."""
        if self.authority is not None:
            self.authority()
        saved = cast(sqlite3.Row | None, self.requests.db.execute(
            'SELECT result_json FROM correction_cancellation_results WHERE intent_id=?', (intent.intent_id,)).fetchone())
        if saved is not None:
            value = strict_loads(_text(saved, 0),16_384)
            if not isinstance(value,dict):
                raise CancellationEvidenceError('CANCELLATION_RESULT_CORRUPT')
            result = verify_cancellation_result(value,intent,now=self.now,
                provider_keys=self.provider_keys if self.provider_keys is not None else {self.signing_key_id:self.signing_key.public_key()})
            if (result.result_generation_id,result.result_generation_manifest_digest) != (generation_id,generation_digest):
                raise CancellationEvidenceError('CANCELLATION_RESULT_CORRUPT')
            if self.authority is not None:
                self.authority()
            return model_object(result)
        active = self.generations.active()
        high = (intent.tombstone.sequence,intent.tombstone.set_root)
        if (active.generation_id != generation_id or active.manifest.generation_digest != generation_digest
            or (active.manifest.tombstone_sequence,active.manifest.tombstone_set_root) != high
            or self.requests.tombstone_high_water() != high):
            raise CancellationEvidenceError('CANCELLATION_RESULT_GENERATION_UNAVAILABLE')
        activation, drain, disposal = self.generations.activation_digests(generation_id)
        roots = (self.backup_root,self.exports.root)
        binding = copy_disposal_binding(intent.intent_digest,generation_id,roots)
        require_copy_disposal(self.requests.db,intent.intent_id,binding,roots)
        self.exports.validate(self.now)
        row = cast(sqlite3.Row | None,self.requests.db.execute(
            'SELECT binding_digest,inventory_digest,observed_at FROM managed_copy_disposals WHERE operation_id=?',
            (intent.intent_id,)).fetchone())
        admitted = cast(sqlite3.Row | None,self.requests.db.execute(
            'SELECT accepted_at FROM correction_cancellations WHERE intent_id=?',(intent.intent_id,)).fetchone())
        if row is None or admitted is None:
            raise CancellationEvidenceError('CANCELLATION_RESULT_CORRUPT')
        old,target,t = intent.original_delegation,intent.target,intent.tombstone
        body: JsonObject = {'schema_version':1,'kind':'memory_correction_cancellation_result',
            'state':'provider_local_suppressed','disposition':'provider_local_suppression',
            'provider_instance_id':intent.provider_instance_id,'provider_release_sha':self.provider_release_sha,
            'signing_key_id':self.signing_key_id,'intent_id':intent.intent_id,'intent_digest':intent.intent_digest,
            'original_request_id':old.request_id,'original_envelope_digest':intent.original_envelope_digest,
            'original_lane_id':old.lane_id,'target_digest':target.target_digest,
            'target_manifest_digest':old.target_manifest_digest,'scope_digest':old.scope_digest,
            'base_generation_id':target.generation_id,'result_generation_id':generation_id,
            'result_generation_manifest_digest':generation_digest,'result_vault_head':active.head,'result_vault_tree':active.tree,
            'tombstone_sequence':t.sequence,'tombstone_previous_root':t.previous_root,'tombstone_set_root':t.set_root,
            'activation_manifest_digest':activation,'reader_drain_digest':drain,'predecessor_disposal_digest':disposal,
            'copy_checkpoint_digest':digest('surface',{'operation_id':intent.intent_id,'binding':_text(row, 0),
                'inventory':_text(row, 1),'observed_at':_text(row, 2)}),
            'aliases_digest':self.aliases_digest(intent),'alias_count':8,'reingress_digest':self._reingress(intent),
            'generation_absence_digest':require_cancellation_absence(self.requests.db,intent.intent_id,generation_id,generation_digest,active.root),
            'accepted_at':_text(admitted, 0),'completed_at':format_instant(self.now)}
        if self.authority is not None:
            self.authority()
        result = sign_cancellation_result(body,self.signing_key)
        wire = model_object(result)
        _ = verify_cancellation_result(wire,intent,now=self.now,
            provider_keys={self.signing_key_id:self.signing_key.public_key()})
        if self.authority is not None:
            self.authority()
        _ = self.requests.db.execute('INSERT INTO correction_cancellation_results VALUES(?,?,?)',
            (intent.intent_id,result.result_digest,canonical_bytes(wire).decode()))
        return wire
