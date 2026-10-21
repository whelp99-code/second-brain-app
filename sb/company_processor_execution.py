"""Reserve outside the company effect writer, then revalidate inside it."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.company_approver_binding import CompanyHandoffPolicy
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness_models import (
    Checkpoint,
    CompanyFreshnessProvider,
    FreshnessScope,
    ReserveProgressResponse,
)
from sb.company_memory import CompanyMemoryReceipt, CompanyMemoryStore, MemoryCandidate
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyMemoryAuthorityV1,
)
from sb.company_memory_handoff import authorize_transition
from sb.company_processor_finish import PendingFinish, save_pending_finish
from sb.company_processor_progress import (
    ProcessorOperation,
    reserve_operation,
    save_checkpoint,
)
from sb.company_transition_receipt import TransitionReceiptSelector, read_original_receipt
from sb.effect_values import JsonObject, canonical_bytes
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess


def execute_processor_transition(
    store: CompanyMemoryStore,
    provider: CompanyFreshnessProvider,
    *,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    owner_keys: dict[str, Ed25519PublicKey],
    authority: CompanyMemoryAuthorityV1,
    operation: ProcessorOperation,
    arguments: JsonObject,
    checkpoint: Checkpoint,
    now: datetime,
    clock: Callable[[], datetime] | None = None,
) -> CompanyMemoryReceipt:
    """Only the durable reservation acknowledgment grants a new SQL effect."""
    candidate_id = arguments["candidate_id"]
    handoff_id = arguments["handoff_id"]
    if not isinstance(candidate_id, str) or not isinstance(handoff_id, str):
        raise CompanyAuthorityRejected("COMPANY_CONTRACT_INVALID")
    scope = SourceAccess(context.principal, context.projects, context.policy_revision)
    deletion = (context.deletion_sequence, context.deletion_set_root)

    def verify_original(selector: JsonObject) -> None:
        original = read_original_receipt(
            store.db,
            context,
            policy,
            TransitionReceiptSelector.model_validate(selector),
        )
        if original is None:
            raise CompanyAuthorityRejected("COMPANY_RECEIPT_EVIDENCE_ABSENT")

    # This validation must perform no decision consumption or candidate effect.
    candidate = store.get(context.workspace_id, candidate_id, scope, deletion)
    freshness_scope = FreshnessScope(
        provider_instance_id=context.provider, workspace_id=context.workspace_id
    )
    original_reservation = isinstance(
        provider, CompanyDbFreshnessProvider
    ) and provider.has_original_reservation(
        freshness_scope, operation, authority.request_digest, checkpoint
    )
    preflight_rejection: CompanyAuthorityRejected | None = None
    try:
        authorize_transition(
            store.db,
            candidate,
            context,
            policy,
            owner_keys,
            operation,
            arguments,
            authority.request_digest,
            now,
            verify_original,
            consume=False,
        )
    except CompanyAuthorityRejected as exc:
        if not original_reservation:
            raise
        preflight_rejection = exc
    cached: list[tuple[int]] = store.db.execute(
        "SELECT 1 FROM company_memory_receipts WHERE workspace_id=? AND request_digest=?",
        (context.workspace_id, authority.request_digest),
    ).fetchall()
    reservation: ReserveProgressResponse | None = None
    operation_id = ""
    if not cached:
        commands: list[tuple[str]] = store.db.execute(
            """SELECT command_digest FROM company_handoff_outbox
            WHERE workspace_id=? AND candidate_id=? AND request_id=?""",
            (context.workspace_id, candidate_id, handoff_id),
        ).fetchall()
        if original_reservation and isinstance(provider, CompanyDbFreshnessProvider):
            from sb.company_auto_policy import command_digest

            original_command = provider.reserved_processor_command(
                freshness_scope, operation, authority.request_digest, checkpoint
            )
            if (
                original_command.request_id != handoff_id
                or original_command.target.candidate_id != candidate_id
                or original_command.target.content_digest != candidate.content_digest
            ):
                raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
            commands = [(command_digest(model_object(original_command)),)]
        if not commands:
            raise CompanyAuthorityRejected("COMPANY_HANDOFF_REQUIRED")
        if isinstance(provider, CompanyDbFreshnessProvider) and operation == "mark_processed":
            provider.require_completed_handoff(
                FreshnessScope(
                    provider_instance_id=context.provider, workspace_id=context.workspace_id
                ),
                handoff_id,
                commands[0][0],
            )
        operation_id, reservation = reserve_operation(
            provider,
            FreshnessScope(
                provider_instance_id=context.provider,
                workspace_id=context.workspace_id,
            ),
            operation,
            handoff_id,
            commands[0][0],
            authority.request_digest,
            checkpoint,
            resume_original=original_reservation,
        )

    authorization_rejected = False

    def authorize(db: sqlite3.Connection, current: MemoryCandidate) -> None:
        nonlocal authorization_rejected
        # Recheck local CAS and every signed decision/scope/fence after reserving.
        local: list[tuple[str]] = db.execute(
            "SELECT checkpoint_json FROM company_processor_checkpoint WHERE workspace_id=?",
            (context.workspace_id,),
        ).fetchall()
        if not local or local[0][0] != canonical_bytes(model_object(checkpoint)).decode():
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
        try:
            authorize_transition(
                db,
                current,
                context,
                policy,
                owner_keys,
                operation,
                arguments,
                authority.request_digest,
                clock() if clock is not None else datetime.now(UTC),
                verify_original,
            )
        except CompanyAuthorityRejected:
            authorization_rejected = True
            raise
        existing: list[tuple[int]] = db.execute(
            "SELECT 1 FROM company_memory_receipts WHERE workspace_id=? AND request_digest=?",
            (context.workspace_id, authority.request_digest),
        ).fetchall()
        if existing:
            return
        if reservation is None or reservation.checkpoint is None:
            raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
        save_checkpoint(db, context.workspace_id, reservation.checkpoint, checkpoint)
        save_pending_finish(
            db,
            context.workspace_id,
            authority.request_digest,
            PendingFinish(
                operation=operation,
                operation_id=operation_id,
                reservation=reservation,
                original_reservation_retry=reservation.outcome == "already_reserved",
            ),
        )

    guard = (
        provider.effect_guard(
            FreshnessScope(
                provider_instance_id=context.provider, workspace_id=context.workspace_id
            ),
            operation_id,
            reservation,
        )
        if isinstance(provider, CompanyDbFreshnessProvider) and reservation is not None
        else nullcontext()
    )
    with guard:
        try:
            if preflight_rejection is not None:
                authorization_rejected = True
                raise preflight_rejection
            return store.execute(
                workspace_id=context.workspace_id,
                request_digest=authority.request_digest,
                operation=operation,
                arguments=arguments,
                current=scope,
                deletion=deletion,
                now=now,
                authorization=authorize,
            )
        except CompanyAuthorityRejected:
            if (
                authorization_rejected
                and isinstance(provider, CompanyDbFreshnessProvider)
                and reservation is not None
            ):
                provider.cancel_unapplied_under_guard(
                    FreshnessScope(
                        provider_instance_id=context.provider, workspace_id=context.workspace_id
                    ),
                    operation_id,
                    reservation,
                    checkpoint,
                    processor_binding={
                        "candidate_id": candidate_id,
                        "content_digest": candidate.content_digest,
                        "handoff_id": handoff_id,
                    },
                )
            raise
