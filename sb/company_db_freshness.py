from __future__ import annotations

import fcntl
import os
import sqlite3
from collections.abc import Callable, Generator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import ValidationError

from sb.company_approval_revocations import (
    approval_revocation_inventory,
    pending_approval_revocations,
)
from sb.company_approver_binding import CompanyHandoffPolicy
from sb.company_auto_cancellation import verify_auto_cancellation
from sb.company_auto_intents import consume_auto_reserve, pending_auto_reserve, prepare_auto_reserve
from sb.company_auto_publication import assessment_snapshot
from sb.company_db_freshness_evidence import (
    verify_internal_effect as _verify_internal_effect,
)
from sb.company_db_freshness_evidence import (
    verify_jarvis_sidecar as _verify_sidecar,
)
from sb.company_db_freshness_evidence import (
    verify_memory_receipt as _verify_memory_receipt,
)
from sb.company_db_freshness_hash import (
    checkpoint_object,
    checkpoint_text,
    deletion_operation_id,
    evidence_root,
    genesis_intent_root,
    genesis_stream_root,
    next_nv,
    operation_id_for,
    prefixed_digest,
    progress_root,
    raw_digest,
    record_digest,
    reservation_id_for,
    scope_object,
)
from sb.company_db_freshness_integrity import (
    CachedOperation,
    JournalEntry,
    audit_journal,
    audit_operation_cache,
    load_journal,
)
from sb.company_db_freshness_models import (
    ActorStore,
    EvidenceRejected,
    EvidenceVerifier,
    FreshnessRegistry,
    GenesisEntry,
    GenesisInventory,
    JarvisRecoveryEvidence,
    JarvisSidecarEvidence,
    RegistryScopePin,
    RegistryTpmPin,
    VerifiedEvidence,
    WitnessTransport,
)
from sb.company_db_freshness_models import OperationRow as _OperationRow
from sb.company_freshness_anchor import (
    FIXED_LOCK_PATH,
    FIXED_REGISTRY_PATH,
    FIXED_WITNESS_DIR,
    NV_HANDLE,
    NV_NAME_ALG,
    AnchorRejected,
    NvAnchor,
    append_witness_frame,
    extend_if_needed,
    read_witness_frames,
    require_trusted_file,
)
from sb.company_freshness_deletion import (
    deletion_evidence,
    deletion_source,
    original_deletion_fact,
    verify_original_deletion,
)
from sb.company_freshness_genesis import (
    audit_owned_pending,
    audit_owned_receipts,
    default_transition_unenrolled,
    verify_owned_genesis,
)
from sb.company_freshness_migrations import migration_applied
from sb.company_freshness_models import (
    TERMINAL_STATE_BY_OPERATION,
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessProviderConfig,
    FreshnessScope,
    FreshnessWireError,
    ProgressOperation,
    ProgressTerminalState,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
    StoreHeads,
    StoreProgress,
)
from sb.company_freshness_progress import is_other_store_prefix
from sb.company_freshness_registry import (
    current_auto_pin,
    latest_auto_pins,
    require_current_auto_pins,
    require_forward_pin,
    require_scope_pins,
)
from sb.company_freshness_storage import open_company_database as _connect
from sb.company_freshness_tpm import TpmNvExtendAnchor
from sb.company_memory_authority import CompanyAuthorityContext
from sb.company_processor_progress import save_checkpoint
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant, strict_loads
from sb.effect_write_values import model_object

__all__ = [
    "CompanyDbFreshnessProvider",
    "FreshnessRegistry",
    "GenesisEntry",
    "GenesisInventory",
    "JarvisSidecarEvidence",
    "RegistryScopePin",
    "RegistryTpmPin",
    "bootstrap_company_scope",
    "company_db_provider_from_factory",
    "preview_genesis_checkpoint",
]
_ALLOWED: dict[ActorStore, frozenset[ProgressOperation]] = {
    "jarvis": frozenset({"decide_approve", "decide_reject", "complete"}),
    "second_brain": frozenset({"accept", "reject", "complete", "mark_processed", "delete"}),
}
_RECEIPT_ONLY: frozenset[ProgressOperation] = frozenset(
    {"decide_approve", "accept"},
)
_TERMINAL_OPS: frozenset[ProgressOperation] = frozenset(
    {"decide_reject", "reject", "complete", "mark_processed", "delete"},
)


class CompanyDbEvidenceVerifier:
    def verify(
        self,
        connection: sqlite3.Connection,
        *,
        scope: FreshnessScope,
        actor_store: ActorStore,
        operation: ProgressOperation,
        operation_id: str,
        event_digest: str,
        evidence_digest: str,
        terminal_state: ProgressTerminalState,
    ) -> VerifiedEvidence:
        del terminal_state, operation_id
        if actor_store == "second_brain" and operation in {"accept", "reject", "mark_processed"}:
            return _verify_memory_receipt(
                connection, scope, operation, event_digest, evidence_digest
            )
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")


def company_db_provider_from_factory(
    config: FreshnessProviderConfig,
    *,
    company_database: Path | None,
    actor_store: ActorStore,
) -> CompanyDbFreshnessProvider:
    if config.kind != "sb_company_db" or config.registry_id is None or company_database is None:
        raise ValueError("company_database is required for sb_company_db")
    return CompanyDbFreshnessProvider(
        database=company_database,
        actor_store=actor_store,
        registry_path=FIXED_REGISTRY_PATH,
        witness_dir=FIXED_WITNESS_DIR,
        lock_path=FIXED_LOCK_PATH,
        anchor=TpmNvExtendAnchor(),
        registry_id=config.registry_id,
    )


