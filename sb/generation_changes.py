"""Content-free page deltas captured before sealed predecessors are disposed."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from collections.abc import Generator
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

# Receipt bound, not a vault-size bound. A recent-changes read materializes one
# generation's delta and rejects anything larger than this (or _MAX_TREE_BYTES).
# The production vault is ~9k pages / ~1.3MB of ls-tree metadata; that census must
# not be stored or capped as if every page were a change.
_MAX_PAGES: Final = 4096
_MAX_GENERATIONS: Final = 4096
_MAX_TREE_BYTES: Final = 4 * 1024 * 1024
_LS_TREE_TIMEOUT: Final = 30.0


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


def _parse_page(row: bytes) -> tuple[str, str] | None:
    metadata, separator, path = row.partition(b"\t")
    fields = metadata.split()
    if not separator or len(fields) != 3 or fields[1] != b"blob":
        raise GenerationChangesError("GENERATION_CHANGES_INVALID")
    try:
        name = path.decode("utf-8")
        blob = fields[2].decode("ascii")
    except UnicodeError as exc:
        raise GenerationChangesError("GENERATION_CHANGES_INVALID") from exc
    if not name.endswith(".md"):
        return None
    return name[:-3], blob


def _stream_pages(generation: GenerationSnapshot) -> Generator[tuple[str, str], None, None]:
    """Yield (page_id, blob) in git path order without retaining the tree."""
    proc = subprocess.Popen(
        ["git", "-C", str(generation.root), "ls-tree", "-rz", generation.head,
         "--", "wiki", "daily", "conflicts"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    stdout = proc.stdout
    if stdout is None:
        raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
    pending = b""
    deadline = time.monotonic() + _LS_TREE_TIMEOUT
    try:
        while True:
            if time.monotonic() > deadline:
                raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
            chunk = stdout.read(65536)
            if not chunk:
                break
            pending += chunk
            while True:
                cut = pending.find(b"\0")
                if cut < 0:
                    break
                row, pending = pending[:cut], pending[cut + 1:]
                if not row:
                    continue
                parsed = _parse_page(row)
                if parsed is not None:
                    yield parsed
            if len(pending) > _MAX_TREE_BYTES:
                raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
        if pending:
            raise GenerationChangesError("GENERATION_CHANGES_INVALID")
        if proc.wait(timeout=5) != 0:
            raise GenerationChangesError("GENERATION_CHANGES_UNAVAILABLE")
    finally:
        if proc.poll() is None:
            proc.kill()
            _ = proc.wait(timeout=5)
        stdout.close()


def _push(delta: list[tuple[str, str]], page: str, change: str) -> None:
    if len(delta) >= _MAX_PAGES:
        raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
    delta.append((page, change))


def _git_before(left: str, right: str) -> bool:
    # ls-tree emits paths in byte order, not Unicode code-point order.
    return left.encode("utf-8") < right.encode("utf-8")


def _baseline_delta(generation: GenerationSnapshot) -> list[tuple[str, str]]:
    """Genesis has no predecessor. A vault that already exceeds the receipt bound
    is the baseline itself: listing every page as added would fail the seal and
    would report unchanged pages as changes. Smaller genesis still records adds.
    """
    pages = _stream_pages(generation)
    delta: list[tuple[str, str]] = []
    try:
        for page, _blob in pages:
            _push(delta, page, "added")
    except GenerationChangesError as exc:
        if exc.args != ("GENERATION_CHANGES_BUDGET",):
            raise
        return []
    finally:
        pages.close()
    return sorted(delta)


def _diff_delta(generation: GenerationSnapshot, parent: GenerationSnapshot) -> list[tuple[str, str]]:
    current = _stream_pages(generation)
    previous = _stream_pages(parent)
    delta: list[tuple[str, str]] = []
    try:
        left = next(previous, None)
        right = next(current, None)
        while left is not None or right is not None:
            if right is None or (left is not None and _git_before(left[0], right[0])):
                assert left is not None
                _push(delta, left[0], "deleted")
                left = next(previous, None)
            elif left is None or _git_before(right[0], left[0]):
                _push(delta, right[0], "added")
                right = next(current, None)
            else:
                if left[1] != right[1]:
                    _push(delta, right[0], "modified")
                left = next(previous, None)
                right = next(current, None)
    finally:
        current.close()
        previous.close()
    return sorted(delta)


def record_generation_changes(db: sqlite3.Connection, generation: GenerationSnapshot, parent: GenerationSnapshot | None) -> None:
    if parent is not None:
        manifest = load_verified_manifest(parent.root)
        if manifest["generation_id"] != parent.generation_id or manifest["head"] != parent.head:
            raise GenerationChangesError("GENERATION_CHANGES_STALE")
    delta = _baseline_delta(generation) if parent is None else _diff_delta(generation, parent)
    encoded = json.dumps(delta, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_TREE_BYTES:
        raise GenerationChangesError("GENERATION_CHANGES_BUDGET")
    _ = db.execute("INSERT INTO generation_changes VALUES(?,?,?,?,NULL)",
        (generation.generation_id, None if parent is None else parent.generation_id,
         generation.head, encoded))


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
