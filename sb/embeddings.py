"""Local BGE-M3 embeddings into a separate sqlite-vec store."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TextIO

from sb.config import load_config
from sb.search import committed_paths, committed_text, git_run
from sb.vector_rebuild import EmbeddingUnavailable as EmbeddingUnavailable  # noqa: PLC0414
from sb.vector_rebuild import publish_vectors

VECTOR_DIM: Final = 1024
DEFAULT_MODEL_ID: Final = "BAAI/bge-m3"
DEFAULT_REVISION: Final = "5617a9f61b028005a4858fdac845db406aefb181"
_DB_NAME: Final = "vectors.db"
_PREFIXES: Final = ("wiki/", "daily/")
_WARMUP_SCRIPT: Final = (
    "import sys\nfrom sentence_transformers import SentenceTransformer\n"
    "SentenceTransformer(sys.argv[1], revision=sys.argv[2])\nprint(sys.argv[2])\n"
)
_ENCODE_SCRIPT: Final = (
    "import json,sys\nfrom sentence_transformers import SentenceTransformer\n"
    "m=SentenceTransformer(sys.argv[1], revision=sys.argv[2], local_files_only=True)\n"
    "for row in m.encode(json.load(sys.stdin), normalize_embeddings=True):\n"
    " print(','.join(str(float(x)) for x in row))\n"
)


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    model_id: str
    revision: str
    dim: int


@dataclass(frozen=True, slots=True)
class ChunkRef:
    page_id: str
    section: str
    content_hash: str


class Encoder(Protocol):
    @property
    def identity(self) -> ModelIdentity: ...

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class _RemoteEncoder:
    identity: ModelIdentity

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        raw = _run_st(_ENCODE_SCRIPT, self.identity, json.dumps(list(texts)))
        try:
            return tuple(
                tuple(float(part) for part in line.split(",")) for line in raw.splitlines() if line
            )
        except ValueError as exc:
            raise EmbeddingUnavailable("invalid embedding process output") from exc


def vectors_path(vault_root: Path) -> Path:
    return Path(vault_root) / ".sb" / _DB_NAME


def embedding_deriv_key(chunk: ChunkRef, identity: ModelIdentity) -> str:
    payload = "\0".join(
        (
            chunk.page_id,
            chunk.section,
            chunk.content_hash,
            identity.model_id,
            identity.revision,
            str(identity.dim),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_vault_root() -> Path:
    env = os.environ.get("SB_VAULT")
    return Path(env) if env else Path(load_config().vault_root)


def sqlite_vec_available() -> bool:
    return _vec_cli() is not None


def run_vec_sql(path: Path, sql: str, *, read_only: bool = False, lock_fd: int | None = None) -> str:
    cli, ext = _vec_cli(), _vec0_path()
    if cli is None or ext is None:
        raise EmbeddingUnavailable("sqlite-vec missing")
    mode = ["-readonly"] if read_only else []
    done = subprocess.run(
        [cli, *mode, "-separator", "\x1f", "-newline", "\x1e", str(path), f".load {ext}", sql],
        capture_output=True,
        text=True,
        check=False,
        pass_fds=() if lock_fd is None else (lock_fd,),
    )
    if done.returncode != 0:
        raise EmbeddingUnavailable(done.stderr.strip() or "vec sql failed")
    return done.stdout


def run_vec_script(path: Path, script: TextIO, *, lock_fd: int) -> None:
    """Execute a generated ASCII SQL stream; callers hex-encode all text values."""
    cli, ext = _vec_cli(), _vec0_path()
    if cli is None or ext is None:
        raise EmbeddingUnavailable("sqlite-vec missing")
    _ = script.seek(0)
    done = subprocess.run(
        [cli, "-batch", "-bail", str(path), f".load {ext}", ".read /dev/stdin"],
        stdin=script, capture_output=True, text=True, check=False, pass_fds=(lock_fd,),
    )
    if done.returncode != 0:
        raise EmbeddingUnavailable(done.stderr.strip() or "vec rebuild failed")


def run_vec_read_script(path: Path, sql: str) -> str:
    """Bounded-result read query; stream generated ASCII SQL instead of argv."""
    cli, ext = _vec_cli(), _vec0_path()
    if cli is None or ext is None:
        raise EmbeddingUnavailable("sqlite-vec missing")
    with tempfile.TemporaryFile(mode="w+", encoding="ascii") as script:
        _ = script.write(sql)
        _ = script.seek(0)
        done = subprocess.run(
            [cli, "-readonly", "-batch", "-bail", "-separator", "\x1f", "-newline", "\x1e",
             str(path), f".load {ext}", ".read /dev/stdin"],
            stdin=script, capture_output=True, text=True, check=False,
        )
    if done.returncode != 0:
        raise EmbeddingUnavailable(done.stderr.strip() or "vec read failed")
    return done.stdout


def _env_identity() -> ModelIdentity:
    return ModelIdentity(
        os.environ.get("SB_EMBED_MODEL", DEFAULT_MODEL_ID),
        os.environ.get("SB_EMBED_REVISION", DEFAULT_REVISION),
        VECTOR_DIM,
    )


def resolve_encoder() -> Encoder:
    identity = _env_identity()
    hub = os.environ.get("HF_HOME")
    base = Path(hub) / "hub" if hub else Path.home() / ".cache" / "huggingface" / "hub"
    snap = (
        base / ("models--" + identity.model_id.replace("/", "--")) / "snapshots" / identity.revision
    )
    if not snap.is_dir():
        raise EmbeddingUnavailable("embedding model unavailable")
    return _RemoteEncoder(identity)


def warmup() -> ModelIdentity:
    identity = _env_identity()
    revision = _run_st(_WARMUP_SCRIPT, identity, "", timeout=600).strip() or identity.revision
    return ModelIdentity(identity.model_id, revision, VECTOR_DIM)


_SCHEMA = (
    "BEGIN;CREATE TABLE embedding_meta(embedding_model_id TEXT NOT NULL,"
    "revision TEXT NOT NULL,dim INTEGER NOT NULL,git_head TEXT NOT NULL);"
    "CREATE TABLE chunks(id INTEGER PRIMARY KEY,page_id TEXT NOT NULL,"
    "section TEXT NOT NULL,text TEXT NOT NULL,content_hash TEXT NOT NULL,"
    "deriv_key TEXT NOT NULL);CREATE VIRTUAL TABLE vec_chunks USING vec0("
    "embedding float[1024] distance_metric=cosine);\n"
)


def _text(value: str) -> str:
    # sqlite3's stdin parser normalizes CRLF, including inside string literals.
    # ASCII hex also prevents user content from becoming CLI dot commands.
    return "CAST(X'" + value.encode("utf-8").hex() + "' AS TEXT)"


def _head(root: Path) -> str:
    value = git_run(root, "rev-parse", "--verify", "HEAD^{commit}")
    if value is None:
        raise EmbeddingUnavailable("committed embedding source unavailable")
    return value.strip()


def _write_script(script: TextIO, chunks: tuple[tuple[str, str, str, str], ...],
                  vectors: tuple[tuple[float, ...], ...], identity: ModelIdentity,
                  head: str) -> None:
    if len(vectors) != len(chunks):
        raise EmbeddingUnavailable("embedding result count mismatch")
    _ = script.write(_SCHEMA + "INSERT INTO embedding_meta VALUES ("
                     + f"{_text(identity.model_id)},{_text(identity.revision)},"
                     + f"{identity.dim},{_text(head)});\n")
    for index, ((page, section, body, digest), vector) in enumerate(
        zip(chunks, vectors, strict=True), start=1,
    ):
        if (len(vector) != identity.dim or not all(math.isfinite(v) for v in vector)
            or not 1.1754943508222875e-38 <= sum(v * v for v in vector) <= 3.4028234663852886e38):
            raise EmbeddingUnavailable("invalid embedding vector")
        key = embedding_deriv_key(ChunkRef(page, section, digest), identity)
        _ = script.write(f"INSERT INTO chunks VALUES ({index},"
                         + ",".join(_text(v) for v in (page, section, body, digest, key))
                         + ");\nINSERT INTO vec_chunks(rowid,embedding) VALUES ("
                         + f"{index},{_text('[' + ','.join(format(v, '.9g') for v in vector) + ']')});\n")
    _ = script.write("COMMIT;\n")
    script.flush()


def rebuild(vault_root: Path, *, encoder: Encoder | None = None) -> int:
    root = Path(vault_root)
    enc = encoder if encoder is not None else resolve_encoder()
    if enc.identity.dim != VECTOR_DIM or not sqlite_vec_available():
        raise EmbeddingUnavailable("sqlite-vec 1024-d store unavailable")

    def build(staging: Path, lock_fd: int) -> int:
        head, identity = _head(root), enc.identity
        chunks = collect_chunks(root, revision=head)
        vectors = enc.encode(tuple(item[2] for item in chunks)) if chunks else ()
        if enc.identity != identity:
            raise EmbeddingUnavailable("embedding identity changed during rebuild")
        with tempfile.TemporaryFile(mode="w+", encoding="ascii", dir=staging.parent) as script:
            _write_script(script, chunks, vectors, identity, head)
            run_vec_script(staging, script, lock_fd=lock_fd)
        check = run_vec_sql(staging, ("PRAGMA quick_check;SELECT "
                            "(SELECT count(*) FROM chunks),"
                            "(SELECT count(*) FROM vec_chunks);"), read_only=True, lock_fd=lock_fd)
        if check != f"ok\x1e{len(chunks)}\x1f{len(chunks)}\x1e":
            raise EmbeddingUnavailable("vector database validation failed")
        if _head(root) != head:
            raise EmbeddingUnavailable("committed source changed during rebuild; retry")
        return len(chunks)

    return publish_vectors(root, build)


def read_identity(vault_root: Path) -> ModelIdentity | None:
    path = vectors_path(vault_root)
    if not path.is_file():
        return None
    raw = _sqlite(path, "SELECT embedding_model_id, revision, dim FROM embedding_meta LIMIT 1")
    if not path.is_file() or raw is None or raw.strip() == "":
        return None
    parts = raw.split("\x1e")[0].split("\x1f")
    try:
        return ModelIdentity(parts[0], parts[1], int(parts[2]))
    except (IndexError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _ = sys.stderr.write("usage: python -m sb.embeddings warmup|rebuild\n")
        return 2
    try:
        if args[0] == "warmup":
            identity = warmup()
            _ = sys.stdout.write(f"{identity.model_id} {identity.revision} dim={identity.dim}\n")
            return 0
        if args[0] == "rebuild":
            _ = sys.stdout.write(f"rebuilt {rebuild(resolve_vault_root())} vectors\n")
            return 0
    except EmbeddingUnavailable as exc:
        _ = sys.stderr.write(f"{exc}\n")
        return 1
    _ = sys.stderr.write(f"unknown command: {args[0]}\n")
    return 2


def collect_chunks(vault_root: Path, *, revision: str = "HEAD") -> tuple[tuple[str, str, str, str], ...]:
    found: list[tuple[str, str, str, str]] = []
    try:
        paths = committed_paths(vault_root, _PREFIXES, revision=revision, required=True)
    except ValueError as exc:
        raise EmbeddingUnavailable("committed embedding paths unavailable") from exc
    for rel in paths:
        text = committed_text(vault_root, rel, revision=revision)
        if text is None:
            raise EmbeddingUnavailable("committed embedding source unavailable")
        page_id = rel.removesuffix(".md")
        for section, body in _sections(text):
            found.append((page_id, section, body, hashlib.sha256(body.encode()).hexdigest()))
    return tuple(found)


def _sqlite(path: Path, sql: str) -> str | None:
    try:
        done = subprocess.run(
            ["sqlite3", "-readonly", "-separator", "\x1f", "-newline", "\x1e", str(path), sql],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return None if done.returncode != 0 else done.stdout


def _sections(text: str) -> tuple[tuple[str, str], ...]:
    body = text
    if text.startswith("---"):
        rest = text[3:].lstrip("\n")
        end = rest.find("\n---")
        if end >= 0:
            body = rest[end + 4 :].lstrip("\n")
    name = ""
    buf: list[str] = []
    parts: list[tuple[str, str]] = []
    for line in body.splitlines():
        if line.startswith("#"):
            chunk = "\n".join(buf).strip()
            if chunk:
                parts.append((name, chunk))
            name = line.lstrip("#").strip()
            buf = []
            continue
        buf.append(line)
    chunk = "\n".join(buf).strip()
    if chunk:
        parts.append((name, chunk))
    return tuple(parts)


def _vec0_path() -> Path | None:
    spec = importlib.util.find_spec("sqlite_vec")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent / "vec0"


_CLI_MEMO: list[str | None] = []


def _vec_cli() -> str | None:
    if _CLI_MEMO:
        return _CLI_MEMO[0]
    ext, found = _vec0_path(), None
    env = os.environ.get("SB_SQLITE")
    for cand in (
        env,
        "/opt/homebrew/opt/sqlite/bin/sqlite3",
        "/usr/local/opt/sqlite/bin/sqlite3",
        "sqlite3",
    ):
        if cand is None or ext is None:
            continue
        try:
            done = subprocess.run(
                [cand, ":memory:", f".load {ext}", "select vec_version();"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if done.returncode == 0 and done.stdout.strip() != "":
            found = cand
            break
    _CLI_MEMO.append(found)
    return found


def _run_st(script: str, identity: ModelIdentity, stdin_text: str, *, timeout: float = 60) -> str:
    try:
        done = subprocess.run(
            [sys.executable, "-c", script, identity.model_id, identity.revision],
            input=stdin_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise EmbeddingUnavailable("embedding subprocess timed out") from exc
    except OSError as exc:
        raise EmbeddingUnavailable("embedding subprocess unavailable") from exc
    if done.returncode != 0:
        raise EmbeddingUnavailable(done.stderr.strip() or "sentence-transformers failed")
    return done.stdout


if __name__ == "__main__":
    raise SystemExit(main())