class CompanyDbFreshnessProvider:
    def __init__(
        self,
        *,
        database: Path,
        actor_store: ActorStore,
        registry_path: Path,
        witness_dir: Path,
        lock_path: Path,
        anchor: NvAnchor,
        registry_id: str,
        verifier: EvidenceVerifier | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.database: Path = database
        self.actor_store: ActorStore = actor_store
        self.registry_path: Path = registry_path
        self.witness_dir: Path = witness_dir
        self.lock_path: Path = lock_path
        self.anchor: NvAnchor = anchor
        self.registry_id: str = registry_id
        self.verifier: EvidenceVerifier = (
            verifier if verifier is not None else CompanyDbEvidenceVerifier()
        )
        self.clock: Callable[[], str] = clock if clock is not None else _clock

    @property
    def installation_id(self) -> str:
        return self._registry().installation_id

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        try:
            with self._locked():
                self._recover()
                head = self._head(request.scope)
                if head is None:
                    status: Literal["mismatch", "unavailable"] = (
                        "mismatch" if self._pinned(request.scope) else "unavailable"
                    )
                    return _read(request, status, None)
                if self._closed(request.scope) or not self._installation(request.installation_id):
                    return _read(
                        request, "mismatch" if self._closed(request.scope) else "unavailable", None
                    )
                if self._pending(request.scope) or self._unpublished():
                    return _read(request, "uncertain", None)
                return _read(
                    request, _read_status(request, head, self.actor_store, self.database), head
                )
        except (AnchorRejected, OSError, sqlite3.Error, ValueError):
            return _read(request, "unavailable", None)

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        try:
            with self._locked():
                self._recover()
                return self._reserve(request)
        except AnchorRejected:
            return _wire_error()
        except (OSError, sqlite3.Error, ValueError):
            return _wire_error()

    def has_original_reservation(
        self,
        scope: FreshnessScope,
        operation: ProgressOperation,
        event_digest: str,
        observed: Checkpoint,
    ) -> bool:
        """Recovery evidence only; the actual reserve must still match operation ID."""
        with self._locked():
            self._recover()
            if self._closed(scope):
                return False
            connection = _connect(self.database)
            try:
                rows: list[tuple[str]] = connection.execute(
                    """SELECT reserved_checkpoint_json FROM company_freshness_operations
                    WHERE provider_instance_id=? AND workspace_id=? AND actor_store=?
                      AND operation=? AND event_digest=? AND reserve_expected_json=?
                      AND state='reserved'""",
                    (
                        scope.provider_instance_id,
                        scope.workspace_id,
                        self.actor_store,
                        operation,
                        event_digest,
                        checkpoint_text(observed),
                    ),
                ).fetchall()
            finally:
                connection.close()

            return len(rows) == 1 and Checkpoint.model_validate_json(
                rows[0][0], strict=True
            ) == self._head(scope)

    def rebase_unreserved_auto_intent(self, scope: FreshnessScope, expected: Checkpoint) -> None:
        """Change only a never-reserved intent, under the publication lock and SQL CAS."""
        with self._locked():
            self._recover()
            connection = _connect(self.database)
            try:
                _ = connection.execute("BEGIN IMMEDIATE")
                intent = pending_auto_reserve(connection, scope)
                if intent is None or intent.request.expected_checkpoint == expected:
                    return
                request = intent.request
                if (
                    self.actor_store != "second_brain"
                    or self._closed(scope)
                    or self._require_head(scope) != expected
                    or not is_other_store_prefix(
                        request.expected_checkpoint, expected, "second_brain"
                    )
                    or self._operation(scope, request.operation_id) is not None
                    or not any(
                        entry.scope == scope
                        and entry.published_sequence is not None
                        and entry.after == request.expected_checkpoint
                        for entry in load_journal(connection)
                    )
                ):
                    raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
                for table in (
                    "company_memory_receipts",
                    "company_processor_pending_finish",
                    "company_internal_pending_finish",
                ):
                    if connection.execute(
                        f"SELECT 1 FROM {table} WHERE workspace_id=? AND request_digest=?",
                        (scope.workspace_id, request.event_digest),
                    ).fetchone():
                        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
                if connection.execute(
                    """SELECT 1 FROM company_internal_effects
                    WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
                    (scope.provider_instance_id, scope.workspace_id, request.operation_id),
                ).fetchone():
                    raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
                if request.operation in {"accept", "complete"}:
                    for table, column in (
                        ("company_internal_effects", "candidate_id"),
                        ("company_internal_records", "source_candidate_id"),
                    ):
                        if connection.execute(
                            f"SELECT 1 FROM {table} WHERE provider_instance_id=? "
                            f"AND workspace_id=? AND {column}=?",
                            (scope.provider_instance_id, scope.workspace_id, intent.candidate_id),
                        ).fetchone():
                            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
                consume_auto_reserve(connection, intent)
                prepare_auto_reserve(
                    connection,
                    intent.model_copy(
                        update={
                            "request": request.model_copy(update={"expected_checkpoint": expected})
                        }
                    ),
                )
                connection.commit()
            finally:
                connection.close()

    def require_completed_handoff(
        self,
        scope: FreshnessScope,
        request_id: str,
        command_digest: str,
    ) -> None:
        with self._locked():
            self._recover()
            original = self._operation(
                scope,
                operation_id_for(
                    scope,
                    request_id=request_id,
                    command_digest=command_digest,
                    operation="complete",
                ),
            )
            if (
                original is None
                or original.actor_store != "jarvis"
                or original.state != "finished"
                or original.terminal_state != "completed"
            ):
                raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")

    @contextmanager
    def read_only_report(self, scope: FreshnessScope) -> Generator[sqlite3.Connection, None, None]:
        with (
            self._locked(),
            closing(sqlite3.connect(f"{self.database.resolve().as_uri()}?mode=ro", uri=True)) as db,
        ):
            _ = db.execute("PRAGMA query_only=ON")
            _ = db.execute("BEGIN")
            self._audit_snapshot(db)
            if _unpublished_row(db) is not None:
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            if (
                db.execute(
                    "SELECT 1 FROM company_freshness_scopes WHERE provider_instance_id=? AND workspace_id=?",
                    (scope.provider_instance_id, scope.workspace_id),
                ).fetchone()
                is None
            ):
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            yield db

    @contextmanager
    def effect_guard(
        self,
        scope: FreshnessScope,
        operation_id: str,
        reservation: ReserveProgressResponse,
    ) -> Generator[None, None, None]:
        """Lock order is registry then SQL; all anchor I/O precedes the writer."""
        with self._locked():
            self._recover()
            original = self._operation(scope, operation_id)
            if (
                original is None
                or original.state != "reserved"
                or original.actor_store != self.actor_store
                or original.reservation_id != reservation.reservation_id
                or reservation.scope != scope
                or reservation.checkpoint != self._head(scope)
                or self._closed(scope)
            ):
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            yield

    def cancel_unapplied_under_guard(
        self,
        scope: FreshnessScope,
        operation_id: str,
        reservation: ReserveProgressResponse,
        processor_before: Checkpoint,
        *,
        processor_binding: JsonObject | None = None,
    ) -> None:
        """Caller holds effect_guard; resumed auto acceptance requires full zero-effect proof."""
        original = self._operation(scope, operation_id)
        head = self._require_head(scope)
        if (
            original is None
            or original.state != "reserved"
            or original.actor_store != "second_brain"
            or self.actor_store != "second_brain"
            or original.operation not in {"accept", "reject", "mark_processed", "complete"}
            or reservation.outcome not in {"reserved", "already_reserved"}
            or original.reservation_id != reservation.reservation_id
            or original.reserve_expected_json != checkpoint_text(processor_before)
            or reservation.checkpoint != head
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        record: JsonObject = {
            "kind": "unapplied_processor_cancellation",
            "operation_id": operation_id,
            "reservation_id": original.reservation_id,
            "event_digest": original.event_digest,
            "original_at": self.clock(),
            "processor_checkpoint_before": checkpoint_object(processor_before),
            "terminal_state": "cancelled",
            "state": "finished",
        }
        if processor_binding is not None:
            record["processor_binding"] = processor_binding
        connection = _connect(self.database)
        try:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_internal_pending_reserve'"
            ).fetchone():
                intent = pending_auto_reserve(connection, scope)
                if intent is not None:
                    record["auto_intent"] = model_object(intent)
                    for table in (
                        "company_internal_pending_finish",
                        "company_processor_pending_finish",
                    ):
                        if connection.execute(
                            f"SELECT 1 FROM {table} WHERE workspace_id=?", (scope.workspace_id,)
                        ).fetchone():
                            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            if reservation.outcome == "already_reserved" and not (
                "auto_intent" in record or "processor_binding" in record
            ):
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            if original.operation == "complete" and "auto_intent" not in record:
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            verified = _verify_unapplied_cancellation(connection, scope, original, record)
            local = connection.execute(
                "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
                (scope.workspace_id,),
            ).fetchone()
            if local is None or local[0] != checkpoint_text(processor_before):
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        finally:
            connection.close()
        record["evidence_digest"] = verified.source_digest
        evidence = _finish_evidence(
            scope, original.operation, "second_brain", head, verified, "cancelled"
        )
        self._publish_new(
            scope=scope,
            phase="finish",
            operation_id=operation_id,
            record=record,
            evidence=evidence,
            before=head,
            after=_apply_finish(head, record, "second_brain", evidence),
            challenge="unapplied-authorization-rejected",
            reservation_id=original.reservation_id,
            operation=original.operation,
            event_digest=original.event_digest,
            expected_json=checkpoint_text(head),
            terminal_state="cancelled",
            evidence_digest=verified.source_digest,
        )

    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError:
        try:
            with self._locked():
                self._recover()
                return self._finish(request, sidecar=None, context=None, policy=None)
        except AnchorRejected:
            return _wire_error()
        except (OSError, sqlite3.Error, ValueError):
            return _wire_error()

    def finish_with_jarvis_sidecar(
        self,
        request: FinishProgressRequest,
        sidecar: JarvisSidecarEvidence,
        *,
        context: CompanyAuthorityContext,
        policy: CompanyHandoffPolicy,
    ) -> FinishProgressResponse | FreshnessWireError:
        try:
            with self._locked():
                self._recover()
                return self._finish(request, sidecar=sidecar, context=context, policy=policy)
        except AnchorRejected:
            return _wire_error()
        except (OSError, sqlite3.Error, ValueError):
            return _wire_error()

    def bridge_deletion(
        self,
        *,
        scope: FreshnessScope,
        deletion_plan_digest: str,
        expected_checkpoint: Checkpoint,
        challenge: str,
    ) -> ReserveProgressResponse | FinishProgressResponse | FreshnessWireError:
        """Record existing approved deletion facts; this performs no deletion."""
        operation_id = deletion_operation_id(scope, deletion_plan_digest)
        try:
            source = deletion_source(self._registry(), scope, operation_id)
            _intent, event = original_deletion_fact(source, "intent")
        except (ValueError, AnchorRejected, OSError):
            return _wire_error()
        finish_challenge = "deletion-finish:" + prefixed_digest(
            b"second-brain/company-deletion-challenge/v1\0", challenge
        )
        request = ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=operation_id,
            operation="delete",
            expected_checkpoint=expected_checkpoint,
            event_digest=event,
            challenge=challenge,
        )
        reserved = self.reserve_progress(request)
        if (
            not isinstance(reserved, ReserveProgressResponse)
            or reserved.checkpoint is None
            or reserved.reservation_id is None
            or source.completion_path is None
            or source.completion_digest is None
        ):
            return reserved
        result = self.finish_progress(
            FinishProgressRequest(
                schema_version=2,
                scope=scope,
                operation_id=operation_id,
                reservation_id=reserved.reservation_id,
                expected_checkpoint=reserved.checkpoint,
                evidence_digest=source.completion_digest,
                terminal_state="deleted",
                challenge=finish_challenge,
            )
        )
        return result

    def publish_assessment(
        self,
        scope: FreshnessScope,
        assessment_digest: str,
        expected: Checkpoint,
    ) -> Checkpoint:
        """Anchor an actual SQL assessment snapshot, without authorizing an effect."""
        with self._locked():
            self._recover()
            head = self._require_head(scope)
            if (
                self.actor_store != "second_brain"
                or expected != head
                or not self._ready_scope(scope)
                or self._pending(scope)
            ):
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            connection = _connect(self.database)
            try:
                snapshot = assessment_snapshot(connection, scope, assessment_digest)
                record: JsonObject = {
                    "kind": "internal_auto_assessment",
                    "snapshot": model_object(snapshot),
                }
                serialized = canonical_bytes(model_object(snapshot)).decode("utf-8")
                exists: list[tuple[int]] = connection.execute(
                    """SELECT 1 FROM company_freshness_log l
                    JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
                    WHERE l.provider_instance_id=? AND l.workspace_id=?
                      AND l.phase='registry'
                      AND json_extract(l.record_json,'$.kind')='internal_auto_assessment'
                      AND json_extract(l.record_json,'$.snapshot')=?""",
                    (scope.provider_instance_id, scope.workspace_id, serialized),
                ).fetchall()
            finally:
                connection.close()
            if not exists:
                self._publish_new(
                    scope=scope,
                    phase="registry",
                    operation_id=snapshot.operation_id,
                    record=record,
                    evidence=[],
                    before=head,
                    after=head,
                    challenge="assessment:" + assessment_digest,
                    reservation_id="assessment",
                    operation="complete",
                    event_digest=assessment_digest,
                    expected_json=checkpoint_text(head),
                    terminal_state=None,
                    evidence_digest=None,
                )
            return head

    def publish_completed_assessments(
        self, scope: FreshnessScope, expected: Checkpoint
    ) -> Checkpoint:
        connection = _connect(self.database)
        try:
            missing: list[tuple[str]] = connection.execute(
                """SELECT a.assessment_digest FROM company_auto_assessments a
                JOIN company_auto_policy_receipts r ON r.provider_instance_id=a.provider_instance_id
                  AND r.workspace_id=a.workspace_id AND r.assessment_digest=a.assessment_digest
                JOIN company_memory_candidates c
                  ON c.workspace_id=a.workspace_id AND c.candidate_id=a.candidate_id
                WHERE a.provider_instance_id=? AND a.workspace_id=? AND c.state='processed_complete'
                  AND NOT EXISTS(SELECT 1 FROM company_freshness_log l
                    JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
                    WHERE l.provider_instance_id=a.provider_instance_id AND l.workspace_id=a.workspace_id
                      AND json_extract(l.record_json,'$.kind')='internal_auto_assessment'
                      AND json_extract(l.record_json,'$.snapshot.assessment_digest')=a.assessment_digest
                      AND json_extract(l.record_json,'$.snapshot.state')='processed_complete')
                ORDER BY a.assessment_digest LIMIT 100""",
                (scope.provider_instance_id, scope.workspace_id),
            ).fetchall()
        finally:
            connection.close()
        for (digest,) in missing:
            expected = self.publish_assessment(scope, digest, expected)
        return expected

    def validate_auto_policy_pin(self, scope: FreshnessScope) -> None:
        """Reject invalid operator advancement before writing any local policy row."""
        with self._locked():
            self._recover(allow_policy_update=True, read_only=True)
            pin = current_auto_pin(self._registry(), scope)
            connection = _connect(self.database)
            try:
                previous = latest_auto_pins(load_journal(connection)).get(
                    (scope.provider_instance_id, scope.workspace_id),
                )
            finally:
                connection.close()
            if pin != previous:
                require_forward_pin(previous, pin)

    def install_auto_policy_pin(self, scope: FreshnessScope) -> Checkpoint:
        """Operator-only activation of the exact protected registry entry."""
        with self._locked():
            self._recover(allow_policy_update=True)
            head = self._require_head(scope)
            if self.actor_store != "second_brain" or self._pending(scope) or self._closed(scope):
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            pin = current_auto_pin(self._registry(), scope)
            connection = _connect(self.database)
            try:
                journal = load_journal(connection)
                previous = latest_auto_pins(journal).get(
                    (scope.provider_instance_id, scope.workspace_id),
                )
                local_row = connection.execute(
                    "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
                    (scope.workspace_id,),
                ).fetchone()
            finally:
                connection.close()
            if previous == pin:
                return head
            require_forward_pin(previous, pin)
            if local_row is None:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            local = Checkpoint.model_validate_json(local_row[0], strict=True)
            if not is_other_store_prefix(local, head, "second_brain") or not any(
                entry.scope == scope
                and entry.published_sequence is not None
                and entry.after == local
                for entry in journal
            ):
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            record: JsonObject = {
                "kind": "internal_auto_policy",
                "pin": model_object(pin),
                "processor_checkpoint_before": checkpoint_object(local),
            }
            digest = prefixed_digest(b"second-brain/company-auto-policy-registration/v1\0", record)
            evidence = [
                _stream_projection(
                    scope,
                    "registry",
                    "revocation",
                    head.revocation_root,
                    head.revocation_sequence + 1,
                    f"auto-policy:{pin.revision}",
                    digest,
                    {"original_at": self.clock(), "kind": "policy_registration"},
                )
            ]
            after = _advance_intent(head, record).model_copy(
                update={
                    "revocation_sequence": head.revocation_sequence + 1,
                    "revocation_root": evidence[0]["root"],
                }
            )
            self._publish_new(
                scope=scope,
                phase="registry",
                operation_id="auto-policy:" + digest,
                record=record,
                evidence=evidence,
                before=head,
                after=after,
                challenge="auto-policy:" + digest,
                reservation_id="policy",
                operation="complete",
                event_digest=digest,
                expected_json=checkpoint_text(head),
                terminal_state=None,
                evidence_digest=None,
            )
            return after

    def require_auto_policy(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None:
        with self.auto_policy_guard(
            scope, policy_digest, key_id, key_fingerprint, source_context_digest
        ):
            pass

    @contextmanager
    def auto_policy_guard(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> Generator[None, None, None]:
        """Keep registry exclusion through the caller's SQL commit, never SQL first."""
        with self._locked():
            self._recover()
            self.require_auto_policy_under_guard(
                scope, policy_digest, key_id, key_fingerprint, source_context_digest
            )
            yield

    def require_auto_policy_under_guard(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None:
        """Caller holds effect_guard or auto_policy_guard; no recursive flock or writer."""
        registry = self._registry()
        pin = current_auto_pin(registry, scope)
        connection = _connect(self.database)
        try:
            installed = latest_auto_pins(load_journal(connection)).get(
                (scope.provider_instance_id, scope.workspace_id),
            )
        finally:
            connection.close()
        if (
            installed != pin
            or pin.policy_digest != policy_digest
            or pin.key_id != key_id
            or pin.public_key_fingerprint != key_fingerprint
            or policy_digest in pin.revoked_policy_digests
            or key_fingerprint in pin.revoked_key_fingerprints
            or _pin(registry, scope).source_context_digest != source_context_digest
        ):
            raise AnchorRejected("COMPANY_POLICY_REGISTRATION_REQUIRED")

    def record_approval_revocations(self, scope: FreshnessScope) -> Checkpoint:
        """Operator-only forward revocation; no new epoch or restored authority."""
        with self._locked():
            self._recover(allow_approval_revocation=True)
            if self.actor_store != "second_brain":
                raise AnchorRejected("COMPANY_APPROVAL_REVOKED")
            head = self._require_head(scope)
            connection = _connect(self.database)
            try:
                facts = pending_approval_revocations(
                    self._registry(),
                    load_journal(connection),
                    scope,
                )
            finally:
                connection.close()
            for fact in facts:
                if (
                    fact.approval_policy_version != head.approval_policy_version
                    or fact.approval_binding_digest != head.approval_binding_digest
                ):
                    raise AnchorRejected("COMPANY_APPROVAL_REVOKED")
                value = model_object(fact)
                digest = prefixed_digest(b"second-brain/company-approval-revocation/v1\0", value)
                record: JsonObject = {
                    "kind": "approval_revocation",
                    "closed": True,
                    "revocation": value,
                }
                evidence = [
                    _stream_projection(
                        scope,
                        "registry",
                        "revocation",
                        head.revocation_root,
                        head.revocation_sequence + 1,
                        "approval-revocation:" + fact.source_record_id,
                        digest,
                        {"original_at": fact.original_at, "kind": fact.reason},
                    )
                ]
                after = _advance_intent(head, record).model_copy(
                    update={
                        "revocation_sequence": head.revocation_sequence + 1,
                        "revocation_root": evidence[0]["root"],
                    }
                )
                self._publish_new(
                    scope=scope,
                    phase="registry",
                    operation_id="approval-revocation:" + digest,
                    record=record,
                    evidence=evidence,
                    before=head,
                    after=after,
                    challenge="approval-revocation:" + digest,
                    reservation_id="revocation",
                    operation="complete",
                    event_digest=digest,
                    expected_json=checkpoint_text(head),
                    terminal_state=None,
                    evidence_digest=None,
                )
                head = after
            return head

    def _reserve(
        self, request: ReserveProgressRequest
    ) -> ReserveProgressResponse | FreshnessWireError:
        if not self._ready_scope(request.scope):
            return _wire_error()
        if request.operation not in _ALLOWED[self.actor_store]:
            return _conflict_reserve(request)
        existing = self._operation(request.scope, request.operation_id)
        if existing is not None:
            if _same_reserve(existing, request):
                reserved = Checkpoint.model_validate_json(existing.reserved_checkpoint_json)
                return _reserved(request, "already_reserved", reserved, existing.reservation_id)
            return _conflict_reserve(request)
        if self._other_pending(request.scope, request.operation_id):
            return _conflict_reserve(request)
        head = self._require_head(request.scope)
        if request.expected_checkpoint != head:
            return _conflict_reserve(request)
        if self._challenge_replay(request.challenge, request.operation_id):
            return _conflict_reserve(request)
        reservation_id = reservation_id_for(request.operation_id)
        record: JsonObject = {
            "operation_id": request.operation_id,
            "operation": request.operation,
            "event_digest": request.event_digest,
            "reservation_id": reservation_id,
            "actor_store": self.actor_store,
            "state": "reserved",
        }
        deletion_intent: VerifiedEvidence | None = None
        if request.operation == "delete":
            source = deletion_source(self._registry(), request.scope, request.operation_id)
            fact, digest = original_deletion_fact(source, "intent")
            if digest != request.event_digest:
                return _conflict_reserve(request)
            deletion_intent = deletion_evidence(fact, digest)
        evidence = _reserve_evidence(request, self.actor_store, head, head, deletion_intent)
        after = _apply_finish(head, record, self.actor_store, evidence)
        self._publish_new(
            scope=request.scope,
            phase="reserve",
            operation_id=request.operation_id,
            record=record,
            evidence=evidence,
            before=head,
            after=after,
            challenge=request.challenge,
            reservation_id=reservation_id,
            operation=request.operation,
            event_digest=request.event_digest,
            expected_json=checkpoint_text(request.expected_checkpoint),
            terminal_state=None,
            evidence_digest=None,
        )
        return _reserved(request, "reserved", after, reservation_id)

    def _finish(
        self,
        request: FinishProgressRequest,
        *,
        sidecar: JarvisSidecarEvidence | None,
        context: CompanyAuthorityContext | None,
        policy: CompanyHandoffPolicy | None,
    ) -> FinishProgressResponse | FreshnessWireError:
        if not self._ready_scope(request.scope):
            return _wire_error()
        existing = self._operation_by_reservation(request.scope, request.reservation_id)
        if existing is None or existing.operation_id != request.operation_id:
            return _conflict_finish(request)
        if existing.actor_store != self.actor_store:
            return _conflict_finish(request)
        if request.terminal_state not in {
            TERMINAL_STATE_BY_OPERATION[existing.operation],
            "cancelled",
        }:
            return _conflict_finish(request)
        if existing.state == "finished":
            if (
                existing.evidence_digest == request.evidence_digest
                and existing.terminal_state == request.terminal_state
                and existing.finish_expected_json == checkpoint_text(request.expected_checkpoint)
            ):
                finished = Checkpoint.model_validate_json(
                    existing.finished_checkpoint_json or "null"
                )
                return _finished(request, "already_recorded", finished)
            return _conflict_finish(request)
        head = self._require_head(request.scope)
        if request.expected_checkpoint != head:
            return _conflict_finish(request)
        try:
            verified = self._verify_finish(request, existing, sidecar, context, policy)
        except EvidenceRejected as exc:
            if exc.code == "COMPANY_RECEIPT_EVIDENCE_ABSENT":
                return FreshnessWireError(
                    schema_version=2,
                    outcome="error",
                    code="COMPANY_RECEIPT_EVIDENCE_ABSENT",
                )
            return _conflict_finish(request)
        record: JsonObject = {
            "operation_id": request.operation_id,
            "reservation_id": request.reservation_id,
            "evidence_digest": verified.source_digest,
            "terminal_state": request.terminal_state,
            "state": "finished",
        }
        if self.actor_store == "second_brain" and existing.operation in {"accept", "reject"}:
            with closing(_connect(self.database)) as db:
                record["default_transition_authority"] = default_transition_unenrolled(
                    db, request.scope.workspace_id
                )
        if sidecar is not None and context is not None and policy is not None:
            record["jarvis_evidence"] = model_object(
                JarvisRecoveryEvidence(sidecar=sidecar, context=context, policy=policy)
            )
        if existing.operation == "delete" and self.actor_store == "second_brain":
            source = deletion_source(self._registry(), request.scope, existing.operation_id)
            intent, _ = original_deletion_fact(source, "intent")
            if not self._deletion_fence_safe(
                request.scope, intent.source_fence, intent.source_root
            ):
                record["closed"] = True
                record["reason"] = "deletion_fence"
        if request.evidence_digest != verified.source_digest:
            return _conflict_finish(request)
        evidence = _finish_evidence(
            request.scope,
            existing.operation,
            self.actor_store,
            head,
            verified,
            request.terminal_state,
        )
        connection = _connect(self.database)
        try:
            for item in evidence:
                if connection.execute(
                    """SELECT 1 FROM company_freshness_evidence
                    WHERE provider_instance_id=? AND workspace_id=? AND store=? AND stream=?
                      AND (sequence=? OR source_record_id=?)""",
                    (
                        request.scope.provider_instance_id,
                        request.scope.workspace_id,
                        item["store"],
                        item["stream"],
                        item["sequence"],
                        item["source_record_id"],
                    ),
                ).fetchone():
                    return _conflict_finish(request)
        finally:
            connection.close()
        after = _apply_finish(head, record, self.actor_store, evidence)
        self._publish_new(
            scope=request.scope,
            phase="finish",
            operation_id=request.operation_id,
            record=record,
            evidence=evidence,
            before=head,
            after=after,
            challenge=request.challenge,
            reservation_id=request.reservation_id,
            operation=existing.operation,
            event_digest=existing.event_digest,
            expected_json=checkpoint_text(request.expected_checkpoint),
            terminal_state=request.terminal_state,
            evidence_digest=verified.source_digest,
        )
        return _finished(request, "recorded", after)

    def _verify_finish(
        self,
        request: FinishProgressRequest,
        existing: _OperationRow,
        sidecar: JarvisSidecarEvidence | None,
        context: CompanyAuthorityContext | None,
        policy: CompanyHandoffPolicy | None,
    ) -> VerifiedEvidence:
        connection = _connect(self.database)
        try:
            if sidecar is not None:
                if context is None or policy is None or self.actor_store != "jarvis":
                    raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
                return _verify_sidecar(connection, sidecar, request, existing, context, policy)
            if request.terminal_state == "cancelled":
                raise EvidenceRejected("COMPANY_VERIFIER_INVALID")
            if existing.operation == "delete" and self.actor_store == "second_brain":
                return verify_original_deletion(
                    self._registry(),
                    request.scope,
                    existing.operation_id,
                    existing.event_digest,
                    request.evidence_digest,
                )
            if existing.operation == "complete" and self.actor_store == "second_brain":
                return _verify_internal_effect(
                    connection,
                    request.scope,
                    existing.operation_id,
                    existing.event_digest,
                    request.evidence_digest,
                    self._registry(),
                )
            return self.verifier.verify(
                connection,
                scope=request.scope,
                actor_store=self.actor_store,
                operation=existing.operation,
                operation_id=existing.operation_id,
                event_digest=existing.event_digest,
                evidence_digest=request.evidence_digest,
                terminal_state=request.terminal_state,
            )
        finally:
            connection.close()

    def _publish_new(
        self,
        *,
        scope: FreshnessScope,
        phase: str,
        operation_id: str,
        record: JsonObject,
        evidence: list[JsonObject],
        before: Checkpoint,
        after: Checkpoint,
        challenge: str,
        reservation_id: str,
        operation: ProgressOperation,
        event_digest: str,
        expected_json: str,
        terminal_state: str | None,
        evidence_digest: str | None,
    ) -> None:
        record = {
            **record,
            "transport": {
                "challenge": challenge,
                "reservation_id": reservation_id,
                "terminal_state": terminal_state,
            },
        }
        previous = self.anchor.read_value()
        sequence = self._next_sequence()
        digest = record_digest(
            global_sequence=sequence,
            scope=scope,
            phase=phase,
            record=record,
            evidence=evidence,
            before_checkpoint=before,
            after_checkpoint=after,
        )
        nxt = next_nv(previous, digest)
        created_at = self.clock()
        connection = _connect(self.database)
        try:
            _ = connection.execute("BEGIN IMMEDIATE")
            _insert_log(
                connection,
                sequence=sequence,
                scope=scope,
                phase=phase,
                operation_id=operation_id,
                record=record,
                evidence=evidence,
                digest=digest,
                previous=previous,
                nxt=nxt,
                before=before,
                after=after,
                created_at=created_at,
            )
            if phase == "reserve":
                _insert_operation(
                    connection,
                    scope=scope,
                    operation_id=operation_id,
                    operation=operation,
                    actor_store=self.actor_store,
                    event_digest=event_digest,
                    reservation_id=reservation_id,
                    expected_json=expected_json,
                    reserved_json=checkpoint_text(after),
                    created_at=created_at,
                )
            connection.commit()
        finally:
            connection.close()
        body = _frame_body(
            sequence=sequence,
            scope=scope,
            epoch=after.operational_epoch,
            operation_id=operation_id,
            reservation_id=reservation_id,
            record_digest=digest,
            after=after,
            evidence=evidence,
            terminal_state=terminal_state,
            previous=previous,
            nxt=nxt,
            challenge=challenge,
        )
        append_witness_frame(self.witness_dir, body)
        extend_if_needed(self.anchor, previous, nxt, raw_digest(digest))
        connection = _connect(self.database)
        try:
            _ = connection.execute("BEGIN IMMEDIATE")
            _insert_evidence_rows(connection, scope, evidence, operation_id, created_at)
            _upsert_scope(connection, scope, after, sequence, created_at)
            if record.get("kind") in {"internal_auto_policy", "unapplied_processor_cancellation"}:
                save_checkpoint(
                    connection,
                    scope.workspace_id,
                    after,
                    Checkpoint.model_validate(
                        record.get("processor_checkpoint_before"), strict=True
                    ),
                )
            if record.get("kind") == "unapplied_processor_cancellation":
                _consume_cancelled_auto_reserve(connection, scope, operation_id)
            if phase == "finish" and evidence_digest is not None and terminal_state is not None:
                _finish_operation(
                    connection,
                    scope=scope,
                    operation_id=operation_id,
                    expected_json=expected_json,
                    evidence_digest=evidence_digest,
                    terminal_state=terminal_state,
                    finished_json=checkpoint_text(after),
                    finished_at=created_at,
                )
            _ = connection.execute(
                "INSERT INTO company_freshness_publication(global_sequence, published_at) VALUES (?, ?)",
                (sequence, created_at),
            )
            connection.commit()
        finally:
            connection.close()

    def _audit_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        allow_policy_update: bool = False,
        allow_approval_revocation: bool = False,
    ) -> tuple[list[JournalEntry], list[CachedOperation], list[JsonObject]]:
        self._require_anchor_pin()
        live = self.anchor.read_value()
        journal = load_journal(connection)
        unpublished_frame = None
        if journal and journal[-1].published_sequence is None:
            entry = journal[-1]
            # A torn append cannot have extended the anchor. Never discard
            # bytes committed by NV or a publication, even at the final frame.
            if live.hex() == entry.previous_nv:
                transport = WitnessTransport.model_validate(
                    entry.record.get("transport"), strict=True
                )
                unpublished_frame = _frame_body(
                    sequence=entry.sequence,
                    scope=entry.scope,
                    epoch=entry.after.operational_epoch,
                    operation_id=entry.operation_id,
                    reservation_id=transport.reservation_id,
                    record_digest=entry.digest,
                    after=entry.after,
                    evidence=entry.evidence,
                    terminal_state=transport.terminal_state,
                    previous=bytes.fromhex(entry.previous_nv),
                    nxt=bytes.fromhex(entry.next_nv),
                    challenge=transport.challenge,
                )
        frames = read_witness_frames(self.witness_dir, unpublished_frame=unpublished_frame)
        entries = audit_journal(
            connection,
            frames,
            live,
            bytes.fromhex(self._registry().tpm.initial_value_hex),
        )
        require_scope_pins(self._registry(), entries)
        _ = approval_revocation_inventory(
            self._registry(), entries, allow_pending=allow_approval_revocation
        )
        if not allow_policy_update:
            require_current_auto_pins(self._registry(), entries)
        operations = audit_operation_cache(connection, entries)
        try:
            audit_owned_receipts(connection, entries, operations)
            audit_owned_pending(connection, entries, operations, self._registry())
            indexed = {
                (
                    item.scope.provider_instance_id,
                    item.scope.workspace_id,
                    item.row.operation_id,
                ): item.row
                for item in operations
            }
            for entry in entries:
                if entry.phase != "finish" or entry.record.get("terminal_state") == "cancelled":
                    continue
                original = indexed.get(
                    (entry.scope.provider_instance_id, entry.scope.workspace_id, entry.operation_id)
                )
                if (
                    original is not None
                    and original.actor_store == "second_brain"
                    and original.operation == "complete"
                ):
                    digest = entry.record.get("evidence_digest")
                    if not isinstance(digest, str):
                        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
                    _verify_internal_effect(
                        connection,
                        entry.scope,
                        original.operation_id,
                        original.event_digest,
                        digest,
                        self._registry(),
                        reclassify=False,
                    )
        except (EvidenceRejected, ValueError) as exc:
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
        return entries, operations, frames

    def _recover(
        self,
        *,
        allow_policy_update: bool = False,
        read_only: bool = False,
        allow_approval_revocation: bool = False,
    ) -> None:
        if not migration_applied(self.database, "freshness"):
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        connection = _connect(self.database)
        try:
            entries, operations, frames = self._audit_snapshot(
                connection,
                allow_policy_update=allow_policy_update,
                allow_approval_revocation=allow_approval_revocation,
            )
            if read_only:
                return
            prepared_finish = (
                entries[-1]
                if entries
                and entries[-1].phase == "finish"
                and entries[-1].published_sequence is None
                else None
            )
            cancellations: dict[tuple[str, str, str | None], JournalEntry] = {}
            for entry in entries:
                if entry.record.get("kind") == "unapplied_processor_cancellation":
                    key = (
                        entry.scope.provider_instance_id,
                        entry.scope.workspace_id,
                        entry.operation_id,
                    )
                    if key in cancellations:
                        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                    cancellations[key] = entry
            for item in operations:
                original = item.row
                cancellation = cancellations.get(
                    (
                        item.scope.provider_instance_id,
                        item.scope.workspace_id,
                        original.operation_id,
                    )
                )
                if cancellation is not None:
                    verified = _verify_unapplied_cancellation(
                        connection, item.scope, original, cancellation.record
                    )
                    if cancellation.record.get("evidence_digest") != verified.source_digest:
                        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                    continue
                pending_original = (
                    prepared_finish
                    if prepared_finish is not None
                    and prepared_finish.operation_id == original.operation_id
                    and prepared_finish.scope == item.scope
                    else None
                )
                if original.actor_store == "second_brain" and (
                    original.state == "finished" or pending_original is not None
                ):
                    evidence_digest = original.evidence_digest
                    terminal_state = original.terminal_state
                    if pending_original is not None:
                        if pending_original.before is None:
                            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                        pending_request = FinishProgressRequest.model_validate(
                            {
                                "schema_version": 2,
                                "scope": scope_object(item.scope),
                                "operation_id": original.operation_id,
                                "reservation_id": original.reservation_id,
                                "expected_checkpoint": checkpoint_object(pending_original.before),
                                "evidence_digest": pending_original.record.get("evidence_digest"),
                                "terminal_state": pending_original.record.get("terminal_state"),
                                "challenge": "recovery",
                            }
                        )
                        evidence_digest = pending_request.evidence_digest
                        terminal_state = pending_request.terminal_state
                        if terminal_state != TERMINAL_STATE_BY_OPERATION[original.operation]:
                            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                    if evidence_digest is None or terminal_state is None:
                        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                    if original.operation == "delete":
                        _ = verify_original_deletion(
                            self._registry(),
                            item.scope,
                            original.operation_id,
                            original.event_digest,
                            evidence_digest,
                        )
                    elif original.operation == "complete":
                        _ = _verify_internal_effect(
                            connection,
                            item.scope,
                            original.operation_id,
                            original.event_digest,
                            evidence_digest,
                            self._registry(),
                        )
                    else:
                        _ = self.verifier.verify(
                            connection,
                            scope=item.scope,
                            actor_store="second_brain",
                            operation=original.operation,
                            operation_id=original.operation_id,
                            event_digest=original.event_digest,
                            evidence_digest=evidence_digest,
                            terminal_state=terminal_state,
                        )
            jarvis_operations = {
                (
                    item.scope.provider_instance_id,
                    item.scope.workspace_id,
                    item.row.operation_id,
                ): item.row
                for item in operations
                if item.row.actor_store == "jarvis"
            }
            for entry in entries:
                if entry.phase != "finish":
                    continue
                original = jarvis_operations.get(
                    (entry.scope.provider_instance_id, entry.scope.workspace_id, entry.operation_id)
                )
                if original is None:
                    continue
                if entry.before is None:
                    raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                recovered = JarvisRecoveryEvidence.model_validate_json(
                    canonical_bytes(entry.record.get("jarvis_evidence")), strict=True
                )
                request = FinishProgressRequest.model_validate(
                    {
                        "schema_version": 2,
                        "scope": scope_object(entry.scope),
                        "operation_id": entry.operation_id,
                        "reservation_id": original.reservation_id,
                        "expected_checkpoint": checkpoint_object(entry.before),
                        "evidence_digest": entry.record.get("evidence_digest"),
                        "terminal_state": entry.record.get("terminal_state"),
                        "challenge": "recovery",
                    }
                )
                _ = _verify_sidecar(
                    connection,
                    recovered.sidecar,
                    request,
                    original,
                    recovered.context,
                    recovered.policy,
                )
            row = _unpublished_row(connection)
        finally:
            connection.close()
        if row is None:
            return
        sequences: set[int] = set()
        for item in frames:
            sequence = item.get("global_sequence")
            if isinstance(sequence, int):
                sequences.add(sequence)
        if row.sequence not in sequences:
            append_witness_frame(self.witness_dir, row.frame)
        extend_if_needed(self.anchor, row.previous, row.nxt, raw_digest(row.digest))
        connection = _connect(self.database)
        try:
            _ = connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM company_freshness_publication WHERE global_sequence = ?",
                    (row.sequence,),
                ).fetchone()
                is None
            ):
                _insert_evidence_rows(
                    connection, row.scope, row.evidence, row.operation_id, row.created_at
                )
                _upsert_scope(connection, row.scope, row.after, row.sequence, row.created_at)
                original = entries[-1]
                if original.phase == "bootstrap":
                    _seed_bootstrap_checkpoint(connection, row.scope, row.after)
                if original.record.get("kind") in {
                    "internal_auto_policy",
                    "unapplied_processor_cancellation",
                }:
                    save_checkpoint(
                        connection,
                        row.scope.workspace_id,
                        row.after,
                        Checkpoint.model_validate(
                            original.record.get("processor_checkpoint_before"), strict=True
                        ),
                    )
                if original.phase == "finish":
                    record = original.record
                    if record.get("kind") == "unapplied_processor_cancellation":
                        _consume_cancelled_auto_reserve(connection, row.scope, row.operation_id)
                    reservation_id = record.get("reservation_id")
                    evidence_digest = record.get("evidence_digest")
                    terminal_state = record.get("terminal_state")
                    if (
                        original.before is None
                        or not isinstance(reservation_id, str)
                        or not isinstance(evidence_digest, str)
                        or not isinstance(terminal_state, str)
                    ):
                        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
                    _finish_operation(
                        connection,
                        scope=row.scope,
                        operation_id=row.operation_id,
                        expected_json=checkpoint_text(original.before),
                        evidence_digest=evidence_digest,
                        terminal_state=terminal_state,
                        finished_json=checkpoint_text(row.after),
                        finished_at=row.created_at,
                    )
                _ = connection.execute(
                    "INSERT INTO company_freshness_publication(global_sequence, published_at) VALUES (?, ?)",
                    (row.sequence, row.created_at),
                )
            connection.commit()
        finally:
            connection.close()

    def _require_anchor_pin(self) -> None:
        registry = self._registry()
        if registry.tpm.nv_handle != NV_HANDLE or registry.tpm.name_alg != NV_NAME_ALG:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        if registry.tpm.identity != self.anchor.identity():
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        if bytes.fromhex(registry.tpm.public_name_hex) != self.anchor.public_name():
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

    def _registry(self) -> FreshnessRegistry:
        require_trusted_file(self.registry_path, mode=0o644)
        try:
            registry = FreshnessRegistry.model_validate_json(
                self.registry_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError) as exc:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED") from exc
        if registry.registry_id != self.registry_id:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        return registry

    def _installation(self, installation_id: str) -> bool:
        try:
            return self._registry().installation_id == installation_id
        except AnchorRejected:
            return False

    def _pinned(self, scope: FreshnessScope) -> bool:
        try:
            return any(_scope_matches(pin, scope) for pin in self._registry().scopes)
        except AnchorRejected:
            return False

    def _ready_scope(self, scope: FreshnessScope) -> bool:
        return (
            migration_applied(self.database, "freshness")
            and self._pinned(scope)
            and self._head(scope) is not None
            and not self._closed(scope)
            and not self._unpublished()
        )

    def _head(self, scope: FreshnessScope) -> Checkpoint | None:
        connection = _connect(self.database)
        try:
            row = cast(
                tuple[str] | None,
                connection.execute(
                    """SELECT checkpoint_json FROM company_freshness_scopes
                   WHERE provider_instance_id = ? AND workspace_id = ?""",
                    (scope.provider_instance_id, scope.workspace_id),
                ).fetchone(),
            )
        except sqlite3.Error:
            return None
        finally:
            connection.close()
        if row is None:
            return None
        return Checkpoint.model_validate_json(str(row[0]))

    def _require_head(self, scope: FreshnessScope) -> Checkpoint:
        head = self._head(scope)
        if head is None:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        return head

    def _pending(self, scope: FreshnessScope) -> bool:
        connection = _connect(self.database)
        try:
            row = cast(
                tuple[int] | None,
                connection.execute(
                    """SELECT 1 FROM company_freshness_operations
                   WHERE provider_instance_id = ? AND workspace_id = ? AND state = 'reserved'""",
                    (scope.provider_instance_id, scope.workspace_id),
                ).fetchone(),
            )
            return row is not None
        finally:
            connection.close()

    def _other_pending(self, scope: FreshnessScope, operation_id: str) -> bool:
        connection = _connect(self.database)
        try:
            row = cast(
                tuple[int] | None,
                connection.execute(
                    """SELECT 1 FROM company_freshness_operations
                   WHERE provider_instance_id = ? AND workspace_id = ? AND state = 'reserved'
                     AND operation_id != ?""",
                    (scope.provider_instance_id, scope.workspace_id, operation_id),
                ).fetchone(),
            )
            return row is not None
        finally:
            connection.close()

    def _unpublished(self) -> bool:
        connection = _connect(self.database)
        try:
            return _unpublished_row(connection) is not None
        finally:
            connection.close()

    def _closed(self, scope: FreshnessScope) -> bool:
        connection = _connect(self.database)
        try:
            rows: list[tuple[str]] = connection.execute(
                """SELECT record_json FROM company_freshness_log
                   WHERE provider_instance_id = ? AND workspace_id = ?
                     AND phase IN ('registry','finish')""",
                (scope.provider_instance_id, scope.workspace_id),
            ).fetchall()
        except sqlite3.Error:
            return False
        finally:
            connection.close()
        for row in rows:
            loaded = strict_loads(row[0], 1_048_576)
            if isinstance(loaded, dict) and loaded.get("closed") is True:
                return True
        return False

    def _operation(self, scope: FreshnessScope, operation_id: str) -> _OperationRow | None:
        connection = _connect(self.database)
        try:
            rows: list[tuple[str]] = connection.execute(
                """SELECT json_object(
                    'operation_id',operation_id,'operation',operation,'actor_store',actor_store,
                    'event_digest',event_digest,'reservation_id',reservation_id,
                    'reserve_expected_json',reserve_expected_json,
                    'reserved_checkpoint_json',reserved_checkpoint_json,'state',state,
                    'finish_expected_json',finish_expected_json,'evidence_digest',evidence_digest,
                    'terminal_state',terminal_state,'finished_checkpoint_json',finished_checkpoint_json)
                FROM company_freshness_operations
                   WHERE provider_instance_id = ? AND workspace_id = ? AND operation_id = ?""",
                (scope.provider_instance_id, scope.workspace_id, operation_id),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return None
        return _OperationRow.model_validate_json(rows[0][0], strict=True)

    def _operation_by_reservation(
        self, scope: FreshnessScope, reservation_id: str
    ) -> _OperationRow | None:
        connection = _connect(self.database)
        try:
            row = cast(
                tuple[str] | None,
                connection.execute(
                    """SELECT operation_id FROM company_freshness_operations
                   WHERE provider_instance_id = ? AND workspace_id = ? AND reservation_id = ?""",
                    (scope.provider_instance_id, scope.workspace_id, reservation_id),
                ).fetchone(),
            )
        finally:
            connection.close()
        if row is None:
            return None
        return self._operation(scope, str(row[0]))

    def _next_sequence(self) -> int:
        connection = _connect(self.database)
        try:
            row = cast(
                tuple[int] | None,
                connection.execute(
                    "SELECT COALESCE(MAX(global_sequence), 0) FROM company_freshness_log"
                ).fetchone(),
            )
        finally:
            connection.close()
        return int(row[0]) + 1 if row is not None else 1

    def _challenge_replay(self, challenge: str, operation_id: str) -> bool:
        if not self.witness_dir.exists():
            return False
        try:
            frames = read_witness_frames(self.witness_dir)
        except AnchorRejected:
            return True
        for frame in frames:
            if frame.get("challenge") == challenge and frame.get("operation_id") != operation_id:
                return True
        return False

    def _deletion_fence_safe(
        self, scope: FreshnessScope, source_fence: int, source_root: str
    ) -> bool:
        pin = _pin(self._registry(), scope)
        return (
            pin.source_deletion_sequence == source_fence and pin.source_deletion_root == source_root
        )

    def bootstrap_scope(
        self,
        *,
        scope: FreshnessScope,
        approval_policy_version: int,
        approval_binding_digest: str,
        inventory: GenesisInventory,
        now: str,
    ) -> Checkpoint:
        with self._locked():
            pin = _pin(self._registry(), scope)
            self._recover()
            if self._head(scope) is not None:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            if len(self.anchor.read_value()) != 32:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            if _history_present(self.database, scope):
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            connection = _connect(self.database)
            try:
                default_transition_receipts = verify_owned_genesis(
                    connection,
                    scope,
                    inventory,
                    exact=True,
                    approval_binding_digest=approval_binding_digest,
                )
            finally:
                connection.close()
            checkpoint = _genesis_checkpoint(
                scope,
                approval_policy_version=approval_policy_version,
                approval_binding_digest=approval_binding_digest,
                inventory=inventory,
            )
            if checkpoint.intent_root != pin.genesis_digest or pin.epoch != 1:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
            record: JsonObject = {
                "phase": "bootstrap",
                "epoch": 1,
                "inventory": model_object(inventory),
                "default_transition_receipts": default_transition_receipts,
                "source_deletion_sequence": pin.source_deletion_sequence,
                "source_deletion_root": pin.source_deletion_root,
                "source_context_digest": pin.source_context_digest,
                "transport": {
                    "challenge": "bootstrap",
                    "reservation_id": None,
                    "terminal_state": None,
                },
            }
            previous = self.anchor.read_value()
            sequence = self._next_sequence()
            digest = record_digest(
                global_sequence=sequence,
                scope=scope,
                phase="bootstrap",
                record=record,
                evidence=[],
                before_checkpoint=None,
                after_checkpoint=checkpoint,
            )
            nxt = next_nv(previous, digest)
            connection = _connect(self.database)
            try:
                _ = connection.execute("BEGIN IMMEDIATE")
                _ = connection.execute(
                    """INSERT INTO company_freshness_epochs(
                        provider_instance_id, workspace_id, epoch, previous_epoch,
                        previous_checkpoint_digest, genesis_json, registry_binding_digest, created_at
                    ) VALUES (?, ?, 1, NULL, NULL, ?, ?, ?)""",
                    (
                        scope.provider_instance_id,
                        scope.workspace_id,
                        checkpoint_text(checkpoint),
                        pin.genesis_digest,
                        now,
                    ),
                )
                _insert_log(
                    connection,
                    sequence=sequence,
                    scope=scope,
                    phase="bootstrap",
                    operation_id=None,
                    record=record,
                    evidence=[],
                    digest=digest,
                    previous=previous,
                    nxt=nxt,
                    before=None,
                    after=checkpoint,
                    created_at=now,
                )
                connection.commit()
            finally:
                connection.close()
            append_witness_frame(
                self.witness_dir,
                _frame_body(
                    sequence=sequence,
                    scope=scope,
                    epoch=1,
                    operation_id=None,
                    reservation_id=None,
                    record_digest=digest,
                    after=checkpoint,
                    evidence=[],
                    terminal_state=None,
                    previous=previous,
                    nxt=nxt,
                    challenge="bootstrap",
                ),
            )
            extend_if_needed(self.anchor, previous, nxt, raw_digest(digest))
            connection = _connect(self.database)
            try:
                _ = connection.execute("BEGIN IMMEDIATE")
                _upsert_scope(connection, scope, checkpoint, sequence, now)
                _seed_bootstrap_checkpoint(connection, scope, checkpoint)
                _ = connection.execute(
                    "INSERT INTO company_freshness_publication(global_sequence, published_at) VALUES (?, ?)",
                    (sequence, now),
                )
                connection.commit()
            finally:
                connection.close()
            return checkpoint

    @contextmanager
    def _locked(self) -> Generator[None, None, None]:
        require_trusted_file(self.lock_path, mode=0o600)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def bootstrap_company_scope(
    *,
    database: Path,
    registry_path: Path,
    witness_dir: Path,
    lock_path: Path,
    anchor: NvAnchor,
    registry_id: str,
    scope: FreshnessScope,
    approval_policy_version: int,
    approval_binding_digest: str,
    inventory: GenesisInventory,
    now: str,
    caller_checkpoint: Checkpoint | None = None,
) -> Checkpoint:
    del caller_checkpoint
    if not migration_applied(database, "freshness"):
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    provider = CompanyDbFreshnessProvider(
        database=database,
        actor_store="second_brain",
        registry_path=registry_path,
        witness_dir=witness_dir,
        lock_path=lock_path,
        anchor=anchor,
        registry_id=registry_id,
        clock=lambda: now,
    )
    return provider.bootstrap_scope(
        scope=scope,
        approval_policy_version=approval_policy_version,
        approval_binding_digest=approval_binding_digest,
        inventory=inventory,
        now=now,
    )


@dataclass(frozen=True, slots=True)
class _Prepared:
    sequence: int
    scope: FreshnessScope
    operation_id: str
    digest: str
    previous: bytes
    nxt: bytes
    evidence: list[JsonObject]
    after: Checkpoint
    created_at: str
    frame: JsonObject


def _clock() -> str:
    return format_instant(datetime.now(UTC))


def _wire_error() -> FreshnessWireError:
    return FreshnessWireError(schema_version=2, outcome="error", code="COMPANY_FRESHNESS_REQUIRED")


def _read(
    request: ReadFreshnessRequest,
    status: Literal["ready", "mismatch", "unavailable", "uncertain"],
    head: Checkpoint | None,
) -> ReadFreshnessResponse:
    checkpoint = head if status == "ready" else None
    return ReadFreshnessResponse(
        schema_version=2,
        scope=request.scope,
        challenge=request.challenge,
        status=status,
        checkpoint=checkpoint,
    )


def _read_status(
    request: ReadFreshnessRequest,
    head: Checkpoint,
    actor_store: ActorStore,
    database: Path,
) -> Literal["ready", "mismatch"]:
    observed = request.observed_checkpoint
    if observed is None or observed == head:
        return "ready" if observed == head else "mismatch"
    if not _own_unchanged(observed, head, actor_store):
        return "mismatch"
    if not _other_proven(database, request.scope, observed, head, actor_store):
        return "mismatch"
    return "ready"


def _own_unchanged(observed: Checkpoint, head: Checkpoint, actor_store: ActorStore) -> bool:
    if (
        observed.operational_epoch != head.operational_epoch
        or observed.approval_policy_version != head.approval_policy_version
        or observed.approval_binding_digest != head.approval_binding_digest
        or observed.revocation_sequence != head.revocation_sequence
        or observed.revocation_root != head.revocation_root
    ):
        return False
    match actor_store:
        case "second_brain":
            return observed.stores.second_brain == head.stores.second_brain
        case "jarvis":
            return observed.stores.jarvis == head.stores.jarvis


def _other_proven(
    database: Path,
    scope: FreshnessScope,
    observed: Checkpoint,
    head: Checkpoint,
    actor_store: ActorStore,
) -> bool:
    if not _own_unchanged(observed, head, actor_store):
        return False
    connection = _connect(database)
    try:
        rows: list[tuple[str]] = connection.execute(
            """SELECT l.after_checkpoint_json FROM company_freshness_log l
               JOIN company_freshness_publication p
                 ON p.global_sequence = l.global_sequence
               WHERE l.provider_instance_id = ? AND l.workspace_id = ?
               ORDER BY l.global_sequence""",
            (scope.provider_instance_id, scope.workspace_id),
        ).fetchall()
    finally:
        connection.close()
    # The whole checkpoint must have existed, including the intent root and
    # zero-height roots. Independently valid stream heights are not a prefix.
    return any(Checkpoint.model_validate_json(row[0], strict=True) == observed for row in rows)


def _conflict_reserve(request: ReserveProgressRequest) -> ReserveProgressResponse:
    return ReserveProgressResponse(
        schema_version=2,
        scope=request.scope,
        challenge=request.challenge,
        outcome="conflict",
        checkpoint=None,
        reservation_id=None,
    )


def _reserved(
    request: ReserveProgressRequest,
    outcome: Literal["reserved", "already_reserved"],
    checkpoint: Checkpoint,
    reservation_id: str,
) -> ReserveProgressResponse:
    return ReserveProgressResponse(
        schema_version=2,
        scope=request.scope,
        challenge=request.challenge,
        outcome=outcome,
        checkpoint=checkpoint,
        reservation_id=reservation_id,
    )


def _conflict_finish(request: FinishProgressRequest) -> FinishProgressResponse:
    return FinishProgressResponse(
        schema_version=2,
        scope=request.scope,
        challenge=request.challenge,
        outcome="conflict",
        checkpoint=None,
    )


def _finished(
    request: FinishProgressRequest,
    outcome: Literal["recorded", "already_recorded"],
    checkpoint: Checkpoint,
) -> FinishProgressResponse:
    return FinishProgressResponse(
        schema_version=2,
        scope=request.scope,
        challenge=request.challenge,
        outcome=outcome,
        checkpoint=checkpoint,
    )


def _same_reserve(existing: _OperationRow, request: ReserveProgressRequest) -> bool:
    return (
        existing.operation == request.operation
        and existing.event_digest == request.event_digest
        and existing.reserve_expected_json == checkpoint_text(request.expected_checkpoint)
    )


def _advance_intent(head: Checkpoint, record: JsonObject) -> Checkpoint:
    sequence = head.intent_sequence + 1
    return head.model_copy(
        update={
            "intent_sequence": sequence,
            "intent_root": progress_root(head.intent_root, sequence, record),
        },
    )


def _reserve_evidence(
    request: ReserveProgressRequest,
    actor_store: ActorStore,
    before: Checkpoint,
    after: Checkpoint,
    deletion_intent: VerifiedEvidence | None = None,
) -> list[JsonObject]:
    if request.operation != "delete":
        return []
    if deletion_intent is None:
        raise EvidenceRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
    projection = _stream_projection(
        request.scope,
        actor_store,
        "deletion",
        before.stores.second_brain.deletion_root
        if actor_store == "second_brain"
        else before.stores.jarvis.deletion_root,
        (
            before.stores.second_brain if actor_store == "second_brain" else before.stores.jarvis
        ).deletion_sequence
        + 1,
        deletion_intent.source_record_id + ":intent",
        deletion_intent.source_digest,
        deletion_intent.metadata | {"original_at": deletion_intent.original_at, "kind": "intent"},
    )
    del after
    return [projection]


def _apply_finish(
    head: Checkpoint,
    record: JsonObject,
    actor_store: ActorStore,
    evidence: list[JsonObject],
) -> Checkpoint:
    advanced = _advance_intent(head, record)
    current = (
        advanced.stores.second_brain if actor_store == "second_brain" else advanced.stores.jarvis
    )
    updated = current
    for item in evidence:
        stream = item["stream"]
        root = str(item["root"])
        sequence = int(str(item["sequence"]))
        match stream:
            case "receipt":
                updated = updated.model_copy(
                    update={"receipt_sequence": sequence, "receipt_root": root}
                )
            case "terminal":
                updated = updated.model_copy(
                    update={"terminal_sequence": sequence, "terminal_root": root}
                )
            case "deletion":
                updated = updated.model_copy(
                    update={"deletion_sequence": sequence, "deletion_root": root}
                )
            case _:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    match actor_store:
        case "second_brain":
            stores = advanced.stores.model_copy(update={"second_brain": updated})
        case "jarvis":
            stores = advanced.stores.model_copy(update={"jarvis": updated})
    return advanced.model_copy(update={"stores": stores})


def _finish_evidence(
    scope: FreshnessScope,
    operation: ProgressOperation,
    actor_store: ActorStore,
    head: Checkpoint,
    verified: VerifiedEvidence,
    terminal_state: ProgressTerminalState,
) -> list[JsonObject]:
    store = head.stores.second_brain if actor_store == "second_brain" else head.stores.jarvis
    rows: list[JsonObject] = (
        []
        if terminal_state == "cancelled"
        else [
            _stream_projection(
                scope,
                actor_store,
                "receipt",
                store.receipt_root,
                store.receipt_sequence + 1,
                verified.source_record_id,
                verified.source_digest,
                verified.metadata | {"original_at": verified.original_at},
            ),
        ]
    )
    if operation in _TERMINAL_OPS or terminal_state == "cancelled":
        rows.append(
            _stream_projection(
                scope,
                actor_store,
                "terminal",
                store.terminal_root,
                store.terminal_sequence + 1,
                verified.source_record_id,
                verified.source_digest,
                verified.metadata | {"original_at": verified.original_at},
            ),
        )
    if operation == "delete":
        rows.append(
            _stream_projection(
                scope,
                actor_store,
                "deletion",
                store.deletion_root,
                store.deletion_sequence + 1,
                verified.source_record_id + ":complete",
                verified.source_digest,
                verified.metadata | {"original_at": verified.original_at, "kind": "complete"},
            ),
        )
    return rows


def _stream_projection(
    scope: FreshnessScope,
    store: str,
    stream: str,
    previous_root: str,
    sequence: int,
    source_record_id: str,
    source_digest: str,
    metadata: JsonObject,
) -> JsonObject:
    root = evidence_root(
        scope, store, stream, previous_root, sequence, source_record_id, source_digest
    )
    return {
        "store": store,
        "stream": stream,
        "sequence": sequence,
        "root": root,
        "previous_root": previous_root,
        "source_record_id": source_record_id,
        "source_digest": source_digest,
        "metadata": metadata,
    }


def _frame_body(
    *,
    sequence: int,
    scope: FreshnessScope,
    epoch: int,
    operation_id: str | None,
    reservation_id: str | None,
    record_digest: str,
    after: Checkpoint,
    evidence: list[JsonObject],
    terminal_state: str | None,
    previous: bytes,
    nxt: bytes,
    challenge: str,
) -> JsonObject:
    evidence_value: list[JsonValue] = []
    evidence_value.extend(evidence)
    return {
        "global_sequence": sequence,
        "scope": scope_object(scope),
        "epoch": epoch,
        "operation_id": operation_id,
        "reservation_id": reservation_id,
        "record_digest": record_digest,
        "checkpoint_digest": prefixed_digest(
            b"second-brain/company-db-checkpoint/v1\0", checkpoint_object(after)
        ),
        "evidence_digest": prefixed_digest(
            b"second-brain/company-db-evidence-set/v1\0", evidence_value
        ),
        "terminal_state": terminal_state,
        "previous_nv": previous.hex(),
        "next_nv": nxt.hex(),
        "challenge": challenge,
    }


def _insert_log(
    connection: sqlite3.Connection,
    *,
    sequence: int,
    scope: FreshnessScope,
    phase: str,
    operation_id: str | None,
    record: JsonObject,
    evidence: list[JsonObject],
    digest: str,
    previous: bytes,
    nxt: bytes,
    before: Checkpoint | None,
    after: Checkpoint,
    created_at: str,
) -> None:
    evidence_value: list[JsonValue] = []
    evidence_value.extend(evidence)
    _ = connection.execute(
        """INSERT INTO company_freshness_log(
            global_sequence, provider_instance_id, workspace_id, phase, operation_id,
            record_json, evidence_json, record_digest, previous_nv, next_nv,
            before_checkpoint_json, after_checkpoint_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sequence,
            scope.provider_instance_id,
            scope.workspace_id,
            phase,
            operation_id,
            canonical_bytes(record).decode("utf-8"),
            canonical_bytes(evidence_value).decode("utf-8"),
            digest,
            previous.hex(),
            nxt.hex(),
            checkpoint_text(before),
            checkpoint_text(after),
            created_at,
        ),
    )


def _insert_operation(
    connection: sqlite3.Connection,
    *,
    scope: FreshnessScope,
    operation_id: str,
    operation: str,
    actor_store: str,
    event_digest: str,
    reservation_id: str,
    expected_json: str,
    reserved_json: str,
    created_at: str,
) -> None:
    _ = connection.execute(
        """INSERT INTO company_freshness_operations(
            provider_instance_id, workspace_id, operation_id, operation, actor_store,
            event_digest, reservation_id, reserve_expected_json, reserved_checkpoint_json,
            state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            operation_id,
            operation,
            actor_store,
            event_digest,
            reservation_id,
            expected_json,
            reserved_json,
            created_at,
        ),
    )


def _finish_operation(
    connection: sqlite3.Connection,
    *,
    scope: FreshnessScope,
    operation_id: str,
    expected_json: str,
    evidence_digest: str,
    terminal_state: str,
    finished_json: str,
    finished_at: str,
) -> None:
    cursor = connection.execute(
        """UPDATE company_freshness_operations
           SET state = 'finished', finish_expected_json = ?, evidence_digest = ?,
               terminal_state = ?, finished_checkpoint_json = ?, finished_at = ?
           WHERE provider_instance_id = ? AND workspace_id = ? AND operation_id = ?
             AND state = 'reserved'""",
        (
            expected_json,
            evidence_digest,
            terminal_state,
            finished_json,
            finished_at,
            scope.provider_instance_id,
            scope.workspace_id,
            operation_id,
        ),
    )
    if cursor.rowcount != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _upsert_scope(
    connection: sqlite3.Connection,
    scope: FreshnessScope,
    checkpoint: Checkpoint,
    sequence: int,
    created_at: str,
) -> None:
    text = checkpoint_text(checkpoint)
    digest = prefixed_digest(
        b"second-brain/company-db-checkpoint/v1\0", checkpoint_object(checkpoint)
    )
    existing = cast(
        tuple[str] | None,
        connection.execute(
            """SELECT checkpoint_digest FROM company_freshness_scopes
           WHERE provider_instance_id = ? AND workspace_id = ?""",
            (scope.provider_instance_id, scope.workspace_id),
        ).fetchone(),
    )
    if existing is None:
        _ = connection.execute(
            """INSERT INTO company_freshness_scopes(
                provider_instance_id, workspace_id, epoch, checkpoint_json, checkpoint_digest,
                last_global_sequence, initialized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                checkpoint.operational_epoch,
                text,
                digest,
                sequence,
                created_at,
            ),
        )
        return
    cursor = connection.execute(
        """UPDATE company_freshness_scopes
           SET epoch = ?, checkpoint_json = ?, checkpoint_digest = ?, last_global_sequence = ?
           WHERE provider_instance_id = ? AND workspace_id = ? AND checkpoint_digest = ?""",
        (
            checkpoint.operational_epoch,
            text,
            digest,
            sequence,
            scope.provider_instance_id,
            scope.workspace_id,
            str(existing[0]),
        ),
    )
    if cursor.rowcount != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")


def _insert_evidence_rows(
    connection: sqlite3.Connection,
    scope: FreshnessScope,
    evidence: list[JsonObject],
    operation_id: str,
    created_at: str,
) -> None:
    for item in evidence:
        _ = connection.execute(
            """INSERT INTO company_freshness_evidence(
                provider_instance_id, workspace_id, store, stream, sequence, root, previous_root,
                operation_id, source_record_id, source_digest, evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                item["store"],
                item["stream"],
                item["sequence"],
                item["root"],
                item["previous_root"],
                operation_id,
                item["source_record_id"],
                item["source_digest"],
                canonical_bytes(item).decode("utf-8"),
                _original_at(item, created_at),
            ),
        )


def _unpublished_row(connection: sqlite3.Connection) -> _Prepared | None:
    unpublished = [entry for entry in load_journal(connection) if entry.published_sequence is None]
    if not unpublished:
        return None
    if len(unpublished) != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    entry = unpublished[0]
    transport = WitnessTransport.model_validate(entry.record.get("transport"), strict=True)
    previous = bytes.fromhex(entry.previous_nv)
    nxt = bytes.fromhex(entry.next_nv)
    created: list[tuple[str]] = connection.execute(
        "SELECT created_at FROM company_freshness_log WHERE global_sequence=?",
        (entry.sequence,),
    ).fetchall()
    if len(created) != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    frame = _frame_body(
        sequence=entry.sequence,
        scope=entry.scope,
        epoch=entry.after.operational_epoch,
        operation_id=entry.operation_id,
        reservation_id=transport.reservation_id,
        record_digest=entry.digest,
        after=entry.after,
        evidence=entry.evidence,
        terminal_state=transport.terminal_state,
        previous=previous,
        nxt=nxt,
        challenge=transport.challenge,
    )
    return _Prepared(
        sequence=entry.sequence,
        scope=entry.scope,
        operation_id=entry.operation_id or "",
        digest=entry.digest,
        previous=previous,
        nxt=nxt,
        evidence=entry.evidence,
        after=entry.after,
        created_at=created[0][0],
        frame=frame,
    )


def _seed_bootstrap_checkpoint(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    checkpoint: Checkpoint,
) -> None:
    _ = db.execute(
        """CREATE TABLE IF NOT EXISTS company_processor_checkpoint (
        workspace_id TEXT PRIMARY KEY,checkpoint_json TEXT NOT NULL)""",
    )
    rows: list[tuple[str]] = db.execute(
        "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
        (scope.workspace_id,),
    ).fetchall()
    raw = checkpoint_text(checkpoint)
    if rows:
        if rows[0][0] != raw:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
        return
    _ = db.execute(
        "INSERT INTO company_processor_checkpoint VALUES(?,?)",
        (scope.workspace_id, raw),
    )


def _history_present(database: Path, scope: FreshnessScope) -> bool:
    connection = _connect(database)
    try:
        tables = {
            str(row[0])
            for row in cast(
                list[tuple[str]],
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall(),
            )
        }
        for table in (
            "company_handoff_outbox",
            "company_handoff_decisions",
            "company_processor_pending_finish",
            "company_processor_checkpoint",
            "company_handoff_enrollment",
            "company_approver_enrollment_audit",
        ):
            if table not in tables:
                continue
            row = cast(
                tuple[int] | None,
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE workspace_id=? LIMIT 1",
                    (scope.workspace_id,),
                ).fetchone(),
            )
            if row is not None:
                return True
        return False
    finally:
        connection.close()


