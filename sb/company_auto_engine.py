from __future__ import annotations

import hashlib
import sqlite3
from contextlib import AbstractContextManager, closing, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import ValidationError

from sb.company_approver_binding import public_key_fingerprint
from sb.company_auto_authorization import require_auto_transaction
from sb.company_auto_intents import (
    PendingAutoReserve,
    consume_auto_reserve,
    pending_auto_reserve,
    prepare_auto_reserve,
)
from sb.company_auto_policy import (
    PolicyAutoReceiptV1,
    assessment_digest,
    auto_command,
    auto_request_id,
    build_unsigned_receipt,
    command_digest,
    policy_digest,
    receipt_expired,
    sign_policy_receipt,
    verify_policy_receipt,
)
from sb.company_auto_publication import InternalAutoJournal
from sb.company_auto_readback import verified_auto_assessment
from sb.company_auto_recovery import AcceptedAutoAuthority, accepted_auto_authority
from sb.company_auto_settings import (
    FIXED_TRIGGER_LIMIT,
    AutoInternalContext,
    AutoInternalRejected,
    AutoInternalSettings,
    AutoTriggerGrant,
    SourceContext,
    require_live_trigger,
    source_context_digest,
)
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import (
    TERMINAL_STATE_BY_OPERATION,
    Checkpoint,
    CompanyFreshnessProvider,
    FinishProgressRequest,
    FreshnessScope,
    FreshnessWireError,
    ReadFreshnessRequest,
    ReserveProgressRequest,
    ReserveProgressResponse,
)
from sb.company_freshness_progress import checkpoint_advances, is_other_store_prefix
from sb.company_internal_classifier import InternalClassification, classify_mail_candidate
from sb.company_internal_effects import (
    candidate_state,
    cas_candidate,
    claim_auto,
    effect_digest,
    human_path_blocks,
    insert_assessment,
    insert_effect,
    insert_memory_receipt,
    memory_request_digest,
    record_id_for,
    save_policy_receipt,
    verify_internal_readback,
)
from sb.company_internal_migrations import internal_auto_checksum
from sb.company_memory import CompanyMemoryStore, MemoryCandidate
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.company_processor_progress import local_checkpoint, save_checkpoint
from sb.effect_values import JsonObject, canonical_bytes, format_instant, strict_loads
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess

_OPERATION_DOMAIN = b"second-brain/company-operation/v1\0"


class InternalPendingFinish(ClosedModel):
    operation: Literal["accept", "complete", "mark_processed"]
    operation_id: str
    reservation: ReserveProgressResponse
    evidence_digest: str
    before_checkpoint: Checkpoint
    candidate_id: str
    content_digest: str
    auto_request_id: str
    request_digest: str


@dataclass(frozen=True, slots=True)
class AutoCandidateOutcome:
    candidate_id: str
    classification: str
    effect_count: int
    receipt_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    uncertain: bool


@dataclass(frozen=True, slots=True)
class AutoRunResult:
    outcomes: tuple[AutoCandidateOutcome, ...]
    checkpoint: Checkpoint


def run_auto_internal(
    database: Path,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    provider: InternalAutoJournal,
    trigger: AutoTriggerGrant,
) -> AutoRunResult:
    if context.clock is not None:
        context = replace(context, now=context.clock())
    require_live_trigger(trigger, context.now)
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id,
        workspace_id=context.workspace_id,
    )
    try:
        checkpoint = local_checkpoint(database, context.workspace_id, None)
    except CompanyAuthorityRejected as exc:
        raise AutoInternalRejected(str(exc)) from exc
    if checkpoint is None:
        raise AutoInternalRejected("COMPANY_OPERATIONAL_ROLLBACK")
    checkpoint = drain_internal_pending(database, settings, context, provider, checkpoint)
    _require_installed_policy(database, settings, context.workspace_id)
    provider.require_auto_policy(
        scope,
        policy_digest(settings.policy),
        settings.signer.key_id,
        public_key_fingerprint(settings.signer.public_key),
        source_context_digest(settings.provider_instance_id, context),
    )
    checkpoint = local_checkpoint(database, context.workspace_id, None)
    if checkpoint is None:
        raise AutoInternalRejected("COMPANY_OPERATIONAL_ROLLBACK")
    context = replace(context, observed_checkpoint=checkpoint)
    checkpoint = _require_ready(database, provider, settings, context, scope)
    if isinstance(provider, CompanyDbFreshnessProvider):
        provider.rebase_unreserved_auto_intent(scope, checkpoint)
    with closing(sqlite3.connect(database)) as db:
        pending_reserve = pending_auto_reserve(db, scope)
    if pending_reserve is None:
        checkpoint = provider.publish_completed_assessments(scope, checkpoint)
    outcomes: list[AutoCandidateOutcome] = []
    candidates = list(
        (pending_reserve.candidate_id,)
        if pending_reserve is not None
        else _candidate_ids(database, context, settings)
    )
    for candidate_id in candidates:
        if context.clock is not None:
            context = replace(context, now=context.clock())
        require_live_trigger(trigger, context.now)
        outcome, checkpoint = _one(
            database,
            settings,
            context,
            provider,
            scope,
            candidate_id,
            checkpoint,
            trigger,
        )
        outcomes.append(outcome)
        if outcome.uncertain:
            break
        if pending_reserve is not None and outcome.classification == "skipped_expired":
            candidates.extend(
                candidate
                for candidate in _candidate_ids(database, context, settings)
                if candidate != candidate_id
            )
            del candidates[FIXED_TRIGGER_LIMIT:]
            pending_reserve = None
    return AutoRunResult(tuple(outcomes), checkpoint)


