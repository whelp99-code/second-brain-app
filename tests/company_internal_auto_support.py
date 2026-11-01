from __future__ import annotations

import hashlib
import sqlite3
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.company_auto_policy import policy_digest
from sb.company_auto_settings import (
    AutoInternalContext,
    AutoInternalSettings,
    AutoReportGrant,
    AutoTriggerGrant,
    InternalAutoPolicyV1,
    bind_policy_signer,
)
from sb.company_freshness import (
    Checkpoint,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessScope,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
    StoreHeads,
    StoreProgress,
)
from sb.company_freshness_migrations import apply_component_migration
from sb.company_internal_effects import install_auto_policy
from sb.company_internal_migrations import apply_internal_auto_migration
from sb.company_memory import CompanyMemoryStore
from sb.company_processor_progress import save_checkpoint
from sb.effect_values import canonical_bytes, format_instant
from sb.source_access import SourceAccess

WORKSPACE = "12345678-1234-4234-8234-123456789abc"
PROVIDER = "provider:company-test"
DELETION = (2, "sha256:" + "ab" * 32)
NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
ACCESS = SourceAccess("principal:mail-ms", ("project:company",), "policy:1")
SIMULATED_ANCHOR = "SIMULATED_ANCHOR"


def policy() -> InternalAutoPolicyV1:
    return InternalAutoPolicyV1(
        schema_version="company-internal-auto/v1",
        policy_version=1,
        internal_email_suffixes=[".internal"],
        internal_assignees=["principal:mail-ms"],
        allowed_kinds=["contact", "calendar", "progress"],
    )


def settings() -> AutoInternalSettings:
    private = Ed25519PrivateKey.generate()
    return AutoInternalSettings(
        provider_instance_id=PROVIDER,
        installation_id="install:auto-test",
        policy=policy(),
        signer=bind_policy_signer(
            "principal:company-internal-automation", "policy-auto:test", private
        ),
    )


def context(checkpoint: Checkpoint) -> AutoInternalContext:
    return AutoInternalContext(
        workspace_id=WORKSPACE,
        owner=ACCESS.owner,
        projects=ACCESS.projects,
        policy_revision=ACCESS.policy_revision,
        deletion_sequence=DELETION[0],
        deletion_set_root=DELETION[1],
        observed_checkpoint=checkpoint,
        now=NOW,
    )


def trigger(at: datetime = NOW) -> AutoTriggerGrant:
    return AutoTriggerGrant(
        schema_version=1,
        operation="auto_process_internal",
        purpose="company_internal_auto_trigger",
        principal_id="principal:jarvis-company-progress",
        limit=100,
        issued_at=format_instant(at),
        expires_at=format_instant(at + timedelta(seconds=60)),
    )


def report_grant() -> AutoReportGrant:
    return AutoReportGrant(
        schema_version=1,
        operation="read_auto_report",
        purpose="company_memory_auto_report",
        principal_id="principal:jarvis-company-progress",
    )


def zero_progress() -> StoreProgress:
    root = "sha256:" + hashlib.sha256(b"empty").hexdigest()
    return StoreProgress(
        receipt_sequence=0,
        receipt_root=root,
        terminal_sequence=0,
        terminal_root=root,
        deletion_sequence=0,
        deletion_root=root,
    )


def checkpoint_at(sequence: int, root: str) -> Checkpoint:
    return Checkpoint(
        operational_epoch=1,
        approval_policy_version=1,
        approval_binding_digest="sha256:" + "11" * 32,
        revocation_sequence=0,
        revocation_root="sha256:" + "22" * 32,
        stores=StoreHeads(jarvis=zero_progress(), second_brain=zero_progress()),
        intent_sequence=sequence,
        intent_root=root,
    )


def initial_checkpoint() -> Checkpoint:
    return checkpoint_at(0, "sha256:" + "33" * 32)


