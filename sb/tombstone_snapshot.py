"""Verified provider tombstone-chain snapshots and blocked target identities."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from pydantic import TypeAdapter

from sb.effect_values import JsonObject, digest

GENESIS_ROOT = "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"

type TombstoneRow = tuple[int, str, str, str, str, str, str, str, str, str, str, str, str, str]
type TargetRow = tuple[int, str, str, str, str, str, str, str, int, int]
_TOMBSTONE_ROWS: TypeAdapter[list[TombstoneRow]] = TypeAdapter(list[TombstoneRow])
_TARGET_ROWS: TypeAdapter[list[TargetRow]] = TypeAdapter(list[TargetRow])
_TARGET_STRINGS: TypeAdapter[tuple[str, str, str, str, str, str, str]] = TypeAdapter(
    tuple[str, str, str, str, str, str, str]
)


class TombstoneSnapshotError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TombstoneChainEntry:
    sequence: int
    tombstone_id: str
    operation: str
    lane_id: str
    target_manifest_digest: str
    scope_digest: str
    authority_receipt_digest: str
    payload_digest: str
    keyed_subject_digest: str
    effective_at: str
    previous_root: str
    set_root: str

    def as_dict(self) -> JsonObject:
        return {
            "sequence": self.sequence,
            "tombstone_id": self.tombstone_id,
            "operation": self.operation,
            "lane_id": self.lane_id,
            "target_manifest_digest": self.target_manifest_digest,
            "scope_digest": self.scope_digest,
            "authority_receipt_digest": self.authority_receipt_digest,
            "payload_digest": self.payload_digest,
            "keyed_subject_digest": self.keyed_subject_digest,
            "effective_at": self.effective_at,
            "previous_root": self.previous_root,
            "set_root": self.set_root,
        }


@dataclass(frozen=True, slots=True)
class BlockedTargetIdentity:
    sequence: int
    target_digest: str
    source_identity_digest: str
    content_identity_digest: str
    citation_identity_digest: str
    subject_identity_digest: str
    page_id_digest: str
    page_content_digest: str
    citation_span_start: int
    citation_span_end: int


@dataclass(frozen=True, slots=True)
class TombstoneSnapshot:
    sequence: int
    set_root: str
    snapshot_digest: str
    entries: tuple[TombstoneChainEntry, ...]
    targets: tuple[BlockedTargetIdentity, ...]


def register_target_identities(
    connection: sqlite3.Connection,
    sequence: int,
    targets: tuple[JsonObject, ...],
) -> None:
    if sequence <= 0 or not targets:
        raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID")
    rows: list[TargetRow] = []
    for target in targets:
        strings = tuple(
            target.get(name)
            for name in (
                "target_digest",
                "source_identity_full",
                "content_identity_full",
                "citation_identity_full",
                "subject_digest",
                "page_id",
                "page_content_digest",
            )
        )
        start = target.get("citation_span_start")
        end = target.get("citation_span_end")
        if not all(isinstance(value, str) for value in strings):
            raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID")
        if not isinstance(start, int) or isinstance(start, bool):
            raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID")
        if not isinstance(end, int) or isinstance(end, bool):
            raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID")
        parsed = _TARGET_STRINGS.validate_python(strings)
        page_id = parsed[5]
        rows.append(
            (
                sequence,
                parsed[0],
                parsed[1],
                parsed[2],
                parsed[3],
                parsed[4],
                "sha256:" + hashlib.sha256(page_id.encode("utf-8")).hexdigest(),
                parsed[6],
                start,
                end,
            )
        )
    _ = connection.executemany(
        "INSERT INTO tombstone_target_identities VALUES(?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _entry(values: TombstoneRow) -> TombstoneChainEntry:
    return TombstoneChainEntry(
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
        values[6],
        values[7],
        values[8],
        values[9],
        values[10],
        values[11],
    )


def _target(values: TargetRow) -> BlockedTargetIdentity:
    return BlockedTargetIdentity(*values)


def verified_snapshot(connection: sqlite3.Connection) -> TombstoneSnapshot:
    try:
        raw_entries = _TOMBSTONE_ROWS.validate_python(
            connection.execute("SELECT * FROM tombstone_replica ORDER BY sequence").fetchall()
        )
    except ValueError as exc:
        raise TombstoneSnapshotError("TOMBSTONE_SET_STALE") from exc
    entries = tuple(_entry(row) for row in raw_entries)
    previous = GENESIS_ROOT
    for expected_sequence, entry in enumerate(entries, start=1):
        value = entry.as_dict()
        core = {
            name: value[name]
            for name in (
                "sequence",
                "operation",
                "lane_id",
                "target_manifest_digest",
                "scope_digest",
                "authority_receipt_digest",
                "payload_digest",
                "keyed_subject_digest",
                "effective_at",
                "previous_root",
            )
        }
        observed = digest("tombstone_chain", core)
        if (
            entry.sequence != expected_sequence
            or entry.previous_root != previous
            or entry.set_root != observed
            or entry.tombstone_id != "memtomb:v1:" + observed[7:]
        ):
            raise TombstoneSnapshotError("TOMBSTONE_SET_STALE")
        previous = observed
    try:
        raw_targets = _TARGET_ROWS.validate_python(
            connection.execute(
                "SELECT * FROM tombstone_target_identities ORDER BY sequence,target_digest"
            ).fetchall()
        )
    except ValueError as exc:
        raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID") from exc
    targets = tuple(_target(row) for row in raw_targets)
    destructive_sequences = {
        entry.sequence for entry in entries if entry.operation in {"correct", "forget"}
    }
    if destructive_sequences != {target.sequence for target in targets}:
        raise TombstoneSnapshotError("TOMBSTONE_TARGET_INVENTORY_INVALID")
    return TombstoneSnapshot(
        sequence=len(entries),
        set_root=previous,
        snapshot_digest=digest(
            "tombstone_chain",
            {
                "entries": [entry.as_dict() for entry in entries],
                "targets": [
                    {
                        "sequence": target.sequence,
                        "target_digest": target.target_digest,
                        "source_identity_digest": target.source_identity_digest,
                        "content_identity_digest": target.content_identity_digest,
                        "citation_identity_digest": target.citation_identity_digest,
                        "subject_identity_digest": target.subject_identity_digest,
                    }
                    for target in targets
                ],
            },
        ),
        entries=entries,
        targets=targets,
    )


def root_at(connection: sqlite3.Connection, sequence: int) -> tuple[int, str]:
    snapshot = verified_snapshot(connection)
    if sequence == 0:
        return 0, GENESIS_ROOT
    if sequence < 0 or sequence > snapshot.sequence:
        raise TombstoneSnapshotError("TOMBSTONE_SET_STALE")
    return sequence, snapshot.entries[sequence - 1].set_root
