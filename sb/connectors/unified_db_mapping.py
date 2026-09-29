"""Checked-in unified-db table map and row/project emit helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, override

from sb.connectors.base import ItemMeta
from sb.contracts import SourceRef

_IDENT: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
type JVal = str | int | float | bool | None | list[JVal] | dict[str, JVal]
type Scalar = str | int | bool | datetime | list[str] | None
type Mark = tuple[datetime, str]
type Item = tuple[SourceRef, bytes, ItemMeta]


class _Loads(Protocol):
    def __call__(
        self, s: str, *, object_pairs_hook: Callable[[list[tuple[str, JVal]]], dict[str, JVal]]
    ) -> JVal: ...


@dataclass(frozen=True, slots=True)
class MappingError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class CatalogSpec:
    schema: str
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanTable:
    name: str
    schema: str
    table: str
    pk: str
    occurred_at: str
    project_id: str
    source_id: str
    text: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LowValueRule:
    """One (project, summary) pair whose rows carry no recallable content.

    unified-db records a bare agent heartbeat as `summary = "[<project>] session"`
    with no project_id. Those rows are the largest single group in the source and
    say nothing a later question could be answered from, so they never become units.
    """

    project: str
    summary: str


@dataclass(frozen=True, slots=True)
class MappingSpec:
    page_size: int
    projects: CatalogSpec
    sources: CatalogSpec
    tables: tuple[ScanTable, ...]
    low_value: tuple[LowValueRule, ...] = ()


# Adjustment point B: recorded from unified-db init SQL (catalog/memory/evidence).
# Event/evidence watermarks are occurred_at + primary key (lossless ties).
DEFAULT_MAPPING: Final = MappingSpec(
    1000,
    CatalogSpec("catalog", "projects", ("project_id", "display_name", "aliases", "active")),
    CatalogSpec("catalog", "sources", ("source_id", "enabled")),
    (
        ScanTable(
            "memory.events",
            "memory",
            "events",
            "event_id",
            "occurred_at",
            "project_id",
            "source_id",
            ("actor", "action", "status", "summary"),
        ),
        ScanTable(
            "evidence.items",
            "evidence",
            "items",
            "evidence_id",
            "occurred_at",
            "project_id",
            "source_id",
            ("uri", "sensitivity"),
        ),
    ),
    (LowValueRule("ClaudeProbe", "session"),),
)


def load_mapping() -> MappingSpec:
    """Return the checked-in table map."""
    return DEFAULT_MAPPING


def catalog_sql(spec: CatalogSpec) -> str:
    return f"SELECT {', '.join(quote(col) for col in spec.columns)} FROM {quote(spec.schema)}.{quote(spec.table)}"


def select_sql(table: ScanTable, watermarked: bool, *, change_sequence: bool = False) -> str:
    cols = (table.pk, table.occurred_at, table.project_id, table.source_id, *table.text)
    order_column = "change_sequence" if change_sequence else table.occurred_at
    if change_sequence:
        cols = (*cols, order_column)
    relation = f"{quote(table.schema)}.{quote(table.table)}"
    order = f"ORDER BY {quote(order_column)} ASC, {quote(table.pk)} ASC"
    select = f"SELECT {', '.join(quote(col) for col in cols)} FROM {relation}"
    if watermarked:
        return f"{select} WHERE ({quote(order_column)}, {quote(table.pk)}) > (%s, %s) {order} LIMIT %s"
    return f"{select} {order} LIMIT %s"


def quote(name: str) -> str:
    if _IDENT.fullmatch(name) is None:
        raise MappingError(name)
    return f'"{name}"'


@dataclass(frozen=True, slots=True)
class AmbiguousProjectError(Exception):
    name: str

    @override
    def __str__(self) -> str:
        return f"ambiguous project: {self.name}"


@dataclass(frozen=True, slots=True)
class UnknownProjectError(Exception):
    name: str

    @override
    def __str__(self) -> str:
        return f"unknown project: {self.name}"


@dataclass(slots=True)
class EmitCtx:
    """Per-scan project lookup and disabled-source skip set."""

    adapter_id: str
    lookup: dict[str, str]
    disabled: frozenset[str]
    seen_disabled: set[str]
    low_value: tuple[LowValueRule, ...] = ()


def build_lookup(rows: list[tuple[Scalar, ...]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for project_id, display_name, aliases, _active in rows:
        if not isinstance(project_id, str):
            raise UnknownProjectError(str(project_id))
        names = [project_id]
        if isinstance(display_name, str):
            names.append(display_name)
        names.extend(_alias_names(aliases))
        for name in names:
            key = name.strip().casefold()
            if not key:
                continue
            existing = lookup.get(key)
            if existing is not None and existing != project_id:
                raise AmbiguousProjectError(name)
            lookup[key] = project_id
    return lookup


def _alias_names(raw: Scalar) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(raw)
    if not isinstance(raw, str) or not raw:
        return ()
    trim = " \t\"'[]{}"
    return tuple(part.strip(trim) for part in raw.split(",") if part.strip(trim))


def disabled_sources(rows: list[tuple[Scalar, ...]]) -> frozenset[str]:
    return frozenset(
        source for source, enabled in rows if isinstance(source, str) and enabled is False
    )


def emit_row(table: ScanTable, row: tuple[Scalar, ...], ctx: EmitCtx) -> tuple[Item | None, Mark]:
    pk = cell_text(row[0])
    stamp = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(cell_text(row[1]))
    source = cell_text(row[3])
    mark = (stamp, pk)
    if source in ctx.disabled:
        if source in ctx.seen_disabled:
            return None, mark
        ctx.seen_disabled.add(source)
        skip: Item = (
            SourceRef(ctx.adapter_id, f"unified-db:{source}:disabled", "disabled"),
            b"",
            {"relative_path": source, "skip_reason": "disabled"},
        )
        return skip, mark
    project = resolve_project(row[2], ctx.lookup)
    texts = list(zip(table.text, (cell_text(value) for value in row[4:]), strict=False))
    if is_low_value(project, dict(texts).get("summary", ""), ctx.low_value):
        return None, mark
    fields = [
        (table.pk, pk),
        (table.occurred_at, stamp.isoformat()),
        (table.project_id, project),
        (table.source_id, source),
        *texts,
    ]
    token = f"{stamp.isoformat()}|{pk}"
    meta: ItemMeta = {"relative_path": table.name, "cursor": token}
    body = "\n".join(f"{key}: {value}" for key, value in fields).encode()
    item: Item = (
        SourceRef(ctx.adapter_id, f"unified-db:{project}:{table.name}:{pk}", token),
        body,
        meta,
    )
    return item, mark


def split_summary_label(summary: str) -> tuple[str, str]:
    """Split `"[project] body"` into its label and body; an unlabelled summary keeps both."""
    text = summary.strip()
    if not text.startswith("["):
        return "", text
    closing = text.find("]")
    if closing == -1:
        return "", text
    return text[1:closing].strip(), text[closing + 1 :].strip()


def is_low_value(project: str, summary: str, rules: tuple[LowValueRule, ...]) -> bool:
    """Whether this row is a contentless heartbeat one of `rules` names.

    The row carries the project either in its own column or as the `[project]`
    label unified-db writes into the summary, so both spellings are matched.
    """
    if not rules:
        return False
    label, body = split_summary_label(summary)
    for rule in rules:
        wanted = rule.project.casefold()
        if label.casefold() != wanted and project.casefold() != wanted:
            continue
        if body.casefold() == rule.summary.casefold():
            return True
    return False


def resolve_project(raw: Scalar, lookup: dict[str, str]) -> str:
    if raw is None or raw == "":
        return "global"
    if not isinstance(raw, str):
        raise UnknownProjectError(str(raw))
    found = lookup.get(raw.strip().casefold())
    if found is None:
        raise UnknownProjectError(raw)
    return found


def cell_text(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return ",".join(value)
    return str(value)


def decode_cursor(cursor: str | None) -> dict[str, Mark]:
    if cursor is None or cursor == "":
        return {}
    try:
        loaded = _loads()(cursor, object_pairs_hook=_pairs)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    out: dict[str, Mark] = {}
    for key, value in loaded.items():
        if not isinstance(value, dict):
            continue
        stamp, pk = value.get("occurred_at"), value.get("id")
        if isinstance(stamp, str) and isinstance(pk, str) and stamp and pk:
            out[key] = (datetime.fromisoformat(stamp), pk)
    return out


def encode_cursor(marks: dict[str, Mark]) -> str:
    payload = {
        name: {"occurred_at": stamp.isoformat(), "id": pk}
        for name, (stamp, pk) in sorted(marks.items())
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _pairs(pairs: list[tuple[str, JVal]]) -> dict[str, JVal]:
    return dict(pairs)


def _loads() -> _Loads:
    fn: _Loads | None = getattr(json, "loads", None)
    assert fn is not None
    return fn
