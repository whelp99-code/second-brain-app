"""L1 store: content-addressed raw blobs and the rebuildable ingest ledger."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast, override

type SqlCell = str | int | None
type SqlRow = tuple[SqlCell, ...]


class DerivStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


_ALLOWED: Final[dict[DerivStatus, frozenset[DerivStatus]]] = {
    DerivStatus.PENDING: frozenset({DerivStatus.RUNNING}),
    DerivStatus.RUNNING: frozenset({DerivStatus.DONE, DerivStatus.FAILED}),
    DerivStatus.DONE: frozenset(),
    DerivStatus.FAILED: frozenset(),
}


@dataclass(slots=True)
class LedgerCorrupt(Exception):
    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"ledger corrupt at {self.path}: {self.detail}"


@dataclass(slots=True)
class InvalidDerivationTransition(Exception):
    deriv_key: str
    from_status: str
    to_status: str

    @override
    def __str__(self) -> str:
        return (
            f"invalid derivation transition {self.from_status}->{self.to_status} "
            f"for {self.deriv_key}"
        )


@dataclass(frozen=True, slots=True)
class SourceItem:
    source_id: str
    source_uri: str
    source_version: str
    content_hash: str
    first_seen_run: str
    last_seen_run: str


@dataclass(frozen=True, slots=True)
class UnitRow:
    unit_id: str
    content_hash: str
    span: str
    text_hash: str
    normalizer_version: str


@dataclass(frozen=True, slots=True)
class DerivationOutput:
    output_hash: str
    output_path: str


@dataclass(frozen=True, slots=True)
class Derivation:
    deriv_key: str
    stage: str
    output_hash: str | None
    output_path: str | None
    status: str
    attempts: int
    error: str | None
    run_id: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class Run:
    run_id: str
    started_at: str
    finished_at: str | None
    git_commit: str | None
    status: str


@dataclass(frozen=True, slots=True)
class RunStage:
    run_id: str
    stage: str
    started_at: str
    finished_at: str | None
    status: str
    attempted: int
    written: int
    errors: int
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PageFacts:
    page_id: str
    prompt_version: str | None
    model_id: str | None
    sources: tuple[tuple[str, str], ...]
    derivation_key: str | None = None


def deriv_key(unit_ids: Sequence[str], stage: str, prompt_version: str, model_id: str) -> str:
    """sha256 of sorted unit_ids + stage + prompt_version + model_id (NUL-joined)."""
    payload = "\0".join((*sorted(unit_ids), stage, prompt_version, model_id))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_file_cursor(*, mtime_ns: int, size: int, sha256: str) -> str:
    """K2 file cursor: mtime_ns:size:sha256."""
    return f"{mtime_ns}:{size}:{sha256}"


def format_postgres_cursor(updated_at: str) -> str:
    """K2 postgres cursor: ISO updated_at."""
    return updated_at


def format_jsonl_cursor(byte_offset: int) -> str:
    """K2 JSONL cursor: integer byte offset."""
    return str(byte_offset)


def require_transition(key: str, current: DerivStatus, target: DerivStatus) -> None:
    """Enforce pending->running->done|failed. reset_stale_running bypasses this."""
    if target not in _ALLOWED[current]:
        raise InvalidDerivationTransition(
            deriv_key=key, from_status=current.value, to_status=target.value
        )


def parse_compiled_by(stamp: str) -> tuple[str, str] | None:
    """Return (prompt_version, model_id) only for `sb/<pkg>|<prompt>|<model>`."""
    parts = stamp.split("|")
    if len(parts) < 3 or not parts[0].startswith("sb/"):
        return None
    prompt, model = parts[1], parts[2]
    if prompt == "" or model == "":
        return None
    return prompt, model


def parse_page_frontmatter(text: str) -> PageFacts | None:
    """Parse K1 frontmatter into recoverable page facts. No invented prompt/model."""
    if not text.startswith("---"):
        return None
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return None
    page_id: str | None = None
    compiled: str | None = None
    stored_derivation_key: str | None = None
    sources: list[tuple[str, str]] = []
    current: dict[str, str] = {}
    in_sources = False
    for raw_line in rest[:end].splitlines():
        line = raw_line.rstrip()
        if line == "" or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t", "-")):
            _flush_source(current, sources)
            current = {}
            in_sources = False
            key, sep, value = line.partition(":")
            if not sep:
                continue
            field, parsed = key.strip(), _unquote(value.strip())
            if field == "id":
                page_id = parsed
            elif field == "compiled_by":
                compiled = parsed
            elif field == "derivation_key":
                stored_derivation_key = parsed
            elif field == "sources":
                in_sources = True
            continue
        if not in_sources:
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            _flush_source(current, sources)
            current = {}
            item = stripped[2:]
            if ":" in item:
                item_key, _, item_value = item.partition(":")
                current[item_key.strip()] = _unquote(item_value.strip())
            continue
        if ":" in stripped:
            item_key, _, item_value = stripped.partition(":")
            current[item_key.strip()] = _unquote(item_value.strip())
    _flush_source(current, sources)
    if page_id is None or page_id == "":
        return None
    stamp = parse_compiled_by(compiled) if compiled is not None else None
    prompt = stamp[0] if stamp is not None else None
    model = stamp[1] if stamp is not None else None
    return PageFacts(page_id, prompt, model, tuple(sources), stored_derivation_key)


def _flush_source(current: dict[str, str], sources: list[tuple[str, str]]) -> None:
    origin = current.get("origin")
    content_hash = current.get("hash")
    if origin is not None and content_hash is not None:
        sources.append((origin, content_hash))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


class LedgerTables:
    """Mutable row snapshot. Mutation is the load/write purpose of this holder."""

    def __init__(self) -> None:
        self.source_items: dict[tuple[str, str, str], SourceItem] = {}
        self.cursors: dict[str, tuple[str, str]] = {}
        self.units: dict[str, UnitRow] = {}
        self.derivations: dict[str, Derivation] = {}
        self.runs: dict[str, Run] = {}


def assert_ledger_integrity(path: Path) -> None:
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            row = cast(SqlRow | None, conn.execute("PRAGMA integrity_check").fetchone())
    except sqlite3.DatabaseError as exc:
        raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
    detail = "" if row is None else str(row[0])
    if detail != "ok":
        raise LedgerCorrupt(path=str(path), detail=detail or "integrity_check failed")


def load_ledger_tables(path: Path) -> LedgerTables:
    tables = LedgerTables()
    src_sql = (
        "SELECT source_id,source_uri,source_version,content_hash,"
        + "first_seen_run,last_seen_run FROM source_item"
    )
    unit_sql = "SELECT unit_id,content_hash,span,text_hash,normalizer_version FROM unit"
    deriv_sql = (
        "SELECT deriv_key,stage,output_hash,output_path,status,attempts,"
        + "error,run_id,finished_at FROM derivation"
    )
    try:
        with closing(sqlite3.connect(str(path))) as conn:
            for cells in _query_rows(conn, src_sql):
                item = SourceItem(
                    _cell_text(cells[0]),
                    _cell_text(cells[1]),
                    _cell_text(cells[2]),
                    _cell_text(cells[3]),
                    _cell_text(cells[4]),
                    _cell_text(cells[5]),
                )
                tables.source_items[(item.source_id, item.source_uri, item.content_hash)] = item
            for cells in _query_rows(conn, "SELECT source_id,position,updated_at FROM cursor"):
                tables.cursors[_cell_text(cells[0])] = (
                    _cell_text(cells[1]),
                    _cell_text(cells[2]),
                )
            for cells in _query_rows(conn, unit_sql):
                unit = UnitRow(
                    _cell_text(cells[0]),
                    _cell_text(cells[1]),
                    _cell_text(cells[2]),
                    _cell_text(cells[3]),
                    _cell_text(cells[4]),
                )
                tables.units[unit.unit_id] = unit
            for cells in _query_rows(conn, deriv_sql):
                row = Derivation(
                    _cell_text(cells[0]),
                    _cell_text(cells[1]),
                    _cell_optional_text(cells[2]),
                    _cell_optional_text(cells[3]),
                    _cell_text(cells[4]),
                    _cell_int(cells[5]),
                    _cell_optional_text(cells[6]),
                    _cell_optional_text(cells[7]),
                    _cell_optional_text(cells[8]),
                )
                tables.derivations[row.deriv_key] = row
            for cells in _query_rows(
                conn, "SELECT run_id,started_at,finished_at,git_commit,status FROM run"
            ):
                run = Run(
                    _cell_text(cells[0]),
                    _cell_text(cells[1]),
                    _cell_optional_text(cells[2]),
                    _cell_optional_text(cells[3]),
                    _cell_text(cells[4]),
                )
                tables.runs[run.run_id] = run
    except sqlite3.DatabaseError as exc:
        raise LedgerCorrupt(path=str(path), detail=str(exc)) from exc
    return tables


def _query_rows(conn: sqlite3.Connection, sql: str) -> Iterator[SqlRow]:
    rows = cast(list[SqlRow], conn.execute(sql).fetchall())
    yield from rows


def _cell_text(cell: SqlCell) -> str:
    return "" if cell is None else str(cell)


def _cell_optional_text(cell: SqlCell) -> str | None:
    return None if cell is None else str(cell)


def _cell_int(cell: SqlCell) -> int:
    return 0 if cell is None else int(cell)
