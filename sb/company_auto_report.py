"""Read immutable, published assessment snapshots with a fixed pagination cut."""

from __future__ import annotations

import base64
import sqlite3

from pydantic import Field, ValidationError

from sb.company_auto_publication import PublishedAssessment
from sb.company_auto_settings import AutoInternalRejected, AutoReportGrant
from sb.company_db_freshness import CompanyDbFreshnessProvider
from sb.company_freshness_anchor import AnchorRejected
from sb.company_freshness_models import Checkpoint, FreshnessScope
from sb.company_internal_effects import memory_request_digest
from sb.effect_values import canonical_bytes
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object

_MAX = 9_007_199_254_740_991
_CONFLICT = frozenset(
    {
        "conflict",
        "ambiguous",
        "mixed",
        "money",
        "contract",
        "tax",
        "outgoing",
        "invite",
        "customer_deletion",
        "prompt_injection",
        "timezone_unknown",
        "source_unknown",
        "fence_advanced",
    }
)


class AutoReportQuery(ClosedModel):
    from_global_sequence: int = Field(ge=0, le=_MAX)
    to_global_sequence: int = Field(ge=0, le=_MAX)
    limit: int = Field(ge=1, le=100)
    cursor: str | None


class AutoReportRow(PublishedAssessment):
    global_sequence: int = Field(ge=1, le=_MAX)


class AutoReportPage(ClosedModel):
    cutoff_from: str
    cutoff_to: str
    epoch: int
    head_sequence: int
    contact_new: int
    calendar_new: int
    progress_new: int
    human_required: int
    conflict_ambiguous: int
    uncertain: int
    rows: list[AutoReportRow]
    next_cursor: str | None


class _Cursor(ClosedModel):
    scope: FreshnessScope
    epoch: int
    from_sequence: int
    requested_to: int
    head_sequence: int
    cutoff_from: str
    cutoff_to: str
    last_sequence: int
    last_operation_id: str