def drain_internal_pending(
    database: Path,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    provider: CompanyFreshnessProvider,
    checkpoint: Checkpoint,
) -> Checkpoint:
    scope = FreshnessScope(
        provider_instance_id=settings.provider_instance_id,
        workspace_id=context.workspace_id,
    )
    pending = _load_pending(database, scope)
    if pending is None:
        return checkpoint
    if (
        pending.reservation.scope != scope
        or pending.reservation.checkpoint != checkpoint
        or pending.request_digest
        != memory_request_digest(
            pending.operation,
            pending.candidate_id,
            pending.auto_request_id,
        )
    ):
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if not _pending_evidence(database, scope, pending):
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    finished = _finish(provider, pending)
    _delete_pending(database, context.workspace_id, scope, pending, finished)
    return finished


def _one(
    database: Path,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    provider: InternalAutoJournal,
    scope: FreshnessScope,
    candidate_id: str,
    checkpoint: Checkpoint,
    trigger: AutoTriggerGrant,
) -> tuple[AutoCandidateOutcome, Checkpoint]:
    loaded = _loaded_candidate(database, context, candidate_id)
    if loaded is None:
        return _outcome(
            candidate_id, "human_required", 0, (), ("source_unknown",), False
        ), checkpoint
    candidate, deletion = loaded
    continuation: AcceptedAutoAuthority | None = None
    if deletion != (context.deletion_sequence, context.deletion_set_root):
        return _outcome(
            candidate_id, "human_required", 0, (), ("fence_advanced",), False
        ), checkpoint
    with closing(sqlite3.connect(database)) as db:
        if human_path_blocks(db, scope, candidate_id):
            return _outcome(
                candidate_id, "skipped_human", 0, (), ("human_path",), False
            ), checkpoint
        if candidate.state == "candidate":
            expired = db.execute(
                """SELECT r.receipt_json FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims w
                  ON w.provider_instance_id=r.provider_instance_id AND w.workspace_id=r.workspace_id
                  AND w.candidate_id=r.candidate_id AND w.content_digest=r.content_digest
                  AND w.workflow_request_id=r.auto_request_id AND w.path='auto_internal'
                WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?
                  AND r.content_digest=?""",
                (
                    scope.provider_instance_id,
                    scope.workspace_id,
                    candidate_id,
                    candidate.content_digest,
                ),
            ).fetchall()
            if len(expired) > 1:
                raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
            if expired and receipt_expired(
                PolicyAutoReceiptV1.model_validate_json(expired[0][0], strict=True),
                format_instant(context.now),
            ):
                return _skip_expired_attempt(database, provider, scope, candidate_id, checkpoint)
        if candidate.state == "accepted":
            original_auto: list[tuple[str, str, str, str]] = db.execute(
                """SELECT r.policy_digest,r.auto_request_id,r.receipt_json,r.auto_command_json
                FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims c
                  ON c.provider_instance_id=r.provider_instance_id
                  AND c.workspace_id=r.workspace_id AND c.candidate_id=r.candidate_id
                  AND c.content_digest=r.content_digest AND c.path='auto_internal'
                  AND c.workflow_request_id=r.auto_request_id
                WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?
                  AND r.content_digest=?""",
                (
                    scope.provider_instance_id,
                    scope.workspace_id,
                    candidate_id,
                    candidate.content_digest,
                ),
            ).fetchall()
            if not original_auto:
                return _outcome(
                    candidate_id,
                    "skipped_human",
                    0,
                    (),
                    ("human_path",),
                    False,
                ), checkpoint
            if isinstance(provider, CompanyDbFreshnessProvider):
                continuation = accepted_auto_authority(db, scope, candidate_id)
                settings = replace(settings, policy=continuation.policy)
                if db.execute(
                    """SELECT 1 FROM company_freshness_operations
                    WHERE provider_instance_id=? AND workspace_id=? AND operation='complete'
                      AND actor_store='second_brain' AND state='finished'
                      AND terminal_state='cancelled' AND event_digest=?""",
                    (
                        scope.provider_instance_id,
                        scope.workspace_id,
                        memory_request_digest("complete", candidate_id, original_auto[0][1]),
                    ),
                ).fetchone():
                    return _outcome(
                        candidate_id, "human_required", 0, (), ("conflict",), False
                    ), checkpoint
            elif len(original_auto) != 1 or original_auto[0][0] != policy_digest(settings.policy):
                raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
            accepted_receipt = PolicyAutoReceiptV1.model_validate_json(
                original_auto[0][2], strict=True
            )
            accepted_command = strict_loads(original_auto[0][3], 1_048_576)
            if not isinstance(accepted_command, dict):
                raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
            accepted_payload = verified_auto_assessment(
                db, scope, candidate, accepted_receipt, accepted_command
            )
    digest = policy_digest(settings.policy)
    classification: Literal["auto_internal", "human_required"]
    if candidate.state == "accepted":
        kind = accepted_payload.record_kind
        fields = accepted_payload.fields
        reasons: tuple[str, ...] = ()
        classification = "auto_internal"
        payload = model_object(accepted_payload)
        assessed = accepted_receipt.assessment_digest
        if _allowlist(settings, kind, fields):
            raise AutoInternalRejected("ASSESSMENT_CONFLICT")
        # A collision is not a new assessment of the accepted source. Let the
        # guarded completion prove it unapplied and publish its cancellation.
        if _record_conflict(database, scope, candidate, kind, fields) and _effect_exists(
            database, scope, accepted_receipt.auto_request_id
        ):
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    else:
        classified = classify_mail_candidate(candidate)
        kind = classified.record_kind
        reasons = classified.reason_codes
        fields = classified.fields
        if classified.classification == "auto_internal" and kind is not None:
            denied = _allowlist(settings, kind, fields)
            if denied:
                reasons = denied
                kind = None
            elif _record_conflict(database, scope, candidate, kind, fields):
                reasons = ("conflict",)
                kind = None
        classification = "auto_internal" if kind is not None and not reasons else "human_required"
        payload = (
            _payload(kind, fields, classified)
            if classification == "auto_internal" and kind
            else None
        )
        assessed = assessment_digest(
            candidate_id=candidate.candidate_id,
            content_digest=candidate.content_digest,
            policy_digest_value=digest,
            classification=classification,
            reason_codes=reasons,
            payload=payload,
        )
        with (
            _policy_guard(provider, scope, settings, context),
            closing(sqlite3.connect(database)) as db,
            db,
        ):
            insert_assessment(
                db,
                scope,
                candidate_id=candidate.candidate_id,
                content_digest=candidate.content_digest,
                policy_digest_value=digest,
                assessment_digest_value=assessed,
                classification=classification,
                reason_codes=reasons,
                payload=payload,
                created_at=format_instant(context.now),
            )
    with closing(sqlite3.connect(database)) as db:
        reserved_intent = pending_auto_reserve(db, scope)
    if reserved_intent is None:
        checkpoint = provider.publish_assessment(scope, assessed, checkpoint)
    if candidate.state == "processed_complete":
        return _outcome(candidate_id, "already_complete", 0, (), (), False), checkpoint
    if classification != "auto_internal" or kind is None or payload is None:
        return _outcome(candidate_id, "human_required", 0, (), reasons, False), checkpoint
    request_id = auto_request_id(scope, candidate.candidate_id, candidate.content_digest, digest)
    command = auto_command(
        scope=scope,
        request_id=request_id,
        candidate_id=candidate.candidate_id,
        content_digest=candidate.content_digest,
        policy_digest_value=digest,
        assessment_digest_value=assessed,
        record_kind=kind,
    )
    with closing(sqlite3.connect(database)) as db:
        original: list[tuple[str]] = db.execute(
            """SELECT receipt_json FROM company_auto_policy_receipts
            WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
            (scope.provider_instance_id, scope.workspace_id, request_id),
        ).fetchall()
    if original:
        receipt = PolicyAutoReceiptV1.model_validate_json(original[0][0])
    else:
        if candidate.state == "accepted":
            raise AutoInternalRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")
        unsigned = build_unsigned_receipt(
            settings,
            scope=scope,
            candidate_id=candidate.candidate_id,
            content_digest=candidate.content_digest,
            source_event_id=candidate.source_event_id,
            assessment_digest_value=assessed,
            command_digest_value=command_digest(command),
            issued_at=format_instant(context.now),
        )
        receipt = sign_policy_receipt(settings.signer, unsigned)
    verify_policy_receipt(
        receipt, continuation.public_key if continuation is not None else settings.signer.public_key
    )
    if (
        receipt.scope != scope
        or receipt.auto_request_id != request_id
        or receipt.content_digest != candidate.content_digest
        or receipt.source_event_id != candidate.source_event_id
        or receipt.policy_digest != digest
        or receipt.assessment_digest != assessed
        or receipt.command_digest != command_digest(command)
    ):
        raise AutoInternalRejected("POLICY_RECEIPT_CONFLICT")
    if candidate.state == "candidate" and receipt_expired(receipt, format_instant(context.now)):
        raise AutoInternalRejected("POLICY_RECEIPT_EXPIRED")
    with (
        _policy_guard(provider, scope, settings, context, continuation=continuation),
        closing(sqlite3.connect(database)) as db,
        db,
    ):
        if not claim_auto(
            db,
            scope,
            candidate_id=candidate.candidate_id,
            content_digest=candidate.content_digest,
            workflow_request_id=request_id,
            created_at=format_instant(context.now),
        ):
            return _outcome(
                candidate_id, "skipped_human", 0, (), ("human_path",), False
            ), checkpoint
        _ = save_policy_receipt(db, scope, receipt, command, format_instant(context.now))
        if candidate.state == "candidate":
            prepare_auto_reserve(
                db,
                _reserve_intent(
                    scope,
                    candidate.candidate_id,
                    request_id,
                    command_digest(command),
                    "accept",
                    checkpoint,
                ),
            )
    receipts: list[str] = []
    if candidate_state_of(database, scope.workspace_id, candidate.candidate_id) == "candidate":
        checkpoint, evidence = _transition(
            database,
            settings,
            context,
            provider,
            scope,
            checkpoint,
            candidate,
            "accept",
            request_id,
            command_digest(command),
            deletion,
            None,
            trigger=trigger,
        )
        receipts.append("cmreceipt:v1:" + evidence.removeprefix("sha256:"))
    effect_count = 0
    if not _effect_exists(database, scope, request_id):
        try:
            checkpoint, evidence = _transition(
                database,
                settings,
                context,
                provider,
                scope,
                checkpoint,
                candidate,
                "complete",
                request_id,
                command_digest(command),
                deletion,
                (kind, fields, candidate.source_event_id),
                trigger=trigger,
                continuation=continuation,
            )
        except AutoInternalRejected as exc:
            if (
                exc.code == "INTERNAL_RECORD_CONFLICT"
                and candidate.state == "accepted"
                and isinstance(provider, CompanyDbFreshnessProvider)
            ):
                # _transition returns this error only after guarded zero-effect
                # cancellation succeeds. Never continue on a failed proof.
                current = local_checkpoint(database, scope.workspace_id, None)
                if current is None:
                    raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
                return _outcome(
                    candidate_id, "human_required", 0, tuple(receipts), ("conflict",), False
                ), current
            if exc.code != "READBACK_FAILED":
                raise
            return _outcome(
                candidate_id, "uncertain", 0, tuple(receipts), ("readback_failed",), True
            ), checkpoint
        effect_count = 1
    else:
        effect_count = 1
    if candidate_state_of(database, scope.workspace_id, candidate.candidate_id) == "accepted":
        checkpoint, evidence = _transition(
            database,
            settings,
            context,
            provider,
            scope,
            checkpoint,
            candidate,
            "mark_processed",
            request_id,
            command_digest(command),
            deletion,
            None,
            trigger=trigger,
            continuation=continuation,
        )
        receipts.append("cmreceipt:v1:" + evidence.removeprefix("sha256:"))
    checkpoint = provider.publish_assessment(scope, assessed, checkpoint)
    return _outcome(
        candidate_id, "auto_internal", effect_count, tuple(receipts), (), False
    ), checkpoint


def _transition(
    database: Path,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    provider: InternalAutoJournal,
    scope: FreshnessScope,
    checkpoint: Checkpoint,
    candidate: MemoryCandidate,
    operation: Literal["accept", "complete", "mark_processed"],
    request_id: str,
    command_digest_value: str,
    deletion: tuple[int, str],
    effect: tuple[str, dict[str, str], str] | None,
    *,
    trigger: AutoTriggerGrant,
    continuation: AcceptedAutoAuthority | None = None,
) -> tuple[Checkpoint, str]:
    if context.clock is not None:
        context = replace(context, now=context.clock())
    require_live_trigger(trigger, context.now)
    if continuation and operation == "accept":
        raise AutoInternalRejected("POLICY_RECEIPT_REJECTED")
    if not continuation and policy_digest(settings.policy) in settings.revoked_policy_digests:
        raise AutoInternalRejected("POLICY_REVOKED")
    operation_id = _operation_identity(scope, request_id, command_digest_value, operation)
    request_digest = memory_request_digest(operation, candidate.candidate_id, request_id)
    with (
        _policy_guard(provider, scope, settings, context, continuation=continuation),
        closing(sqlite3.connect(database)) as db,
        db,
    ):
        _ = db.execute("BEGIN IMMEDIATE")
        intent = prepare_auto_reserve(
            db,
            _reserve_intent(
                scope,
                candidate.candidate_id,
                request_id,
                command_digest_value,
                operation,
                checkpoint,
            ),
        )
    reservation = _reserve(provider, intent.request)
    evidence = ""
    with (
        provider.effect_guard(scope, operation_id, reservation),
        closing(sqlite3.connect(database)) as db,
    ):
        # effect_guard already owns registry exclusion. Recheck the live anchored
        # policy before acquiring the SQL writer; never recursively take flock.
        # Anchored acceptances intentionally retain their original public authority.
        if continuation is None:
            try:
                provider.require_auto_policy_under_guard(
                    scope,
                    policy_digest(settings.policy),
                    settings.signer.key_id,
                    public_key_fingerprint(settings.signer.public_key),
                    source_context_digest(settings.provider_instance_id, context),
                )
            except (AnchorRejected, AutoInternalRejected):
                # Reserve is already durable. Close only a proven zero-effect
                # attempt; the provider rejects cancellation on ambiguous SQL.
                if operation in {"accept", "complete"} and isinstance(
                    provider, CompanyDbFreshnessProvider
                ):
                    provider.cancel_unapplied_under_guard(
                        scope, operation_id, reservation, checkpoint
                    )
                raise
        _ = db.execute("BEGIN IMMEDIATE")
        authorization_rejected = False
        try:
            if context.clock is not None:
                context = replace(context, now=context.clock())
            require_live_trigger(trigger, context.now)
            if reservation.checkpoint is None:
                raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
            try:
                require_auto_transaction(
                    db,
                    scope,
                    settings,
                    context,
                    candidate,
                    request_id,
                    command_digest_value,
                    operation,
                    continuation=continuation,
                )
            except AutoInternalRejected:
                authorization_rejected = True
                raise
            save_checkpoint(db, scope.workspace_id, reservation.checkpoint, checkpoint)
            match operation:
                case "accept" | "mark_processed":
                    result = cas_candidate(
                        db,
                        scope,
                        candidate.candidate_id,
                        candidate.content_digest,
                        deletion,
                        operation,
                        context.now,
                    )
                    evidence = insert_memory_receipt(
                        db,
                        workspace_id=scope.workspace_id,
                        request_digest=request_digest,
                        operation=operation,
                        candidate_id=candidate.candidate_id,
                        result=result,
                        created_at=format_instant(context.now),
                    )
                case "complete":
                    if effect is None:
                        raise AutoInternalRejected("EFFECT_CONFLICT")
                    kind, fields, event_id = effect
                    payload: JsonObject = {key: value for key, value in fields.items()}
                    evidence = insert_effect(
                        db,
                        scope,
                        operation_id=operation_id,
                        auto_request_id=request_id,
                        candidate_id=candidate.candidate_id,
                        record_kind=kind,
                        entity_key=_entity_key(kind, fields),
                        payload=payload,
                        source_event_id=event_id,
                        content_digest=candidate.content_digest,
                        deletion=deletion,
                        created_at=format_instant(context.now),
                        forbidden_digests=(command_digest_value,),
                        source_context=SourceContext(
                            workspace_id=context.workspace_id,
                            owner=context.owner,
                            projects=list(context.projects),
                            policy_revision=context.policy_revision,
                            deletion_sequence=context.deletion_sequence,
                            deletion_set_root=context.deletion_set_root,
                        ),
                    )
            pending = InternalPendingFinish(
                operation=operation,
                operation_id=operation_id,
                reservation=reservation,
                evidence_digest=evidence,
                before_checkpoint=checkpoint,
                candidate_id=candidate.candidate_id,
                content_digest=candidate.content_digest,
                auto_request_id=request_id,
                request_digest=request_digest,
            )
            _ = db.execute(
                "INSERT INTO company_internal_pending_finish VALUES(?,?,?,?)",
                (
                    scope.provider_instance_id,
                    scope.workspace_id,
                    request_digest,
                    canonical_bytes(model_object(pending)).decode("utf-8"),
                ),
            )
            consume_auto_reserve(db, intent)
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
        except AutoInternalRejected as exc:
            db.rollback()
            if (
                (authorization_rejected and operation == "accept")
                or (operation == "complete" and exc.code == "INTERNAL_RECORD_CONFLICT")
            ) and isinstance(provider, CompanyDbFreshnessProvider):
                provider.cancel_unapplied_under_guard(scope, operation_id, reservation, checkpoint)
            raise
    if operation == "complete" and not verify_internal_readback(
        database,
        scope,
        operation_id,
        evidence,
    ):
        raise AutoInternalRejected("READBACK_FAILED")
    finished = _finish(provider, pending)
    _delete_pending(database, context.workspace_id, scope, pending, finished)
    return finished, evidence


def _skip_expired_attempt(
    database: Path,
    provider: InternalAutoJournal,
    scope: FreshnessScope,
    candidate_id: str,
    checkpoint: Checkpoint,
) -> tuple[AutoCandidateOutcome, Checkpoint]:
    with closing(sqlite3.connect(database)) as db:
        intent = pending_auto_reserve(db, scope)
        if intent is None:
            rows = db.execute(
                """SELECT r.auto_request_id,r.receipt_json FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims w
                  ON w.provider_instance_id=r.provider_instance_id AND w.workspace_id=r.workspace_id
                  AND w.candidate_id=r.candidate_id AND w.content_digest=r.content_digest
                  AND w.workflow_request_id=r.auto_request_id AND w.path='auto_internal'
                WHERE r.provider_instance_id=? AND r.workspace_id=? AND r.candidate_id=?""",
                (scope.provider_instance_id, scope.workspace_id, candidate_id),
            ).fetchall()
            if len(rows) != 1 or not isinstance(provider, CompanyDbFreshnessProvider):
                raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
            receipt = PolicyAutoReceiptV1.model_validate_json(rows[0][1], strict=True)
            # Reconstruct only the immutable acceptance identity. This grants cancellation,
            # never a renewed receipt or an acceptance after its authorization expired.
            intent = prepare_auto_reserve(
                db,
                _reserve_intent(
                    scope, candidate_id, rows[0][0], receipt.command_digest, "accept", checkpoint
                ),
            )
            db.commit()
    if intent is not None:
        if intent.candidate_id != candidate_id or not isinstance(
            provider, CompanyDbFreshnessProvider
        ):
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        reservation = _reserve(provider, intent.request)
        with provider.effect_guard(scope, intent.request.operation_id, reservation):
            provider.cancel_unapplied_under_guard(
                scope, intent.request.operation_id, reservation, checkpoint
            )
        current = local_checkpoint(database, scope.workspace_id, None)
        if current is None:
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        checkpoint = current
    return _outcome(
        candidate_id, "skipped_expired", 0, (), ("policy_receipt_expired",), False
    ), checkpoint


def _reserve_intent(
    scope: FreshnessScope,
    candidate_id: str,
    request_id: str,
    command_digest_value: str,
    operation: Literal["accept", "complete", "mark_processed"],
    checkpoint: Checkpoint,
) -> PendingAutoReserve:
    return PendingAutoReserve(
        candidate_id=candidate_id,
        auto_request_id=request_id,
        command_digest=command_digest_value,
        request=ReserveProgressRequest(
            schema_version=2,
            scope=scope,
            operation_id=_operation_identity(scope, request_id, command_digest_value, operation),
            operation=operation,
            expected_checkpoint=checkpoint,
            event_digest=memory_request_digest(operation, candidate_id, request_id),
            challenge="reserve:" + uuid4().hex,
        ),
    )


def _reserve(
    provider: CompanyFreshnessProvider,
    request: ReserveProgressRequest,
) -> ReserveProgressResponse:
    try:
        response = provider.reserve_progress(request)
    except (TimeoutError, OSError) as exc:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
    if isinstance(response, FreshnessWireError) or response.outcome not in {
        "reserved",
        "already_reserved",
    }:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if response.checkpoint is None or response.reservation_id is None:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if (
        response.scope != request.scope
        or response.challenge != request.challenge
        or not checkpoint_advances(request.expected_checkpoint, response.checkpoint)
    ):
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    return response


def _finish(provider: CompanyFreshnessProvider, pending: InternalPendingFinish) -> Checkpoint:
    reservation = pending.reservation
    if reservation.checkpoint is None or reservation.reservation_id is None:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    request = FinishProgressRequest(
        schema_version=2,
        scope=reservation.scope,
        operation_id=pending.operation_id,
        reservation_id=reservation.reservation_id,
        expected_checkpoint=reservation.checkpoint,
        evidence_digest=pending.evidence_digest,
        terminal_state=TERMINAL_STATE_BY_OPERATION[pending.operation],
        challenge="finish:" + uuid4().hex,
    )
    try:
        response = provider.finish_progress(request)
    except (TimeoutError, OSError) as exc:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN") from exc
    if isinstance(response, FreshnessWireError) or response.checkpoint is None:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if response.outcome == "conflict":
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    if (
        response.scope != request.scope
        or response.challenge != request.challenge
        or not checkpoint_advances(reservation.checkpoint, response.checkpoint)
    ):
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    return response.checkpoint


def _operation_identity(
    scope: FreshnessScope,
    request_id: str,
    command_digest_value: str,
    operation: str,
) -> str:
    identity: JsonObject = {
        "scope": model_object(scope),
        "request_id": request_id,
        "command_digest": command_digest_value,
        "operation": operation,
    }
    return "sha256:" + hashlib.sha256(_OPERATION_DOMAIN + canonical_bytes(identity)).hexdigest()


def _require_ready(
    database: Path,
    provider: CompanyFreshnessProvider,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    scope: FreshnessScope,
) -> Checkpoint:
    request = ReadFreshnessRequest(
        schema_version=2,
        scope=scope,
        installation_id=settings.installation_id,
        challenge="read:" + uuid4().hex,
        observed_checkpoint=context.observed_checkpoint,
    )
    response = provider.read_freshness(request)
    if (
        response.status == "uncertain"
        and response.scope == scope
        and response.challenge == request.challenge
        and response.checkpoint is None
    ):
        with closing(sqlite3.connect(database)) as db:
            pending = pending_auto_reserve(db, scope)
        if (
            pending is not None
            and pending.request.expected_checkpoint == context.observed_checkpoint
        ):
            # This is not freshness permission: only the recorded original reserve
            # may run next, and the provider must match its exact durable identity.
            return context.observed_checkpoint
    ready = response.checkpoint
    if (
        response.status != "ready"
        or ready is None
        or response.challenge != request.challenge
        or response.scope != scope
        or not is_other_store_prefix(context.observed_checkpoint, ready, "second_brain")
    ):
        raise AutoInternalRejected("COMPANY_FRESHNESS_REQUIRED")
    if ready != context.observed_checkpoint:
        with closing(sqlite3.connect(database)) as db, db:
            save_checkpoint(db, context.workspace_id, ready, context.observed_checkpoint)
    return ready


def _policy_guard(
    provider: InternalAutoJournal,
    scope: FreshnessScope,
    settings: AutoInternalSettings,
    context: AutoInternalContext,
    *,
    continuation: AcceptedAutoAuthority | None = None,
) -> AbstractContextManager[None]:
    if continuation is not None:
        return nullcontext()
    return provider.auto_policy_guard(
        scope,
        policy_digest(settings.policy),
        settings.signer.key_id,
        public_key_fingerprint(settings.signer.public_key),
        source_context_digest(settings.provider_instance_id, context),
    )


def _require_installed_policy(
    database: Path, settings: AutoInternalSettings, workspace_id: str
) -> None:
    digest = policy_digest(settings.policy)
    if digest in settings.revoked_policy_digests:
        raise AutoInternalRejected("POLICY_REVOKED")
    with closing(sqlite3.connect(database)) as db:
        marker = cast(
            tuple[str] | None,
            db.execute(
                """SELECT checksum FROM company_component_migrations
            WHERE component='internal_auto' AND version=1""",
            ).fetchone(),
        )
        if marker is None or marker[0] != internal_auto_checksum():
            raise AutoInternalRejected("COMPANY_MEMORY_SCHEMA_UPGRADE_REQUIRED")
        row = cast(
            tuple[str] | None,
            db.execute(
                """SELECT policy_digest FROM company_auto_policies
            WHERE provider_instance_id=? AND workspace_id=? AND policy_version=?""",
                (settings.provider_instance_id, workspace_id, settings.policy.policy_version),
            ).fetchone(),
        )
    if row is None or row[0] != digest:
        raise AutoInternalRejected("POLICY_NOT_INSTALLED")


def _candidate_ids(
    database: Path,
    context: AutoInternalContext,
    settings: AutoInternalSettings,
) -> tuple[str, ...]:
    with closing(sqlite3.connect(database)) as db:
        rows: list[tuple[str]] = db.execute(
            """SELECT c.candidate_id FROM company_memory_candidates c
            WHERE c.workspace_id=? AND c.owner=? AND c.policy_revision=?
              AND c.source_system='mail' AND c.state IN ('candidate','accepted')
              AND c.deletion_sequence=? AND c.deletion_set_root=?
              AND NOT EXISTS(SELECT 1 FROM company_handoff_outbox h
                WHERE h.workspace_id=c.workspace_id AND h.candidate_id=c.candidate_id)
              AND NOT EXISTS(SELECT 1 FROM company_handoff_decisions h
                WHERE h.workspace_id=c.workspace_id AND h.candidate_id=c.candidate_id)
              AND NOT EXISTS(SELECT 1 FROM company_candidate_execution_claims h
                WHERE h.provider_instance_id=? AND h.workspace_id=c.workspace_id
                  AND h.candidate_id=c.candidate_id AND h.path='human')
              AND (c.state='candidate' OR EXISTS(SELECT 1 FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims w
                  ON w.provider_instance_id=r.provider_instance_id
                  AND w.workspace_id=r.workspace_id AND w.candidate_id=r.candidate_id
                  AND w.content_digest=r.content_digest AND w.path='auto_internal'
                  AND w.workflow_request_id=r.auto_request_id
                WHERE r.provider_instance_id=? AND r.workspace_id=c.workspace_id
                  AND r.candidate_id=c.candidate_id AND r.content_digest=c.content_digest))
              AND NOT EXISTS(SELECT 1 FROM json_each(c.projects_json) p
                WHERE p.value NOT IN (SELECT value FROM json_each(?)))
              AND (json_array_length(c.projects_json)>0 OR ?='[]')
              AND NOT (c.state='accepted' AND EXISTS(
                SELECT 1 FROM company_auto_policy_receipts r
                JOIN company_freshness_log l
                  ON l.provider_instance_id=r.provider_instance_id AND l.workspace_id=r.workspace_id
                JOIN company_freshness_publication f ON f.global_sequence=l.global_sequence
                WHERE r.provider_instance_id=? AND r.workspace_id=c.workspace_id
                  AND r.candidate_id=c.candidate_id AND r.content_digest=c.content_digest
                  AND json_extract(l.record_json,'$.kind')='unapplied_processor_cancellation'
                  AND json_extract(l.record_json,'$.auto_intent.request.operation')='complete'
                  AND json_extract(l.record_json,'$.auto_intent.auto_request_id')=r.auto_request_id))
              AND NOT (c.state='candidate' AND EXISTS(
                SELECT 1 FROM company_auto_policy_receipts r
                JOIN company_candidate_execution_claims w
                  ON w.provider_instance_id=r.provider_instance_id AND w.workspace_id=r.workspace_id
                  AND w.candidate_id=r.candidate_id AND w.content_digest=r.content_digest
                  AND w.workflow_request_id=r.auto_request_id AND w.path='auto_internal'
                WHERE r.provider_instance_id=? AND r.workspace_id=c.workspace_id
                  AND r.candidate_id=c.candidate_id AND r.content_digest=c.content_digest
                  AND EXISTS(SELECT 1 FROM company_freshness_log l
                    JOIN company_freshness_publication f ON f.global_sequence=l.global_sequence
                    WHERE l.provider_instance_id=r.provider_instance_id AND l.workspace_id=r.workspace_id
                      AND json_extract(l.record_json,'$.kind')='unapplied_processor_cancellation'
                      AND json_extract(l.record_json,'$.auto_intent.auto_request_id')=r.auto_request_id)))
            ORDER BY (c.state='accepted') DESC,
              EXISTS(SELECT 1 FROM company_auto_policy_receipts r
                WHERE r.provider_instance_id=? AND r.workspace_id=c.workspace_id
                  AND r.candidate_id=c.candidate_id AND r.content_digest=c.content_digest) DESC,
              EXISTS(SELECT 1 FROM company_auto_assessments a
                WHERE a.provider_instance_id=? AND a.workspace_id=c.workspace_id
                  AND a.candidate_id=c.candidate_id AND a.policy_digest=?),
              c.candidate_id LIMIT ?""",
            (
                context.workspace_id,
                context.owner,
                context.policy_revision,
                context.deletion_sequence,
                context.deletion_set_root,
                settings.provider_instance_id,
                settings.provider_instance_id,
                canonical_bytes(list(context.projects)).decode("utf-8"),
                canonical_bytes(list(context.projects)).decode("utf-8"),
                settings.provider_instance_id,
                settings.provider_instance_id,
                settings.provider_instance_id,
                settings.provider_instance_id,
                policy_digest(settings.policy),
                FIXED_TRIGGER_LIMIT,
            ),
        ).fetchall()
    return tuple(row[0] for row in rows)


def _loaded_candidate(
    database: Path,
    context: AutoInternalContext,
    candidate_id: str,
) -> tuple[MemoryCandidate, tuple[int, str]] | None:
    access = SourceAccess(context.owner, context.projects, context.policy_revision)
    deletion = (context.deletion_sequence, context.deletion_set_root)
    store = CompanyMemoryStore(database)
    try:
        candidate = store.get(context.workspace_id, candidate_id, access, deletion)
    except ValueError:
        return None
    finally:
        store.close()
    return candidate, (candidate.deletion_sequence, candidate.deletion_set_root)


def _allowlist(
    settings: AutoInternalSettings, kind: str, fields: dict[str, str]
) -> tuple[str, ...]:
    if kind not in settings.policy.allowed_kinds:
        return ("policy_denied",)
    match kind:
        case "contact":
            email = fields.get("email", "").lower()
            if not any(
                email.endswith(suffix) for suffix in settings.policy.internal_email_suffixes
            ):
                return ("policy_denied",)
        case "calendar" | "progress":
            if fields.get("internal_assignee") not in settings.policy.internal_assignees:
                return ("policy_denied",)
    return ()


def _record_conflict(
    database: Path,
    scope: FreshnessScope,
    candidate: MemoryCandidate,
    kind: str,
    fields: dict[str, str],
) -> bool:
    key = _entity_key(kind, fields)
    payload = canonical_bytes(fields).decode("utf-8")
    with closing(sqlite3.connect(database)) as db:
        row = cast(
            tuple[str, str] | None,
            db.execute(
                """SELECT payload_json, source_candidate_id FROM company_internal_records
            WHERE provider_instance_id=? AND workspace_id=? AND entity_key=? AND record_kind=?""",
                (scope.provider_instance_id, scope.workspace_id, key, kind),
            ).fetchone(),
        )
        event = cast(
            tuple[str, str] | None,
            db.execute(
                """SELECT source_candidate_id, payload_json FROM company_internal_records
            WHERE provider_instance_id=? AND workspace_id=? AND source_event_id=?
            AND record_kind=? AND source_slot='primary'""",
                (scope.provider_instance_id, scope.workspace_id, candidate.source_event_id, kind),
            ).fetchone(),
        )
    if row is not None and (row[0] != payload or row[1] != candidate.candidate_id):
        return True
    return event is not None and event[0] != candidate.candidate_id


def _entity_key(kind: str, fields: dict[str, str]) -> str:
    match kind:
        case "contact":
            return fields["email"].lower()
        case "calendar":
            return fields["title"] + "\x1f" + fields["starts_at"]
        case "progress":
            return fields["subject"]
        case _:
            raise AutoInternalRejected("POLICY_DENIED")


def _payload(
    kind: str | None,
    fields: dict[str, str],
    classified: InternalClassification,
) -> JsonObject | None:
    if kind is None:
        return None
    encoded: JsonObject = {}
    for key, span in classified.spans.items():
        encoded[key] = {"start": span.start, "end": span.end}
    field_body: JsonObject = {}
    for key, value in fields.items():
        field_body[key] = value
    body: JsonObject = {
        "schema_version": 1,
        "record_kind": kind,
        "fields": field_body,
        "spans": encoded,
    }
    return body


def _effect_exists(database: Path, scope: FreshnessScope, request_id: str) -> bool:
    with closing(sqlite3.connect(database)) as db:
        return (
            db.execute(
                """SELECT 1 FROM company_internal_effects
            WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
                (scope.provider_instance_id, scope.workspace_id, request_id),
            ).fetchone()
            is not None
        )