class SimulatedAnchorProvider:
    def __init__(self, start: Checkpoint) -> None:
        self.checkpoint: Checkpoint = start
        self.reserves: int = 0
        self.finishes: int = 0
        self.anchor: str = SIMULATED_ANCHOR
        self._reserved: dict[str, ReserveProgressResponse] = {}
        self.assessments: list[str] = []
        self.policies: list[tuple[str, str, str]] = []

    def effect_guard(
        self,
        scope: FreshnessScope,
        operation_id: str,
        reservation: ReserveProgressResponse,
    ) -> AbstractContextManager[None]:
        assert scope == reservation.scope
        assert reservation == self._reserved[operation_id]
        return nullcontext()

    def require_auto_policy(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None:
        assert scope.provider_instance_id == PROVIDER
        assert source_context_digest.startswith("sha256:")
        self.policies.append((policy_digest, key_id, key_fingerprint))

    def auto_policy_guard(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> AbstractContextManager[None]:
        self.require_auto_policy(
            scope, policy_digest, key_id, key_fingerprint, source_context_digest
        )
        return nullcontext()

    def require_auto_policy_under_guard(
        self,
        scope: FreshnessScope,
        policy_digest: str,
        key_id: str,
        key_fingerprint: str,
        source_context_digest: str,
    ) -> None:
        self.require_auto_policy(
            scope, policy_digest, key_id, key_fingerprint, source_context_digest
        )

    def publish_completed_assessments(
        self, scope: FreshnessScope, expected: Checkpoint
    ) -> Checkpoint:
        assert scope.provider_instance_id == PROVIDER
        assert expected == self.checkpoint
        return self.checkpoint

    def publish_assessment(
        self,
        scope: FreshnessScope,
        assessment_digest: str,
        expected: Checkpoint,
    ) -> Checkpoint:
        assert scope.provider_instance_id == PROVIDER
        assert expected == self.checkpoint
        self.assessments.append(assessment_digest)
        return self.checkpoint

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        status = "ready" if request.observed_checkpoint == self.checkpoint else "mismatch"
        return ReadFreshnessResponse(
            schema_version=2,
            scope=request.scope,
            challenge=request.challenge,
            status=status,
            checkpoint=self.checkpoint if status == "ready" else None,
        )

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse:
        self.reserves += 1
        existing = self._reserved.get(request.operation_id)
        if existing is not None:
            return existing
        if request.expected_checkpoint != self.checkpoint:
            return ReserveProgressResponse(
                schema_version=2,
                scope=request.scope,
                challenge=request.challenge,
                outcome="conflict",
                checkpoint=None,
                reservation_id=None,
            )
        self.checkpoint = _advance(self.checkpoint, request.operation_id, "reserve")
        response = ReserveProgressResponse(
            schema_version=2,
            scope=request.scope,
            challenge=request.challenge,
            outcome="reserved",
            checkpoint=self.checkpoint,
            reservation_id="reservation:company-db:" + request.operation_id.removeprefix("sha256:"),
        )
        self._reserved[request.operation_id] = response
        return response

    def finish_progress(self, request: FinishProgressRequest) -> FinishProgressResponse:
        self.finishes += 1
        reserved = self._reserved.get(request.operation_id)
        if reserved is None or reserved.reservation_id != request.reservation_id:
            return FinishProgressResponse(
                schema_version=2,
                scope=request.scope,
                challenge=request.challenge,
                outcome="conflict",
                checkpoint=None,
            )
        if request.expected_checkpoint != reserved.checkpoint:
            return FinishProgressResponse(
                schema_version=2,
                scope=request.scope,
                challenge=request.challenge,
                outcome="conflict",
                checkpoint=None,
            )
        self.checkpoint = _advance(self.checkpoint, request.evidence_digest, "finish")
        return FinishProgressResponse(
            schema_version=2,
            scope=request.scope,
            challenge=request.challenge,
            outcome="recorded",
            checkpoint=self.checkpoint,
        )


def _advance(current: Checkpoint, token: str, phase: str) -> Checkpoint:
    root = (
        "sha256:"
        + hashlib.sha256(
            canonical_bytes(
                {
                    "phase": phase,
                    "previous": current.intent_root,
                    "token": token,
                }
            )
        ).hexdigest()
    )
    return current.model_copy(
        update={"intent_sequence": current.intent_sequence + 1, "intent_root": root}
    )


def prepare(database: Path, bound: AutoInternalSettings) -> None:
    store = CompanyMemoryStore(database)
    store.close()
    apply_component_migration(database, "freshness", now=format_instant(NOW))
    with sqlite3.connect(database) as db:
        _ = apply_internal_auto_migration(db, NOW)
        _ = install_auto_policy(db, bound, WORKSPACE, NOW)
        save_checkpoint(db, WORKSPACE, initial_checkpoint())


def receive(database: Path, candidate_id: str, event_id: str, content: str) -> None:
    store = CompanyMemoryStore(database)
    try:
        _ = store.receive(
            workspace_id=WORKSPACE,
            candidate_id=candidate_id,
            source_system="mail",
            source_locator="msg/" + candidate_id,
            source_event_id=event_id,
            content=content,
            parser_version="mail:1",
            locator={"kind": "message", "ordinal": 1},
            access=ACCESS,
            deletion=DELETION,
        )
    finally:
        store.close()


def contact_body(name: str = "Ada Lovelace", email: str = "ada@mail.internal") -> str:
    return f"sb-internal-mail/v1\nkind: contact\nname: {name}\nemail: {email}\n"


def calendar_body() -> str:
    return (
        "sb-internal-mail/v1\n"
        "kind: calendar\n"
        "title: Internal standup\n"
        "starts_at: 2026-10-16T09:00:00.000Z\n"
        "ends_at: 2026-10-16T09:30:00.000Z\n"
        "timezone: Asia/Seoul\n"
        "internal_assignee: principal:mail-ms\n"
    )


def progress_body() -> str:
    return (
        "sb-internal-mail/v1\n"
        "kind: progress\n"
        "subject: Internal review\n"
        "status: noted\n"
        "internal_assignee: principal:mail-ms\n"
        "next_internal_action: file the note\n"
    )


def publish_head(database: Path, sequence: int = 1) -> None:
    with sqlite3.connect(database) as db:
        _ = db.execute(
            """CREATE TABLE IF NOT EXISTS company_freshness_publication (
            global_sequence INTEGER PRIMARY KEY, published_at TEXT NOT NULL)""",
        )
        _ = db.execute(
            "INSERT OR IGNORE INTO company_freshness_publication VALUES(?,?)",
            (sequence, "2026-10-16T09:00:00.000Z"),
        )


def scope() -> FreshnessScope:
    return FreshnessScope(provider_instance_id=PROVIDER, workspace_id=WORKSPACE)


def installed_digest() -> str:
    return policy_digest(policy())
