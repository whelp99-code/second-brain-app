"""Bounded read-only reconciliation; all durable state lives in the adapter cursor.

The opt-in budget is ``[caps] max_db_reconcile_rows_per_run`` (absent = legacy).
``change_sequence`` is a producer contract: a non-null integer revision sequence,
strictly increasing on each change, not an event timestamp or an insert-only id.
Catalog inspection detects that named capability; it cannot prove producer behavior.
PK passes still run with that capability, because a sequence cannot reveal removals.

A pass fixes its upper PK fence and remembers the previously live keys. Only an
exhausted pass may check missing keys, in bounded batches, against the source again.
The result is a source_deleted *candidate*, never an instruction to erase evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal, Protocol, TypedDict

from sb.connectors.unified_db_mapping import (
    EmitCtx,
    Item,
    JVal,
    Mark,
    Scalar,
    ScanTable,
    cell_text,
    emit_row,
    quote,
)
from sb.contracts import SourceRef


class Result(Protocol):
    def fetchone(self) -> tuple[Scalar, ...] | None: ...
    def fetchall(self) -> list[tuple[Scalar, ...]]: ...


class Session(Protocol):
    def execute(self, query: str, params: Sequence[Scalar] | None = None) -> Result: ...


class KnownRow(TypedDict):
    digest: str
    source: str
    uri: str
    revision: int
    deleted: bool


class SequenceMark(TypedDict):
    value: int
    id: str


class TableState(TypedDict):
    known: dict[str, KnownRow]
    phase: Literal["idle", "scan", "verify"]
    after: str | None
    fence: str | None
    pending: dict[str, bool]
    held: list[str]
    completed: int
    sequence: SequenceMark | None


class Checkpoint(TypedDict):
    version: Literal[1]
    next_table: int
    tables: dict[str, TableState]


class _JsonLoads(Protocol):
    def __call__(self, value: str) -> JVal: ...


def _load(value: str) -> JVal:
    loads: _JsonLoads | None = getattr(json, "loads", None)
    assert loads is not None
    return loads(value)


def _obj(value: JVal) -> dict[str, JVal]:
    if not isinstance(value, dict):
        raise TypeError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    return value


def _text(value: JVal) -> str:
    if not isinstance(value, str):
        raise TypeError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    return value


def _integer(value: JVal) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    return value


def _boolean(value: JVal) -> bool:
    if not isinstance(value, bool):
        raise TypeError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    return value


def _read_table(value: JVal) -> TableState:
    raw = _obj(value)
    phase = _text(raw["phase"])
    if phase != "idle" and phase != "scan" and phase != "verify":
        raise ValueError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    held = raw["held"]
    if not isinstance(held, list):
        raise TypeError("UNIFIED_DB_RECONCILE_CURSOR_INVALID")
    known: dict[str, KnownRow] = {}
    for pk, entry in _obj(raw["known"]).items():
        row = _obj(entry)
        known[pk] = {
            "digest": _text(row["digest"]), "source": _text(row["source"]),
            "uri": _text(row["uri"]), "revision": _integer(row["revision"]),
            "deleted": _boolean(row["deleted"]),
        }
    sequence = None if raw["sequence"] is None else _obj(raw["sequence"])
    return {
        "known": known, "phase": phase,
        "after": None if raw["after"] is None else _text(raw["after"]),
        "fence": None if raw["fence"] is None else _text(raw["fence"]),
        "pending": {pk: _boolean(flag) for pk, flag in _obj(raw["pending"]).items()},
        "held": [_text(source) for source in held], "completed": _integer(raw["completed"]),
        "sequence": None if sequence is None else {
            "value": _integer(sequence["value"]), "id": _text(sequence["id"]),
        },
    }


def read_checkpoint(cursor: str | None) -> Checkpoint | None:
    if not cursor:
        return None
    try:
        payload = _load(cursor)
    except json.JSONDecodeError:
        # Legacy cursors have always tolerated non-JSON input.
        return None
    if not isinstance(payload, dict) or "_reconcile" not in payload:
        return None
    raw = _obj(payload["_reconcile"])
    if raw.get("version") != 1:
        raise ValueError("UNIFIED_DB_RECONCILE_CURSOR_VERSION")
    return {
        "version": 1, "next_table": _integer(raw["next_table"]),
        "tables": {name: _read_table(table) for name, table in _obj(raw["tables"]).items()},
    }


def with_checkpoint(legacy: str, state: Checkpoint | None) -> str:
    if state is None:
        return legacy
    return json.dumps({**_obj(_load(legacy)), "_reconcile": state}, separators=(",", ":"), sort_keys=True)


def has_change_sequence(session: Session, table: ScanTable) -> bool:
    rows = session.execute(
        "SELECT column_name FROM information_schema.columns "
        + "WHERE table_schema = %s AND table_name = %s "
        + "AND column_name = 'change_sequence' AND is_nullable = 'NO' "
        + "AND data_type IN ('smallint', 'integer', 'bigint')",
        (table.schema, table.table),
    ).fetchall()
    return bool(rows)


class Reconciler:
    def __init__(self, state: Checkpoint | None, emit: EmitCtx) -> None:
        self.state: Checkpoint = state if state is not None else {
            "version": 1, "next_table": 0, "tables": {},
        }
        self.emit: EmitCtx = emit
        # A disabled source during any part of a pass cannot become a removal.
        for table in self.state["tables"].values():
            if table["phase"] != "idle":
                table["held"] = sorted(set(table["held"]) | emit.disabled)

    def table_state(self, table: ScanTable) -> TableState:
        return self.state["tables"].setdefault(table.name, {
            "known": {}, "phase": "idle", "after": None, "fence": None,
            "pending": {}, "held": [], "completed": 0, "sequence": None,
        })

    def observe(self, table: ScanTable, row: tuple[Scalar, ...]) -> tuple[Item | None, Mark]:
        state = self.table_state(table)
        pk = cell_text(row[0])
        _ = state["pending"].pop(pk, None)
        item, mark = emit_row(table, row, self.emit)
        if item is None or item[2].get("skip_reason"):
            return item, mark
        ref, body, meta = item
        digest = hashlib.sha256(body).hexdigest()
        previous = state["known"].get(pk)
        if previous and not previous["deleted"] and previous["digest"] == digest:
            return None, mark
        revision = 1 if previous is None else previous["revision"] + 1
        state["known"][pk] = {
            "digest": digest, "source": cell_text(row[3]), "uri": ref.source_uri,
            "revision": revision, "deleted": False,
        }
        # A local revision also distinguishes A -> B -> A and delete -> reappearance.
        version = f"reconcile:{revision}:{digest}"
        return (
            SourceRef(ref.source_id, ref.source_uri, version), body, {**meta, "cursor": version},
        ), mark

    def segment(
        self, session: Session, tables: tuple[ScanTable, ...], limit: int,
    ) -> tuple[list[Item], int]:
        if not tables or limit <= 0:
            return [], 0
        index = self.state["next_table"] % len(tables)
        table = tables[index]
        state = self.table_state(table)
        relation = f"{quote(table.schema)}.{quote(table.table)}"
        pk = quote(table.pk)
        if state["phase"] == "idle":
            top = session.execute(
                f"SELECT {pk} FROM {relation} ORDER BY {pk} DESC LIMIT 1"
            ).fetchone()
            state["fence"] = None if top is None else cell_text(top[0])
            state["after"] = None
            state["pending"] = {
                key: True for key, known in state["known"].items() if not known["deleted"]
            }
            state["held"] = sorted(self.emit.disabled)
            state["phase"] = "scan"
        items: list[Item]
        if state["phase"] == "verify":
            items, used = self._verify_missing(session, table, state, limit)
        else:
            cols = (table.pk, table.occurred_at, table.project_id, table.source_id, *table.text)
            query = f"SELECT {', '.join(quote(col) for col in cols)} FROM {relation}"
            query += f" WHERE {pk} <= %s"
            params: tuple[Scalar, ...] = (state["fence"],)
            if state["after"] is not None:
                query += f" AND {pk} > %s"
                params += (state["after"],)
            rows = session.execute(
                f"{query} ORDER BY {pk} ASC LIMIT %s", (*params, limit),
            ).fetchall()
            items = []
            for row in rows:
                item, _ = self.observe(table, row)
                if item is not None:
                    items.append(item)
                state["after"] = cell_text(row[0])
            used = len(rows)
            # A full-sized segment proves only the cap, not the end of the pass.
            if len(rows) < limit:
                state["phase"] = "verify"
        if state["phase"] == "verify" and not state["pending"]:
            state["completed"] += 1
            state["phase"] = "idle"
            state["after"] = state["fence"] = None
            state["held"] = []
        # Rotate even at a cap of one; a busy first table must not starve others.
        self.state["next_table"] = (index + 1) % len(tables)
        return items, used

    def _verify_missing(
        self, session: Session, table: ScanTable, state: TableState, limit: int,
    ) -> tuple[list[Item], int]:
        keys = sorted(state["pending"])[:limit]
        if not keys:
            return [], 0
        cols = (table.pk, table.occurred_at, table.project_id, table.source_id, *table.text)
        relation = f"{quote(table.schema)}.{quote(table.table)}"
        placeholders = ", ".join("%s" for _ in keys)
        rows = session.execute(
            f"SELECT {', '.join(quote(col) for col in cols)} FROM {relation} "
            + f"WHERE {quote(table.pk)} IN ({placeholders}) ORDER BY {quote(table.pk)} ASC",
            tuple(keys),
        ).fetchall()
        items: list[Item] = []
        present = {cell_text(row[0]) for row in rows}
        for row in rows:
            item, _ = self.observe(table, row)
            if item is not None:
                items.append(item)
        for key in keys:
            _ = state["pending"].pop(key, None)
            known = state["known"][key]
            if key in present or known["source"] in state["held"] or known["deleted"]:
                continue
            known["revision"] += 1
            known["deleted"] = True
            version = f"reconcile:{known['revision']}:source_deleted:{known['digest']}"
            items.append((
                SourceRef(self.emit.adapter_id, known["uri"], version), b"",
                {"relative_path": table.name, "cursor": version, "skip_reason": "source_deleted"},
            ))
        return items, len(keys)