def _consume_cancelled_auto_reserve(
    connection: sqlite3.Connection, scope: FreshnessScope, operation_id: str | None
) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_internal_pending_reserve'"
        ).fetchone()
        is not None
    ):
        _ = connection.execute(
            """DELETE FROM company_internal_pending_reserve
            WHERE provider_instance_id=? AND workspace_id=?
              AND json_extract(intent_json,'$.request.operation_id')=?""",
            (scope.provider_instance_id, scope.workspace_id, operation_id),
        )


def _verify_unapplied_cancellation(
    connection: sqlite3.Connection,
    scope: FreshnessScope,
    original: _OperationRow,
    record: JsonObject,
) -> VerifiedEvidence:
    verify_auto_cancellation(connection, scope, original, record)
    binding = record.get("processor_binding")
    if binding is not None:
        if not isinstance(binding, dict):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        rows = connection.execute(
            """SELECT c.state,c.content_digest,h.command_digest FROM company_memory_candidates c
            JOIN company_handoff_outbox h ON h.workspace_id=c.workspace_id
              AND h.candidate_id=c.candidate_id
            WHERE c.workspace_id=? AND c.candidate_id=? AND h.request_id=?""",
            (scope.workspace_id, binding.get("candidate_id"), binding.get("handoff_id")),
        ).fetchall()
        expected_state = "accepted" if original.operation == "mark_processed" else "candidate"
        if (
            len(rows) != 1
            or rows[0][0] != expected_state
            or rows[0][1] != binding.get("content_digest")
            or original.operation_id
            != operation_id_for(
                scope,
                request_id=binding["handoff_id"],
                command_digest=rows[0][2],
                operation=original.operation,
            )
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        if (
            original.operation in {"accept", "reject"}
            and connection.execute(
                """SELECT 1 FROM company_memory_receipts WHERE workspace_id=? AND candidate_id=?
            AND operation IN ('accept','reject','mark_processed')""",
                (scope.workspace_id, binding.get("candidate_id")),
            ).fetchone()
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        if (
            original.operation in {"accept", "reject"}
            and connection.execute(
                "SELECT 1 FROM company_handoff_decisions WHERE workspace_id=? AND candidate_id=?",
                (scope.workspace_id, binding.get("candidate_id")),
            ).fetchone()
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        for table in ("company_processor_pending_finish", "company_internal_pending_finish"):
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                and connection.execute(
                    f"SELECT 1 FROM {table} WHERE workspace_id=?", (scope.workspace_id,)
                ).fetchone()
            ):
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
        for table, column in (
            ("company_internal_effects", "candidate_id"),
            ("company_internal_records", "source_candidate_id"),
        ):
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                and connection.execute(
                    f"SELECT 1 FROM {table} WHERE workspace_id=? AND {column}=?",
                    (scope.workspace_id, binding.get("candidate_id")),
                ).fetchone()
            ):
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    if (
        original.actor_store != "second_brain"
        or original.operation not in {"accept", "reject", "mark_processed", "complete"}
        or (original.operation == "complete" and record.get("auto_intent") is None)
        or record.get("operation_id") != original.operation_id
        or record.get("reservation_id") != original.reservation_id
        or record.get("event_digest") != original.event_digest
        or record.get("terminal_state") != "cancelled"
    ):
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    for table in (
        "company_memory_receipts",
        "company_processor_pending_finish",
        "company_internal_pending_finish",
    ):
        if (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is None
        ):
            if table != "company_internal_pending_finish":
                raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
            continue
        if (
            connection.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id=? AND request_digest=?",
                (scope.workspace_id, original.event_digest),
            ).fetchone()
            is not None
        ):
            raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_internal_effects'"
        ).fetchone()
        is not None
        and connection.execute(
            """SELECT 1 FROM company_internal_effects
        WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
            (scope.provider_instance_id, scope.workspace_id, original.operation_id),
        ).fetchone()
        is not None
    ):
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    instant = record.get("original_at")
    if not isinstance(instant, str):
        raise AnchorRejected("COMPANY_PROGRESS_UNCERTAIN")
    digest = prefixed_digest(
        b"second-brain/company-unapplied-cancellation/v1\0",
        {
            key: value
            for key, value in record.items()
            if key not in {"evidence_digest", "transport"}
        },
    )
    return VerifiedEvidence(
        source_record_id=original.operation_id,
        source_digest=digest,
        original_at=instant,
        metadata={"kind": "unapplied_processor_cancellation"},
    )


def _pin(registry: FreshnessRegistry, scope: FreshnessScope) -> RegistryScopePin:
    pins = [pin for pin in registry.scopes if _scope_matches(pin, scope)]
    if len(pins) != 1:
        raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")
    return pins[0]


def _scope_matches(pin: RegistryScopePin, scope: FreshnessScope) -> bool:
    return (
        pin.provider_instance_id == scope.provider_instance_id
        and pin.workspace_id == scope.workspace_id
    )


def _genesis_checkpoint(
    scope: FreshnessScope,
    approval_policy_version: int,
    approval_binding_digest: str,
    inventory: GenesisInventory,
) -> Checkpoint:
    jarvis = _genesis_store(
        inventory.jarvis_receipts,
        inventory.jarvis_terminals,
        inventory.jarvis_deletions,
        scope,
        "jarvis",
    )
    second = _genesis_store(
        inventory.second_brain_receipts,
        inventory.second_brain_terminals,
        inventory.second_brain_deletions,
        scope,
        "second_brain",
    )
    revocation = _entry_root(scope, "registry", "revocation", inventory.revocations)
    stores_json: JsonObject = {"jarvis": _store_json(jarvis), "second_brain": _store_json(second)}
    intent = genesis_intent_root(
        scope,
        operational_epoch=1,
        approval_policy_version=approval_policy_version,
        approval_binding_digest=approval_binding_digest,
        revocation_sequence=len(inventory.revocations),
        revocation_root=revocation,
        stores=stores_json,
    )
    return Checkpoint(
        operational_epoch=1,
        approval_policy_version=approval_policy_version,
        approval_binding_digest=approval_binding_digest,
        revocation_sequence=len(inventory.revocations),
        revocation_root=revocation,
        stores=StoreHeads(jarvis=jarvis, second_brain=second),
        intent_sequence=0,
        intent_root=intent,
    )


def _genesis_store(
    receipts: list[GenesisEntry],
    terminals: list[GenesisEntry],
    deletions: list[GenesisEntry],
    scope: FreshnessScope,
    store: str,
) -> StoreProgress:
    return StoreProgress(
        receipt_sequence=len(receipts),
        receipt_root=_entry_root(scope, store, "receipt", receipts),
        terminal_sequence=len(terminals),
        terminal_root=_entry_root(scope, store, "terminal", terminals),
        deletion_sequence=len(deletions),
        deletion_root=_entry_root(scope, store, "deletion", deletions),
    )


def _entry_root(scope: FreshnessScope, store: str, stream: str, entries: list[GenesisEntry]) -> str:
    ordered = sorted(entries, key=lambda item: item.source_record_id)
    listed: list[JsonObject] = []
    for item in ordered:
        listed.append(
            {
                "source_record_id": item.source_record_id,
                "source_digest": item.source_digest,
                "original_at": item.original_at,
                "metadata": item.metadata,
            },
        )
    return genesis_stream_root(scope, store, stream, listed)


def _store_json(store: StoreProgress) -> JsonObject:
    return store.model_dump(mode="json")


def preview_genesis_checkpoint(
    scope: FreshnessScope,
    *,
    approval_policy_version: int,
    approval_binding_digest: str,
    inventory: GenesisInventory,
) -> Checkpoint:
    return _genesis_checkpoint(
        scope,
        approval_policy_version,
        approval_binding_digest,
        inventory,
    )


def auto_receipt_digest(body: JsonObject) -> str:
    return prefixed_digest(b"second-brain/company-auto-policy-receipt/v1\0", body)


def _original_at(item: JsonObject, created_at: str) -> str:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        original = metadata.get("original_at")
        if isinstance(original, str):
            return original
    return created_at