def read_auto_report(
    provider: CompanyDbFreshnessProvider,
    *,
    provider_instance_id: str,
    workspace_id: str,
    grant: AutoReportGrant,
    query: AutoReportQuery,
) -> AutoReportPage:
    if (
        grant.operation != "read_auto_report"
        or grant.purpose != "company_memory_auto_report"
        or grant.principal_id != "principal:jarvis-company-progress"
        or query.from_global_sequence > query.to_global_sequence
    ):
        raise AutoInternalRejected("REPORT_REJECTED")
    scope = FreshnessScope(provider_instance_id=provider_instance_id, workspace_id=workspace_id)
    try:
        with provider.read_only_report(scope) as db:
            heads: list[tuple[str, int]] = db.execute(
                """SELECT s.checkpoint_json,MAX(p.global_sequence)
                FROM company_freshness_scopes s
                JOIN company_freshness_log l ON l.provider_instance_id=s.provider_instance_id
                  AND l.workspace_id=s.workspace_id
                JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
                WHERE s.provider_instance_id=? AND s.workspace_id=?
                GROUP BY s.checkpoint_json""",
                (provider_instance_id, workspace_id),
            ).fetchall()
            if len(heads) != 1:
                raise AutoInternalRejected("COMPANY_FRESHNESS_REQUIRED")
            epoch = Checkpoint.model_validate_json(heads[0][0], strict=True).operational_epoch
            cursor = _decode(query, scope, epoch)
            head = (
                min(query.to_global_sequence, heads[0][1])
                if cursor is None
                else cursor.head_sequence
            )
            if (
                head > heads[0][1]
                or head > query.to_global_sequence
                or head < query.from_global_sequence
            ):
                raise AutoInternalRejected("REPORT_REJECTED")
            rows: list[tuple[int, str, str]] = db.execute(
                """SELECT l.global_sequence,json_extract(l.record_json,'$.snapshot'),l.created_at
                FROM company_freshness_log l
                JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
                WHERE l.provider_instance_id=? AND l.workspace_id=?
                  AND l.phase='registry'
                  AND json_extract(l.record_json,'$.kind')='internal_auto_assessment'
                  AND l.global_sequence<=?
                ORDER BY l.global_sequence,l.operation_id""",
                (provider_instance_id, workspace_id, head),
            ).fetchall()
            cutoff_from = _cutoff(db, scope, query.from_global_sequence)
            cutoff_to = _cutoff(db, scope, head)
            dispositions = _candidate_dispositions(db, scope, head)
    except AutoInternalRejected:
        raise
    except (sqlite3.Error, OSError, ValueError, AnchorRejected) as exc:
        raise AutoInternalRejected("COMPANY_FRESHNESS_REQUIRED") from exc
    if cursor is not None and (cursor.cutoff_from != cutoff_from or cursor.cutoff_to != cutoff_to):
        raise AutoInternalRejected("REPORT_REJECTED")
    # Latest publication at the pinned cut wins, not mutable current candidate state.
    latest: dict[str, AutoReportRow] = {}
    for sequence, raw, _created_at in rows:
        snapshot = PublishedAssessment.model_validate_json(raw, strict=True)
        if snapshot.candidate_id in dispositions:
            disposition_sequence, operation_id, updates = dispositions[snapshot.candidate_id]
            if disposition_sequence > sequence:
                sequence = disposition_sequence
                snapshot = snapshot.model_copy(update={**updates, "operation_id": operation_id})
        if sequence <= query.from_global_sequence:
            continue
        latest[snapshot.candidate_id] = AutoReportRow.model_validate(
            {
                **model_object(snapshot),
                "global_sequence": sequence,
            },
            strict=True,
        )
    built = sorted(latest.values(), key=lambda row: (row.global_sequence, row.operation_id))
    remaining = built
    if cursor is not None:
        key = (cursor.last_sequence, cursor.last_operation_id)
        if not any((row.global_sequence, row.operation_id) == key for row in built):
            raise AutoInternalRejected("REPORT_REJECTED")
        remaining = [row for row in built if (row.global_sequence, row.operation_id) > key]
    page = remaining[: query.limit]
    token = None
    if len(remaining) > query.limit:
        last = page[-1]
        token = (
            base64.urlsafe_b64encode(
                canonical_bytes(
                    model_object(
                        _Cursor(
                            scope=scope,
                            epoch=epoch,
                            from_sequence=query.from_global_sequence,
                            requested_to=query.to_global_sequence,
                            head_sequence=head,
                            cutoff_from=cutoff_from,
                            cutoff_to=cutoff_to,
                            last_sequence=last.global_sequence,
                            last_operation_id=last.operation_id,
                        )
                    )
                )
            )
            .rstrip(b"=")
            .decode("ascii")
        )
    return AutoReportPage(
        cutoff_from=cutoff_from,
        cutoff_to=cutoff_to,
        epoch=epoch,
        head_sequence=head,
        contact_new=sum(
            row.record_kind == "contact" and row.state == "processed_complete" for row in built
        ),
        calendar_new=sum(
            row.record_kind == "calendar" and row.state == "processed_complete" for row in built
        ),
        progress_new=sum(
            row.record_kind == "progress" and row.state == "processed_complete" for row in built
        ),
        human_required=sum(row.classification == "human_required" for row in built),
        conflict_ambiguous=sum(
            row.classification == "human_required"
            and bool(_CONFLICT.intersection(row.reason_codes))
            for row in built
        ),
        uncertain=sum(row.state == "uncertain" for row in built),
        rows=page,
        next_cursor=token,
    )


def _cutoff(db: sqlite3.Connection, scope: FreshnessScope, sequence: int) -> str:
    if sequence == 0:
        initial: list[tuple[str]] = db.execute(
            """SELECT l.created_at FROM company_freshness_log l
            JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
            WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.phase='bootstrap'
            ORDER BY l.global_sequence LIMIT 1""",
            (scope.provider_instance_id, scope.workspace_id),
        ).fetchall()
        if len(initial) != 1:
            raise AutoInternalRejected("REPORT_REJECTED")
        return initial[0][0]
    rows: list[tuple[str]] = db.execute(
        """SELECT l.created_at FROM company_freshness_log l
        JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.global_sequence<=?
        ORDER BY l.global_sequence DESC LIMIT 1""",
        (scope.provider_instance_id, scope.workspace_id, sequence),
    ).fetchall()
    if len(rows) != 1:
        raise AutoInternalRejected("REPORT_REJECTED")
    return rows[0][0]


