"""Content-free page deltas captured before sealed predecessors are disposed."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol

from pydantic import TypeAdapter

from sb.effect_values import format_instant, parse_instant
from sb.generation_integrity import load_verified_manifest


class GenerationSnapshot(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def generation_id(self) -> str: ...

    @property
    def head(self) -> str: ...

_MAX_PAGES: Final = 4096
_MAX_GENERATIONS: Final = 4096
_MAX_TREE_BYTES: Final = 4 * 1024 * 1024


class GenerationChangesError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChangeRow:
    page_id: str
    change: str
    date: str

    def as_dict(self) -> dict[str, str]:
        return {"page_id": self.page_id, "change": self.change, "date": self.date}


_DELTAS: Final = TypeAdapter(tuple[tuple[str, str], ...])
type ChangeSetRow = tuple[str | None, str, str, str | None]
_ROW: Final[TypeAdapter[ChangeSetRow | None]] = TypeAdapter(ChangeSetRow | None)


def initialize_generation_changes(db: sqlite3.Connection) -> None:
    _ = db.execute("""CREATE TABLE IF NOT EXISTS generation_changes (
        generation_id TEXT PRIMARY KEY, parent_generation_id TEXT, head TEXT NOT NULL,
        delta TEXT NOT NULL, activated_at TEXT
    )""")


def _pages(generation: GenerationSnapshot) -> Mapping[str, str]:
    # The sealed tree is finite; cap both decoded page count and serialized metadata.
    result = subprocess.run(["git", "-C", str(generation.root), "ls-tree", "-rz", generation.head,
        "--", "wiki", "daily", "conflicts"], capture_output=True, check=False, timeout=30)
    if result.returncode or len(result.stdout) > _MAX_TREE_BYTES:
        raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
    pages: dict[str, str] = {}
    for row in result.stdout.split(b"\0"):
        if not row:
            continue
        metadata, separator, path = row.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[1] != b"blob":
            raise GenerationChangesError("GENERATION_CHANGES_INVALID")
        name = path.decode("utf-8")
        if name.endswith(".md"):
            pages[name[:-3]] = fields[2].decode("ascii")
        if len(pages) > _MAX_PAGES:
            raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
    return pages


def record_generation_changes(db: sqlite3.Connection, generation: GenerationSnapshot, parent: GenerationSnapshot | None) -> None:
    if parent is not None:
        manifest = load_verified_manifest(parent.root)
        if manifest["generation_id"] != parent.generation_id or manifest["head"] != parent.head:
            raise GenerationChangesError("GENERATION_CHANGES_STALE")
    current = _pages(generation)
    previous: Mapping[str, str] = {} if parent is None else _pages(parent)
    delta = [(page, "added" if page not in previous else "deleted" if page not in current else "modified")
             for page in sorted(current.keys() | previous.keys()) if current.get(page) != previous.get(page)]
    _ = db.execute("INSERT INTO generation_changes VALUES(?,?,?,?,NULL)",
        (generation.generation_id, None if parent is None else parent.generation_id,
         generation.head, json.dumps(delta, separators=(",", ":"))))


def activate_generation_changes(db: sqlite3.Connection, generation_id: str, now: datetime) -> None:
    _ = db.execute("UPDATE generation_changes SET activated_at=COALESCE(activated_at,?) WHERE generation_id=?",
                   (format_instant(now), generation_id))


def generation_recent_changes(root: Path, journal_path: Path, days: int) -> tuple[ChangeRow, ...]:
    """Read a bounded activated ancestor chain under the caller's generation read pin."""
    manifest = load_verified_manifest(root)
    generation_id = manifest["generation_id"]
    if not isinstance(generation_id, str):
        raise GenerationChangesError("GENERATION_CHANGES_INVALID")
    cutoff = datetime.now(UTC) - timedelta(days=max(days, 0))
    rows: list[ChangeRow] = []
    try:
        with closing(sqlite3.connect(journal_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            _ = db.execute("BEGIN")
            seen: set[str] = set()
            for index in range(_MAX_GENERATIONS):
                if generation_id in seen:
                    raise GenerationChangesError("GENERATION_CHANGES_INVALID")
                seen.add(generation_id)
                row = _ROW.validate_python(db.execute(
                    "SELECT parent_generation_id,head,delta,activated_at FROM generation_changes WHERE generation_id=?",
                    (generation_id,)).fetchone())
                if row is None:
                    raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
                parent, head, encoded, activated = row
                if activated is None:
                    raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
                if index == 0 and (head != manifest["head"] or parent != manifest["parent_generation_id"]):
                    raise GenerationChangesError("GENERATION_CHANGES_STALE")
                instant = parse_instant(activated)
                if instant < cutoff:
                    return tuple(rows)
                if len(encoded) > _MAX_TREE_BYTES:
                    raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
                delta = _DELTAS.validate_json(encoded)
                if len(delta) > _MAX_PAGES * 2:
                    raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
                for page, change in delta:
                    if change not in {"added", "modified", "deleted"}:
                        raise GenerationChangesError("GENERATION_CHANGES_INVALID")
                    rows.append(ChangeRow(page, change, instant.date().isoformat()))
                if parent is None:
                    return tuple(rows)
                generation_id = parent
    except (sqlite3.Error, ValueError, OSError) as exc:
        raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE") from exc
    raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