def candidate_state_of(database: Path, workspace_id: str, candidate_id: str) -> str:
    with closing(sqlite3.connect(database)) as db:
        return candidate_state(db, workspace_id, candidate_id)


def _load_pending(database: Path, scope: FreshnessScope) -> InternalPendingFinish | None:
    with closing(sqlite3.connect(database)) as db:
        if (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_internal_pending_finish'",
            ).fetchone()
            is None
        ):
            return None
        row = cast(
            tuple[str] | None,
            db.execute(
                """SELECT pending_json FROM company_internal_pending_finish
            WHERE provider_instance_id=? AND workspace_id=?""",
                (scope.provider_instance_id, scope.workspace_id),
            ).fetchone(),
        )
    if row is None:
        return None
    try:
        return InternalPendingFinish.model_validate_json(row[0])
    except ValidationError as exc:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN") from exc


def _pending_evidence(
    database: Path, scope: FreshnessScope, pending: InternalPendingFinish
) -> bool:
    with closing(sqlite3.connect(database)) as db:
        match pending.operation:
            case "accept" | "mark_processed":
                row = cast(
                    tuple[str] | None,
                    db.execute(
                        """SELECT receipt_digest FROM company_memory_receipts
                    WHERE workspace_id=? AND request_digest=?""",
                        (scope.workspace_id, pending.request_digest),
                    ).fetchone(),
                )
                return row is not None and row[0] == pending.evidence_digest
            case "complete":
                row = cast(
                    tuple[str] | None,
                    db.execute(
                        """SELECT effect_digest FROM company_internal_effects
                    WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
                        (scope.provider_instance_id, scope.workspace_id, pending.operation_id),
                    ).fetchone(),
                )
                return (
                    row is not None
                    and row[0] == pending.evidence_digest
                    and verify_internal_readback(
                        database,
                        scope,
                        pending.operation_id,
                        pending.evidence_digest,
                    )
                )


def _delete_pending(
    database: Path,
    workspace_id: str,
    scope: FreshnessScope,
    pending: InternalPendingFinish,
    finished: Checkpoint,
) -> None:
    raw = canonical_bytes(model_object(pending)).decode("utf-8")
    with closing(sqlite3.connect(database)) as db, db:
        changed = db.execute(
            """DELETE FROM company_internal_pending_finish
            WHERE provider_instance_id=? AND workspace_id=? AND pending_json=?""",
            (scope.provider_instance_id, scope.workspace_id, raw),
        )
        if changed.rowcount != 1:
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        if pending.reservation.checkpoint is None:
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        save_checkpoint(db, workspace_id, finished, pending.reservation.checkpoint)


def _outcome(
    candidate_id: str,
    classification: str,
    effect_count: int,
    receipt_ids: tuple[str, ...],
    reason_codes: tuple[str, ...],
    uncertain: bool,
) -> AutoCandidateOutcome:
    return AutoCandidateOutcome(
        candidate_id,
        classification,
        effect_count,
        receipt_ids,
        reason_codes,
        uncertain,
    )


def published_record_id(scope: FreshnessScope, source_event_id: str, kind: str) -> str:
    return record_id_for(scope, source_event_id, kind)


def published_effect_digest(manifest: JsonObject) -> str:
    return effect_digest(manifest)