def _decode(query: AutoReportQuery, scope: FreshnessScope, epoch: int) -> _Cursor | None:
    if query.cursor is None:
        return None
    try:
        if len(query.cursor) > 16_384:
            raise ValueError("cursor too large")
        raw = base64.b64decode(
            query.cursor + "=" * (-len(query.cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        cursor = _Cursor.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError) as exc:
        raise AutoInternalRejected("REPORT_REJECTED") from exc
    if (
        cursor.scope != scope
        or cursor.epoch != epoch
        or cursor.from_sequence != query.from_global_sequence
        or cursor.requested_to != query.to_global_sequence
    ):
        raise AutoInternalRejected("REPORT_REJECTED")
    return cursor


def _candidate_dispositions(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    head: int,
) -> dict[str, tuple[int, str, dict[str, str | None]]]:
    authorities: list[tuple[str, str]] = db.execute(
        """SELECT candidate_id,auto_request_id FROM company_auto_policy_receipts
        WHERE provider_instance_id=? AND workspace_id=?""",
        (scope.provider_instance_id, scope.workspace_id),
    ).fetchall()
    events = {
        memory_request_digest(operation, candidate, request_id): candidate
        for candidate, request_id in authorities
        for operation in ("accept", "complete", "mark_processed")
    }
    completed_events = {
        memory_request_digest("mark_processed", candidate, request_id)
        for candidate, request_id in authorities
    }
    log: list[tuple[int, str, str, str | None, str | None]] = db.execute(
        """SELECT l.global_sequence,l.phase,l.operation_id,
        json_extract(l.record_json,'$.event_digest'),
        json_extract(l.record_json,'$.terminal_state')
        FROM company_freshness_log l
        JOIN company_freshness_publication p ON p.global_sequence=l.global_sequence
        WHERE l.provider_instance_id=? AND l.workspace_id=? AND l.global_sequence<=?
          AND l.phase IN ('reserve','finish') ORDER BY l.global_sequence""",
        (scope.provider_instance_id, scope.workspace_id, head),
    ).fetchall()
    pending: dict[str, tuple[str, bool]] = {}
    dispositions: dict[str, tuple[int, str, dict[str, str | None]]] = {}
    for sequence, phase, operation_id, digest, terminal_state in log:
        if phase == "finish":
            reserved = pending.pop(operation_id, None)
            if reserved is not None:
                candidate, marks_processed = reserved
                if terminal_state == "cancelled":
                    dispositions[candidate] = (sequence, operation_id, {"state": "cancelled"})
                elif terminal_state == "processed_complete" and marks_processed:
                    completed: list[tuple[str, str, str]] = db.execute(
                        """SELECT m.receipt_id,m.created_at,r.record_kind
                        FROM company_memory_receipts m
                        JOIN company_internal_records r ON r.workspace_id=m.workspace_id
                          AND r.source_candidate_id=m.candidate_id
                        JOIN company_freshness_log l ON l.operation_id=? AND l.phase='finish'
                          AND l.provider_instance_id=r.provider_instance_id
                          AND l.workspace_id=r.workspace_id
                          AND json_extract(l.record_json,'$.evidence_digest')=m.receipt_digest
                        WHERE r.provider_instance_id=? AND m.workspace_id=?
                          AND m.candidate_id=? AND m.operation='mark_processed'""",
                        (operation_id, scope.provider_instance_id, scope.workspace_id, candidate),
                    ).fetchall()
                    if len(completed) != 1:
                        raise AutoInternalRejected("COMPANY_FRESHNESS_REQUIRED")
                    receipt_id, processed_at, record_kind = completed[0]
                    dispositions[candidate] = (
                        sequence,
                        operation_id,
                        {
                            "state": "processed_complete",
                            "receipt_id": receipt_id,
                            "processed_at": processed_at,
                            "record_kind": record_kind,
                        },
                    )
                else:
                    _ = dispositions.pop(candidate, None)
        elif digest is not None and digest in events:
            pending[operation_id] = (events[digest], digest in completed_events)
            dispositions[events[digest]] = (sequence, operation_id, {"state": "uncertain"})
    return dispositions
