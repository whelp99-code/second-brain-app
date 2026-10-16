"""Persist the exact original reserve before an acknowledgment can be lost."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from sb.company_auto_settings import AutoInternalRejected
from sb.company_freshness_models import FreshnessScope, ReserveProgressRequest
from sb.company_processor_progress import local_checkpoint
from sb.effect_values import canonical_bytes
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object


class PendingAutoReserve(ClosedModel):
    candidate_id: str
    auto_request_id: str
    command_digest: str
    request: ReserveProgressRequest


def pending_auto_reserve(
    db: sqlite3.Connection, scope: FreshnessScope
) -> PendingAutoReserve | None:
    rows: list[tuple[str]] = db.execute(
        """SELECT intent_json FROM company_internal_pending_reserve
        WHERE provider_instance_id=? AND workspace_id=?""",
        (scope.provider_instance_id, scope.workspace_id),
    ).fetchall()
    if not rows:
        return None
    intent = PendingAutoReserve.model_validate_json(rows[0][0], strict=True)
    if intent.request.scope != scope:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
    return intent


def prepare_auto_reserve(database: Path, intent: PendingAutoReserve) -> PendingAutoReserve:
    scope = intent.request.scope
    with closing(sqlite3.connect(database)) as db, db:
        _ = db.execute("BEGIN IMMEDIATE")
        existing = pending_auto_reserve(db, scope)
        if existing is not None:
            equivalent = intent.model_copy(
                update={
                    "request": intent.request.model_copy(
                        update={"challenge": existing.request.challenge}
                    ),
                }
            )
            if existing != equivalent:
                raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
            return existing
        if (
            local_checkpoint(database, scope.workspace_id, None)
            != intent.request.expected_checkpoint
        ):
            raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
        _ = db.execute(
            "INSERT INTO company_internal_pending_reserve VALUES(?,?,?)",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                canonical_bytes(model_object(intent)).decode(),
            ),
        )
    return intent


def consume_auto_reserve(db: sqlite3.Connection, intent: PendingAutoReserve) -> None:
    changed = db.execute(
        """DELETE FROM company_internal_pending_reserve
        WHERE provider_instance_id=? AND workspace_id=? AND intent_json=?""",
        (
            intent.request.scope.provider_instance_id,
            intent.request.scope.workspace_id,
            canonical_bytes(model_object(intent)).decode(),
        ),
    )
    if changed.rowcount != 1:
        raise AutoInternalRejected("COMPANY_PROGRESS_UNCERTAIN")
