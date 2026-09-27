"""Publish an admitted tombstone set when a terminal effect will never seal one.

Acceptance writes the signed tombstone delta before the effect runs. A terminal
failure then leaves the replica ahead of the active manifest, and every read
raises TOMBSTONE_SET_STALE. Deferring admission would desynchronize a caller
that already chained from the admitted root. A content-identical successor
carries the admitted set: suppression without a content change cannot resurrect
bytes, and a crash before activation is finished by the next maintain or replay.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast, final

from pydantic import ValidationError

from sb.effect_values import parse_instant
from sb.effect_write_requests import open_request_directory
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationExpectation,
    GenerationMutation,
    GenerationMutationError,
    GenerationOperation,
)
from sb.generations import Generation, GenerationStore
from sb.life_lock import VaultPublicationBusy, publication_lock
from sb.owner_effects import OwnerEffect
from sb.sqlite_values import OPTIONAL_SQL_ROW, SQL_ROWS, SqlCell, SqlRow


@final
class TombstoneAdmissionError(RuntimeError):
    """A tombstone-admission publication could not be completed."""

    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Admission:
    generation_id: str
    head: str
    tree: str
    sequence: int
    set_root: str
    admitted_at: datetime


def publish_terminal_tombstones(service: GenerationMutationService, now: datetime) -> bool:
    """Align the active manifest with a tombstone set no in-flight effect will publish."""
    del now
    try:
        with publication_lock(service.store.active_link):
            directory = open_request_directory(service.requests.pending)
            try:
                fcntl.flock(directory, fcntl.LOCK_EX)
                return _publish_while_admission_locked(service)
            finally:
                fcntl.flock(directory, fcntl.LOCK_UN)
                os.close(directory)
    except VaultPublicationBusy:
        return False


def _publish_while_admission_locked(service: GenerationMutationService) -> bool:
    admission = _claim_or_activate(service)
    if admission is None:
        return False
    try:
        _ = service.mutate(
            GenerationMutation(
                mutation_id="tombstone-admission:" + admission.set_root,
                operation=GenerationOperation.EFFECT,
                now=admission.admitted_at,
                authority=GenerationAuthority(
                    GenerationExpectation(admission.generation_id, admission.head, admission.tree),
                    (admission.sequence, admission.set_root),
                ),
                apply=lambda _root: None,
                recover=lambda _generation: None,
            )
        )
    except GenerationMutationError as exc:
        if exc.code not in {"EFFECT_PRIOR_STALE", "TOMBSTONE_SET_STALE"} or not _aligned(service):
            raise
    return True


def _claim_or_activate(service: GenerationMutationService) -> _Admission | None:
    with service.store.writer():
        if not service.store.active_link.is_symlink():
            return None
        parent = service.store.active()
        target = service.requests.tombstone_high_water()
        observed = (parent.manifest.tombstone_sequence, parent.manifest.tombstone_set_root)
        if observed == target or observed[0] > target[0]:
            return None
        admission = _admission(service, parent, target)
        if admission is None:
            return None
        existing = _successor(service.store, parent, target)
        if existing is not None:
            service.store.activate(existing, parent, admission.admitted_at, lock_held=True)
            return None
        return admission


def _admission(
    service: GenerationMutationService,
    parent: Generation,
    target: tuple[int, str],
) -> _Admission | None:
    if _owner_effect_pending(service.store.state_root) or _request_in_flight(service):
        return None
    rows = _rows(cast(
        list[sqlite3.Row],
        service.requests.db.execute(
            "SELECT sequence,set_root,request_id,created_at FROM tombstone_replica"
            + " WHERE sequence>? ORDER BY sequence",
            (parent.manifest.tombstone_sequence,),
        ).fetchall(),
    ))
    expected = parent.manifest.tombstone_sequence
    admitted_at: datetime | None = None
    last_root: str | None = None
    for sequence, set_root, request_id, created_at in rows:
        expected += 1
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != expected
            or not isinstance(set_root, str)
            or not isinstance(request_id, str)
        ):
            return None
        if not _terminal_without_generation(service, request_id):
            return None
        admitted_at = _instant(created_at)
        last_root = set_root
    if admitted_at is None or last_root is None or expected != target[0] or last_root != target[1]:
        return None
    return _Admission(
        parent.generation_id,
        parent.head,
        parent.tree,
        target[0],
        target[1],
        admitted_at,
    )


def _request_in_flight(service: GenerationMutationService) -> bool:
    row = _optional_row(cast(
        sqlite3.Row | None,
        service.requests.db.execute(
            "SELECT 1 FROM requests WHERE state IN ('pending','processing') LIMIT 1"
        ).fetchone(),
    ))
    return row is not None


def _terminal_without_generation(service: GenerationMutationService, request_id: str) -> bool:
    row = _optional_row(cast(
        sqlite3.Row | None,
        service.requests.db.execute(
            "SELECT state,result_generation_id FROM requests WHERE request_id=?",
            (request_id,),
        ).fetchone(),
    ))
    if row is None or row[1] is not None:
        return False
    state = row[0]
    return isinstance(state, str) and state in {"failed", "expired", "reapproval_required"}


def _owner_effect_pending(state_root: Path) -> bool:
    folder = state_root / "owner-effects"
    if not folder.is_dir():
        return False
    for path in sorted(folder.glob("*.json")):
        if not path.is_file():
            continue
        try:
            effect = OwnerEffect.model_validate_json(path.read_bytes())
        except ValidationError:
            return True
        if effect.result is None:
            return True
    return False


def _successor(
    store: GenerationStore,
    parent: Generation,
    target: tuple[int, str],
) -> Generation | None:
    rows = _rows(cast(
        list[sqlite3.Row],
        store.journal.execute(
            "SELECT generation_id FROM activations WHERE parent_generation_id=?"
            + " AND phase IN ('sealed','switch_intent','activated','disposing')"
            + " ORDER BY generation_id",
            (parent.generation_id,),
        ).fetchall(),
    ))
    for (generation_id,) in rows:
        if not isinstance(generation_id, str) or not (store.generations / generation_id).is_dir():
            continue
        generation = store.generation(generation_id)
        observed = (generation.manifest.tombstone_sequence, generation.manifest.tombstone_set_root)
        if observed == target:
            return generation
    return None


def _aligned(service: GenerationMutationService) -> bool:
    if not service.store.active_link.is_symlink():
        return False
    parent = service.store.active()
    return (
        parent.manifest.tombstone_sequence,
        parent.manifest.tombstone_set_root,
    ) == service.requests.tombstone_high_water()


def _rows(fetched: list[sqlite3.Row]) -> list[SqlRow]:
    return SQL_ROWS.validate_python([tuple(row) for row in fetched], strict=True)


def _optional_row(fetched: sqlite3.Row | None) -> SqlRow | None:
    if fetched is None:
        return None
    return OPTIONAL_SQL_ROW.validate_python(tuple(fetched), strict=True)


def _instant(value: SqlCell) -> datetime:
    if not isinstance(value, str):
        raise TombstoneAdmissionError("TOMBSTONE_ADMISSION_INVALID")
    try:
        return parse_instant(value)
    except ValueError as exc:
        raise TombstoneAdmissionError("TOMBSTONE_ADMISSION_INVALID") from exc
