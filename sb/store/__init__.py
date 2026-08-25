"""L1 store: content-addressed raw blobs and the rebuildable ingest ledger."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never, override

import yaml


class DerivStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LedgerCorrupt(Exception):
    path: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"ledger corrupt at {self.path}: {self.detail}"


@dataclass(frozen=True, slots=True)
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
    match current:
        case DerivStatus.PENDING:
            allowed = target is DerivStatus.RUNNING
        case DerivStatus.RUNNING:
            allowed = target in {DerivStatus.DONE, DerivStatus.FAILED}
        case DerivStatus.DONE | DerivStatus.FAILED:
            allowed = False
        case unreachable:
            assert_never(unreachable)
    if not allowed:
        raise InvalidDerivationTransition(
            deriv_key=key, from_status=current.value, to_status=target.value
        )


def parse_page_frontmatter(
    text: str,
) -> tuple[str, str, str, tuple[tuple[str, str], ...]] | None:
    """Parse K1 frontmatter into (page_id, prompt_version, model_id, origin/hash pairs)."""
    if not text.startswith("---"):
        return None
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return None
    loaded = yaml.safe_load(rest[:end])
    if not isinstance(loaded, dict):
        return None
    page_id = loaded.get("id")
    if not isinstance(page_id, str) or not page_id:
        return None
    compiled = loaded.get("compiled_by")
    parts = compiled.split("|") if isinstance(compiled, str) else []
    prompt, model = (parts[1], parts[2]) if len(parts) >= 3 else ("v1", "unknown")
    pairs: list[tuple[str, str]] = []
    sources = loaded.get("sources")
    if isinstance(sources, list):
        for raw in sources:
            if not isinstance(raw, dict):
                continue
            origin, content_hash = raw.get("origin"), raw.get("hash")
            if isinstance(origin, str) and isinstance(content_hash, str):
                pairs.append((origin, content_hash))
    return page_id, prompt, model, tuple(pairs)
