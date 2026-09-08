"""Build model-bound cited-record vectors in an unpublished generation only."""
from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
import struct
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sb.effect_values import JsonObject, canonical_bytes
from sb.generation_integrity import load_verified_manifest
from sb.memory_records import MemoryRecordError, MemoryRecordV1, parse_page_records
from sb.page_metadata import frontmatter_value
from sb.vector_rebuild import EmbeddingUnavailable

if TYPE_CHECKING:
    from sb.embeddings import Encoder, ModelIdentity

_LOGGER = logging.getLogger(__name__)
_BATCH_SIZE = 64
_DOMAIN = b"second-brain/generation-record-vectors/v1\0"


@dataclass(frozen=True, slots=True)
class VectorContent:
    model_id: str
    revision: str
    dim: int
    row_count: int
    rows_digest: str

    def as_dict(self) -> JsonObject:
        return {"format": "record-f32-v1", **asdict(self)}


def vector_blob(vector: Sequence[float], dim: int) -> bytes:
    if len(vector) != dim or not all(math.isfinite(value) for value in vector):
        raise EmbeddingUnavailable("invalid generation embedding")
    try:
        raw = struct.pack("<" + "f" * dim, *vector)
        values = cast(tuple[float, ...], struct.unpack("<" + "f" * dim, raw))
    except (OverflowError, struct.error) as exc:
        raise EmbeddingUnavailable("invalid generation embedding") from exc
    norm = sum(value * value for value in values)
    if not 1.1754943508222875e-38 <= norm <= 3.4028234663852886e38:
        raise EmbeddingUnavailable("invalid generation embedding")
    return raw


def _previous(root: Path | None, identity: ModelIdentity) -> sqlite3.Connection | None:
    if root is None:
        return None
    _ = load_verified_manifest(root)
    conn = sqlite3.connect((root / ".sb/vectors.db").as_uri() + "?mode=ro", uri=True)
    try:
        exists = cast(tuple[str] | None, conn.execute("SELECT name FROM sqlite_master WHERE name='vector_info'").fetchone())
        if exists is not None and conn.execute(
            "SELECT model_id,revision,dim FROM vector_info"
        ).fetchall() == [(identity.model_id, identity.revision, identity.dim)]:
            return conn
    except BaseException:
        conn.close()
        raise
    conn.close()
    return None


def _section(raw: bytes, record: MemoryRecordV1) -> str:
    headings = [line.lstrip("#").strip() for line in
                raw[:record.citation_span_start].decode("utf-8").splitlines() if line.startswith("#")]
    return headings[-1] if headings else ""


def _fill(conn: sqlite3.Connection, previous: sqlite3.Connection | None,
          pages: Sequence[tuple[str, bytes]], encoder: Encoder, identity: ModelIdentity) -> VectorContent:
    if (identity.dim != 1024 or not identity.model_id or not identity.revision or encoder.identity != identity):
        raise EmbeddingUnavailable("generation embedding identity invalid")
    pending: list[tuple[str, str, MemoryRecordV1]] = []
    count = 0

    def insert(page: str, section: str, record: MemoryRecordV1, blob: bytes) -> None:
        nonlocal count
        _ = conn.execute("INSERT INTO record_vectors VALUES(?,?,?,?,?,?,?)",
                         (record.record_id, page, section, record.record_digest,
                          record.record_text, record.record_text_digest, blob))
        count += 1

    def flush() -> None:
        if not pending:
            return
        encoded = encoder.encode(tuple(record.record_text for _, _, record in pending))
        if encoder.identity != identity or len(encoded) != len(pending):
            raise EmbeddingUnavailable("generation embedding identity/count changed")
        for (page, section, record), vector in zip(pending, encoded, strict=True):
            insert(page, section, record, vector_blob(vector, identity.dim))
        pending.clear()

    for page, raw in sorted(pages):
        records = parse_page_records(raw, page)
        text = raw.decode("utf-8")
        _ = conn.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (page, page.split("/")[0],
                         *(frontmatter_value(text, field) for field in ("status", "updated", "source_ref"))))
        seen: set[str] = set()
        for record in records:
            if record.record_id in seen:
                continue
            seen.add(record.record_id)
            row = None if previous is None else cast(tuple[bytes] | None, previous.execute(
                "SELECT embedding FROM record_vectors WHERE record_id=? AND record_digest=?",
                (record.record_id, record.record_digest)).fetchone())
            section = _section(raw, record)
            if row is not None:
                if len(row[0]) != identity.dim * 4:
                    raise EmbeddingUnavailable("invalid previous generation embedding")
                insert(page, section, record, row[0])
            else:
                pending.append((page, section, record))
                if len(pending) == _BATCH_SIZE:
                    flush()
    flush()
    if encoder.identity != identity:
        raise EmbeddingUnavailable("generation embedding identity changed")
    digest = hashlib.sha256(_DOMAIN)
    rows = conn.execute("SELECT record_id,page_id,section,record_digest,text_digest,embedding "
                        + "FROM record_vectors ORDER BY page_id,record_id")
    for row in cast(Iterable[tuple[str, str, str, str, str, bytes]], rows):
        _ = digest.update(canonical_bytes({"record_id": row[0], "page_id": row[1], "section": row[2],
            "record_digest": row[3], "text_digest": row[4],
            "vector_digest": "sha256:" + hashlib.sha256(row[5]).hexdigest()}) + b"\n")
    content = VectorContent(identity.model_id, identity.revision, identity.dim, count, "sha256:" + digest.hexdigest())
    _ = conn.execute("INSERT INTO vector_info VALUES(?,?,?,?,?)",
                     (content.model_id, content.revision, content.dim, content.row_count, content.rows_digest))
    return content


def prepare_vectors(root: Path, pages: Sequence[tuple[str, bytes]], *,
                    parent_root: Path | None, enabled: bool) -> VectorContent | None:
    """Expected encoder unavailability produces a disabled successor, never stale vectors."""
    if not enabled:
        return None
    path = root / ".sb/vectors.db"
    previous: sqlite3.Connection | None = None
    created = False
    try:
        from sb.embeddings import resolve_encoder

        encoder = resolve_encoder()
        identity = encoder.identity
        previous = _previous(parent_root, identity)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        # The generation builder owns this private staging tree exclusively.
        with path.open("xb"):
            pass
        created = True
        path.chmod(0o600)
        conn = sqlite3.connect(path)
        try:
            _ = conn.executescript("""
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                PRAGMA secure_delete=ON;
                CREATE TABLE vector_info(model_id TEXT,revision TEXT,dim INTEGER,
                                         row_count INTEGER,rows_digest TEXT);
                CREATE TABLE pages(page_id TEXT PRIMARY KEY,kind TEXT,status TEXT,updated TEXT,source_ref TEXT);
                CREATE TABLE record_vectors(record_id TEXT PRIMARY KEY,page_id TEXT NOT NULL,
                    section TEXT NOT NULL,record_digest TEXT NOT NULL,text TEXT NOT NULL,
                    text_digest TEXT NOT NULL,embedding BLOB NOT NULL CHECK(length(embedding)=4096));
                CREATE INDEX vectors_by_page ON record_vectors(page_id,record_id);
            """)
            with conn:
                content = _fill(conn, previous, pages, encoder, identity)
        finally:
            conn.close()
        return content
    except (EmbeddingUnavailable, ImportError, MemoryRecordError):
        if created:
            path.unlink(missing_ok=True)
            for suffix in ("-journal", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        _LOGGER.warning("generation vectors unavailable; sealing lexical-only generation")
        return None
    finally:
        if previous is not None:
            previous.close()
