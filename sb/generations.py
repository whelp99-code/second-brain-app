"""Copy-on-write sealed generations, read pins, activation, and disposal.
# noqa: SIZE_OK -- one sealed-generation state machine and crash journal
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
from collections.abc import Callable, Generator, Iterable, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast, final

from pydantic import TypeAdapter

from sb.effect_values import (
    JsonInput,
    JsonValue,
    canonical_bytes,
    digest,
    format_instant,
    strict_loads,
)
from sb.generation_cleanup import discard_staging
from sb.generation_integrity import load_verified_manifest
from sb.generation_locks import GenerationWriteLease, generation_writer
from sb.generation_walk import surface_files
from sb.request_store import RequestStore


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GenerationManifestV1:
    schema_version: int
    generation_id: str
    generation_digest: str
    provider_instance_id: str
    provider_release_sha: str
    parent_generation_id: str | None
    head: str
    tree: str
    tombstone_sequence: int
    tombstone_set_root: str
    content_manifest_digest: str
    ledger_manifest_digest: str
    lexical_manifest_digest: str
    vector_manifest_digest: str
    briefing_manifest_digest: str
    file_count: int
    byte_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class Generation:
    manifest: GenerationManifestV1
    root: Path

    @property
    def generation_id(self) -> str:
        return self.manifest.generation_id

    @property
    def head(self) -> str:
        return self.manifest.head

    @property
    def tree(self) -> str:
        return self.manifest.tree


@dataclass(frozen=True, slots=True)
class ReaderPin:
    generation: Generation
    directory_fd: int
    lease_id: str | None


@dataclass(frozen=True, slots=True)
class DerivedStoreDigests:
    ledger: str
    lexical: str
    vector: str
    briefing: str


_JOURNAL_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS activations(
  generation_id TEXT PRIMARY KEY,
  parent_generation_id TEXT,
  phase TEXT NOT NULL CHECK(phase IN ('sealed','switch_intent','activated','disposing','proved')),
  manifest_digest TEXT NOT NULL,
  pointer_target TEXT,
  reader_drain_digest TEXT,
  disposal_digest TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS activation_identity_immutable
BEFORE UPDATE OF generation_id,parent_generation_id,manifest_digest,created_at ON activations
BEGIN SELECT RAISE(ABORT,'immutable activation identity'); END;
"""
_GENESIS_ROOT: Final = "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
type SqliteCell = None | int | float | str | bytes


def _no_barrier(_phase: str) -> None:
    return


def _directory_fsync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink < 2
    ):
        raise GenerationError("GENERATION_ROOT_UNSAFE")
    path.chmod(0o700)


def _regular_files(root: Path, *, include_derived: bool) -> tuple[tuple[Path, Path], ...]:
    files: list[tuple[Path, Path]] = []
    for path, relative in surface_files(root, include_derived=include_derived):
        metadata = path.stat(follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
        ):
            raise GenerationError("GENERATION_SURFACE_UNSAFE")
        files.append((path, relative))
    return tuple(files)


def _content_rows(root: Path) -> tuple[list[dict[str, JsonValue]], int]:
    rows: list[dict[str, JsonValue]] = []
    byte_count = 0
    for path, relative_path in _regular_files(root, include_derived=False):
        relative = relative_path.as_posix()
        raw = path.read_bytes()
        byte_count += len(raw)
        rows.append(
            {
                "surface_id": hashlib.sha256(relative.encode("utf-8")).hexdigest(),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        )
    return rows, byte_count


def _page_rows(root: Path) -> tuple[tuple[str, bytes], ...]:
    rows: list[tuple[str, bytes]] = []
    for prefix in ("wiki", "daily", "conflicts"):
        directory = root / prefix
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.md"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root)
            if relative.parts[:2] == ("wiki", "_proposed"):
                continue
            rows.append((relative.with_suffix("").as_posix(), path.read_bytes()))
    return tuple(rows)


def _sections(raw: bytes) -> tuple[tuple[str, str], ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenerationError("GENERATION_CONTENT_INVALID") from exc
    if text.startswith("---"):
        rest = text[3:].lstrip("\n")
        boundary = rest.find("\n---")
        if boundary >= 0:
            text = rest[boundary + 4 :].lstrip("\n")
    heading = ""
    lines: list[str] = []
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith("#"):
            body = "\n".join(lines).strip()
            if body:
                rows.append((heading, body))
            heading = line.lstrip("#").strip()
            lines = []
        else:
            lines.append(line)
    body = "\n".join(lines).strip()
    if body:
        rows.append((heading, body))
    return tuple(rows)


def _logical_derived_digests(
    pages: Sequence[tuple[str, bytes]],
    *,
    head: str,
    tree: str,
    tombstone_sequence: int,
    tombstone_set_root: str,
) -> DerivedStoreDigests:
    page_manifest = [
        {
            "page_id": page_id,
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        for page_id, raw in pages
    ]
    binding = {
        "head": head,
        "tree": tree,
        "tombstone_sequence": tombstone_sequence,
        "tombstone_set_root": tombstone_set_root,
        "pages": page_manifest,
    }
    lexical_rows = [
        {
            "page_id": page_id,
            "section": section,
            "digest": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        for page_id, raw in pages
        for section, body in _sections(raw)
    ]
    briefing_rows = [row for row in page_manifest if str(row["page_id"]).startswith("daily/")]
    return DerivedStoreDigests(
        ledger=digest("generation", {"ledger": binding}),
        lexical=digest("generation", {"binding": binding, "rows": lexical_rows}),
        vector=digest(
            "generation",
            {"binding": binding, "enabled": False, "model": None, "revision": None, "rows": 0},
        ),
        briefing=digest("generation", {"binding": binding, "briefs": briefing_rows}),
    )


def _connect_fresh(path: Path) -> sqlite3.Connection:
    if path.exists() or path.is_symlink():
        raise GenerationError("GENERATION_SURFACE_UNSAFE")
    connection = sqlite3.connect(path, isolation_level=None)
    _ = connection.execute("PRAGMA journal_mode=DELETE")
    _ = connection.execute("PRAGMA synchronous=FULL")
    _ = connection.execute("PRAGMA secure_delete=ON")
    return connection


def _close_fresh(connection: sqlite3.Connection, path: Path) -> None:
    try:
        _ = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        _ = connection.execute("VACUUM").fetchall()
    finally:
        connection.close()
    path.chmod(0o600)
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(f"{path}{suffix}").exists():
            raise GenerationError("GENERATION_SQLITE_RESIDUE")


@contextmanager
def _derived_transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    """Commit a derived table and its binding together, without per-row fsync."""
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise GenerationError("GENERATION_WRITE_FAILED")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _build_derived_stores(
    root: Path,
    manifest: GenerationManifestV1,
    pages: Sequence[tuple[str, bytes]],
) -> None:
    derived = root / ".sb"
    derived.mkdir(mode=0o700, exist_ok=True)
    derived.chmod(0o700)
    binding = (
        manifest.generation_id,
        manifest.provider_instance_id,
        manifest.head,
        manifest.tree,
        manifest.tombstone_sequence,
        manifest.tombstone_set_root,
    )

    ledger_path = derived / "ledger.db"
    if ledger_path.exists():
        source = sqlite3.connect(ledger_path, isolation_level=None)
        _ = source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        rebuilt_path = ledger_path.with_name("ledger.rebuilt.db")
        rebuilt = _connect_fresh(rebuilt_path)
        try:
            source.backup(rebuilt)
        finally:
            source.close()
        _ = rebuilt.execute("PRAGMA journal_mode=DELETE").fetchall()
        _close_fresh(rebuilt, rebuilt_path)
        ledger_path.unlink()
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{ledger_path}{suffix}").unlink(missing_ok=True)
        os.replace(rebuilt_path, ledger_path)
        ledger = sqlite3.connect(ledger_path, isolation_level=None)
        _ = ledger.execute("PRAGMA synchronous=FULL")
        _ = ledger.execute("PRAGMA secure_delete=ON")
        _ = ledger.executescript("DROP TABLE IF EXISTS generation_meta; DROP TABLE IF EXISTS records;")
    else:
        ledger = _connect_fresh(ledger_path)
    try:
        _ = ledger.executescript(
            """
            CREATE TABLE generation_meta(
              generation_id TEXT PRIMARY KEY,provider_instance_id TEXT NOT NULL,head TEXT NOT NULL,
              tree TEXT NOT NULL,tombstone_sequence INTEGER NOT NULL,tombstone_set_root TEXT NOT NULL,
              manifest_digest TEXT NOT NULL,row_count INTEGER NOT NULL
            );
            CREATE TABLE records(
              page_id TEXT PRIMARY KEY,content_digest TEXT NOT NULL,byte_count INTEGER NOT NULL
            );
            """
        )
        with _derived_transaction(ledger):
            _ = ledger.executemany(
                "INSERT INTO records VALUES(?,?,?)",
                [
                    (page_id, "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw))
                    for page_id, raw in pages
                ],
            )
            _ = ledger.execute(
                "INSERT INTO generation_meta VALUES(?,?,?,?,?,?,?,?)",
                (*binding, manifest.ledger_manifest_digest, len(pages)),
            )
    finally:
        _close_fresh(ledger, ledger_path)

    search_path = derived / "search.db"
    search = _connect_fresh(search_path)
    lexical_rows = [
        (page_id, section, body)
        for page_id, raw in pages
        for section, body in _sections(raw)
    ]
    try:
        _ = search.executescript(
            """
            CREATE TABLE generation_meta(
              generation_id TEXT PRIMARY KEY,provider_instance_id TEXT NOT NULL,head TEXT NOT NULL,
              tree TEXT NOT NULL,tombstone_sequence INTEGER NOT NULL,tombstone_set_root TEXT NOT NULL,
              manifest_digest TEXT NOT NULL,row_count INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE docs USING fts5(page_id,section,text,tokenize='trigram');
            """
        )
        with _derived_transaction(search):
            _ = search.executemany("INSERT INTO docs(page_id,section,text) VALUES(?,?,?)", lexical_rows)
            _ = search.execute(
                "INSERT INTO generation_meta VALUES(?,?,?,?,?,?,?,?)",
                (*binding, manifest.lexical_manifest_digest, len(lexical_rows)),
            )
    finally:
        _close_fresh(search, search_path)

    vector_path = derived / "vectors.db"
    vectors = _connect_fresh(vector_path)
    try:
        _ = vectors.executescript(
            """
            CREATE TABLE generation_meta(
              generation_id TEXT PRIMARY KEY,provider_instance_id TEXT NOT NULL,head TEXT NOT NULL,
              tree TEXT NOT NULL,tombstone_sequence INTEGER NOT NULL,tombstone_set_root TEXT NOT NULL,
              manifest_digest TEXT NOT NULL,row_count INTEGER NOT NULL,enabled INTEGER NOT NULL CHECK(enabled=0),
              model_id TEXT,revision TEXT
            );
            CREATE TABLE chunks(
              id INTEGER PRIMARY KEY,page_id TEXT NOT NULL,section TEXT NOT NULL,
              content_hash TEXT NOT NULL,deriv_key TEXT NOT NULL
            );
            """
        )
        _ = vectors.execute(
            "INSERT INTO generation_meta VALUES(?,?,?,?,?,?,?,?,0,NULL,NULL)",
            (*binding, manifest.vector_manifest_digest, 0),
        )
    finally:
        _close_fresh(vectors, vector_path)

    briefing = {
        "schema_version": 1,
        "generation_id": manifest.generation_id,
        "head": manifest.head,
        "tree": manifest.tree,
        "tombstone_sequence": manifest.tombstone_sequence,
        "tombstone_set_root": manifest.tombstone_set_root,
        "manifest_digest": manifest.briefing_manifest_digest,
        "brief_count": sum(page_id.startswith("daily/") for page_id, _raw in pages),
    }
    _write_private(derived / "briefing-manifest.json", canonical_bytes(briefing) + b"\n")
    store_rows: list[dict[str, JsonValue]] = []
    for name in ("ledger.db", "search.db", "vectors.db", "briefing-manifest.json"):
        raw = (derived / name).read_bytes()
        store_rows.append(
            {"name": name, "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        )
    derived_manifest: dict[str, JsonInput] = {
        "schema_version": 1,
        "generation_id": manifest.generation_id,
        "head": manifest.head,
        "tree": manifest.tree,
        "tombstone_sequence": manifest.tombstone_sequence,
        "tombstone_set_root": manifest.tombstone_set_root,
        "logical_manifests": {
            "ledger": manifest.ledger_manifest_digest,
            "lexical": manifest.lexical_manifest_digest,
            "vector": manifest.vector_manifest_digest,
            "briefing": manifest.briefing_manifest_digest,
        },
        "stores": store_rows,
    }
    _write_private(derived / "derived-manifest.json", canonical_bytes(derived_manifest) + b"\n")


def _same_generation_binding(connection: sqlite3.Connection, manifest: GenerationManifestV1) -> bool:
    row = cast(
        tuple[SqliteCell, ...] | None,
        connection.execute(
            "SELECT generation_id,provider_instance_id,head,tree,tombstone_sequence,tombstone_set_root "
            + "FROM generation_meta LIMIT 1"
        ).fetchone(),
    )
    return row == (
        manifest.generation_id,
        manifest.provider_instance_id,
        manifest.head,
        manifest.tree,
        manifest.tombstone_sequence,
        manifest.tombstone_set_root,
    )


def _validate_derived_stores(root: Path, manifest: GenerationManifestV1) -> None:
    derived = root / ".sb"
    for name in ("ledger.db", "search.db", "vectors.db"):
        path = derived / name
        try:
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            valid = _same_generation_binding(connection, manifest)
            connection.close()
        except sqlite3.Error as exc:
            raise GenerationError("GENERATION_SPLIT_BRAIN") from exc
        if not valid:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
    try:
        raw = strict_loads((derived / "derived-manifest.json").read_bytes(), 65_536)
    except (OSError, ValueError) as exc:
        raise GenerationError("GENERATION_SPLIT_BRAIN") from exc
    if not isinstance(raw, dict) or raw.get("generation_id") != manifest.generation_id:
        raise GenerationError("GENERATION_SPLIT_BRAIN")


def _make_writable(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts)):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o700)
        elif path.is_file() and not path.is_symlink():
            path.chmod(0o600)
    root.chmod(0o700)


def _seal_modes(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_file() and not path.is_symlink():
            path.chmod(0o400)
        elif path.is_dir() and not path.is_symlink():
            path.chmod(0o500)
    root.chmod(0o500)


def _proc_descriptors(root: Path) -> tuple[tuple[int, int], ...]:
    resolved = root.resolve()
    found: list[tuple[int, int]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        raise GenerationError("GENERATION_READER_DRAIN_UNVERIFIABLE")
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
        except OSError:
            continue
        descriptors = process / "fd"
        try:
            entries = tuple(descriptors.iterdir())
        except OSError:
            continue
        for descriptor in entries:
            try:
                target = Path(os.readlink(descriptor).removesuffix(" (deleted)"))
                if target.is_absolute() and target.resolve().is_relative_to(resolved):
                    found.append((int(process.name), int(descriptor.name)))
            except (OSError, ValueError):
                continue
    return tuple(sorted(found))


@final
class GenerationStore:
    def __init__(
        self,
        state_root: Path,
        share_root: Path,
        *,
        provider_instance_id: str,
        provider_release_sha: str,
        requests: RequestStore | None = None,
    ) -> None:
        self.state_root = state_root
        self.share_root = share_root
        self.provider_instance_id = provider_instance_id
        self.provider_release_sha = provider_release_sha
        self.requests = requests
        self.generations = share_root / "vault-generations"
        self.staging = self.generations / ".staging"
        self.retired = self.generations / ".retired"
        self.active_link = share_root / "vault"
        for directory in (state_root, share_root, self.generations, self.staging, self.retired):
            _private_directory(directory)
        if self.generations.stat().st_dev != self.share_root.stat().st_dev:
            raise GenerationError("GENERATION_EXDEV")
        self.lock_path = state_root / "generation.lock"
        lock_fd = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.close(lock_fd)
        self.lock_path.chmod(0o600)
        self.journal_path = state_root / "generation-journal.db"
        self.journal = sqlite3.connect(self.journal_path, isolation_level=None, timeout=30)
        _ = self.journal.execute("PRAGMA journal_mode=DELETE")
        _ = self.journal.execute("PRAGMA synchronous=FULL")
        _ = self.journal.executescript(_JOURNAL_SCHEMA)
        self.journal_path.chmod(0o600)

    def close(self) -> None:
        self.journal.close()

    def discard_abandoned_staging(self) -> tuple[str, ...]:
        """Dispose only unpublished staging while the caller owns writer/exclusive locks."""
        def require_unused(root: Path) -> None:
            if _proc_descriptors(root):
                raise GenerationError("GENERATION_STAGING_IN_USE")

        return discard_staging(self.staging, require_unused)

    @contextmanager
    def writer(self) -> Generator[GenerationWriteLease, None, None]:
        with generation_writer(self.lock_path) as lease:
            yield lease

    @contextmanager
    def exclusive(self) -> Generator[None, None, None]:
        with self.writer():
            yield

    @contextmanager
    def try_exclusive(self) -> Generator[None, None, None]:
        with generation_writer(self.lock_path, blocking=False):
            yield

    @contextmanager
    def pin(
        self,
        lease_id: str | None = None,
        now: datetime | None = None,
    ) -> Generator[ReaderPin, None, None]:
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        directory_fd: int | None = None
        registered = False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            generation = self.active()
            directory_fd = os.open(
                generation.root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            if lease_id is not None:
                if self.requests is None or now is None:
                    raise GenerationError("READER_LEASE_INVALID")
                self.requests.register_reader(lease_id, generation.generation_id, os.getpid(), now)
                registered = True
            yield ReaderPin(generation, directory_fd, lease_id)
        finally:
            if registered and lease_id is not None and self.requests is not None:
                self.requests.release_reader(lease_id)
            if directory_fd is not None:
                os.close(directory_fd)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @staticmethod
    def _git(root: Path, *args: str, timestamp: str | None = None) -> str:
        env = os.environ.copy()
        env.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "Second Brain",
                "GIT_AUTHOR_EMAIL": "second-brain@local",
                "GIT_COMMITTER_NAME": "Second Brain",
                "GIT_COMMITTER_EMAIL": "second-brain@local",
            }
        )
        if timestamp is not None:
            env["GIT_AUTHOR_DATE"] = timestamp
            env["GIT_COMMITTER_DATE"] = timestamp
        completed = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Second Brain",
                "-c",
                "user.email=second-brain@local",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if completed.returncode != 0:
            raise GenerationError("GENERATION_GIT_FAILED")
        return completed.stdout.strip()

    @staticmethod
    def _copy_allowed(
        source: Path,
        destination: Path,
        allowed: Callable[[Path], bool],
    ) -> None:
        source_device = source.stat().st_dev
        for path, relative in surface_files(source):
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid()
            ):
                raise GenerationError("GENERATION_SOURCE_UNSAFE")
            if metadata.st_dev != source_device or not allowed(relative):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            target_fd: int | None = None
            try:
                observed = os.fstat(source_fd)
                if observed.st_ino != metadata.st_ino or observed.st_dev != metadata.st_dev:
                    raise GenerationError("GENERATION_SOURCE_UNSAFE")
                target_fd = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                )
                while True:
                    block = os.read(source_fd, 65_536)
                    if not block:
                        break
                    offset = 0
                    while offset < len(block):
                        count = os.write(target_fd, block[offset:])
                        if count <= 0:
                            raise GenerationError("GENERATION_WRITE_FAILED")
                        offset += count
                # The complete staged tree is fsynced after all mutations and
                # derived stores, before any sealed manifest is published.
            finally:
                os.close(source_fd)
                if target_fd is not None:
                    os.close(target_fd)

    @staticmethod
    def _fsync_tree(root: Path) -> None:
        directories: list[Path] = []
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_file():
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            elif path.is_dir():
                directories.append(path)
        directories.append(root)
        for directory in directories:
            _directory_fsync(directory)

    def build(
        self,
        *,
        request_id: str,
        parent: Generation | None,
        tombstone_sequence: int,
        tombstone_set_root: str,
        created_at: datetime,
        allowed: Callable[[Path], bool],
        mutate: Callable[[Path], None],
        derived_manifests: dict[str, str] | None = None,
        barrier: Callable[[str], None] | None = None,
    ) -> Generation:
        emit: Callable[[str], None] = barrier or _no_barrier
        request_key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        staging = self.staging / request_key
        if staging.exists():
            _make_writable(staging)
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        emit("successor_creation")
        try:
            if parent is not None:
                self._copy_allowed(parent.root, staging, allowed)
            mutate(staging)
            emit("sanitized_copy")
            for path in staging.rglob("*"):
                if path.is_symlink():
                    raise GenerationError("GENERATION_SURFACE_UNSAFE")
            ignore = staging / ".gitignore"
            existing_ignore = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
            required_rules = ("raw/", ".sb/", "generation.json")
            rules = [line for line in existing_ignore.splitlines() if line and line not in required_rules]
            # Required private surfaces must win over inherited negation rules.
            rules.extend(required_rules)
            _ = ignore.write_text("\n".join(rules) + "\n", encoding="utf-8")
            ignore.chmod(0o600)
            _ = self._git(staging, "init", "-q", "--template=", "-b", "main")
            _ = self._git(staging, "add", "-A")
            _ = self._git(
                staging,
                "commit",
                "--allow-empty",
                "-qm",
                "sealed generation",
                timestamp="2000-01-01T00:00:00+00:00",
            )
            head = self._git(staging, "rev-parse", "HEAD")
            tree = self._git(staging, "rev-parse", "HEAD^{tree}")
            if self._git(staging, "rev-list", "--parents", "-n", "1", "HEAD").count(" ") != 0:
                raise GenerationError("GENERATION_HISTORY_INVALID")
            emit("git_seal")
            content_rows, byte_count = _content_rows(staging)
            pages = _page_rows(staging)
            logical = _logical_derived_digests(
                pages,
                head=head,
                tree=tree,
                tombstone_sequence=tombstone_sequence,
                tombstone_set_root=tombstone_set_root,
            )
            overrides = derived_manifests or {}
            body: dict[str, JsonValue] = {
                "schema_version": 1,
                "provider_instance_id": self.provider_instance_id,
                "provider_release_sha": self.provider_release_sha,
                "parent_generation_id": None if parent is None else parent.generation_id,
                "head": head,
                "tree": tree,
                "tombstone_sequence": tombstone_sequence,
                "tombstone_set_root": tombstone_set_root,
                "content_manifest_digest": digest("generation", {"files": content_rows}),
                "ledger_manifest_digest": overrides.get("ledger", logical.ledger),
                "lexical_manifest_digest": overrides.get("lexical", logical.lexical),
                "vector_manifest_digest": overrides.get("vector", logical.vector),
                "briefing_manifest_digest": overrides.get("briefing", logical.briefing),
                "file_count": len(content_rows),
                "byte_count": byte_count,
                "created_at": format_instant(created_at),
            }
            generation_digest = digest("generation", body)
            generation_id = "sbgen:v1:" + generation_digest[7:]
            manifest = GenerationManifestV1(
                schema_version=1,
                generation_id=generation_id,
                generation_digest=generation_digest,
                provider_instance_id=self.provider_instance_id,
                provider_release_sha=self.provider_release_sha,
                parent_generation_id=None if parent is None else parent.generation_id,
                head=head,
                tree=tree,
                tombstone_sequence=tombstone_sequence,
                tombstone_set_root=tombstone_set_root,
                content_manifest_digest=str(body["content_manifest_digest"]),
                ledger_manifest_digest=str(body["ledger_manifest_digest"]),
                lexical_manifest_digest=str(body["lexical_manifest_digest"]),
                vector_manifest_digest=str(body["vector_manifest_digest"]),
                briefing_manifest_digest=str(body["briefing_manifest_digest"]),
                file_count=len(content_rows),
                byte_count=byte_count,
                created_at=format_instant(created_at),
            )
            _build_derived_stores(staging, manifest, pages)
            emit("ledger_build")
            emit("lexical_build")
            emit("vector_build")
            emit("brief_build")
            manifest_path = staging / "generation.json"
            _write_private(manifest_path, canonical_bytes(asdict(manifest)) + b"\n")
            self._fsync_tree(staging)
            emit("sealed_manifest")
            final = self.generations / generation_id
            if final.exists():
                existing = self._read_manifest(final)
                if existing != manifest:
                    raise GenerationError("GENERATION_SPLIT_BRAIN")
                _make_writable(staging)
                shutil.rmtree(staging)
                return Generation(existing, final)
            os.replace(staging, final)
            _directory_fsync(self.generations)
            _seal_modes(final)
            _ = self.journal.execute(
                "INSERT INTO activations VALUES(?,?, 'sealed', ?,NULL,NULL,NULL,?,?)",
                (
                    generation_id,
                    None if parent is None else parent.generation_id,
                    generation_digest,
                    format_instant(created_at),
                    format_instant(created_at),
                ),
            )
            return Generation(manifest, final)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            if staging.exists():
                _make_writable(staging)
                shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _read_manifest(root: Path) -> GenerationManifestV1:
        try:
            value = load_verified_manifest(root)
            manifest = TypeAdapter(GenerationManifestV1).validate_python(value)
            _validate_derived_stores(root, manifest)
            return manifest
        except (OSError, TypeError, ValueError) as exc:
            raise GenerationError("GENERATION_SPLIT_BRAIN") from exc

    def generation(self, generation_id: str) -> Generation:
        if not generation_id.startswith("sbgen:v1:") or "/" in generation_id:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        root = self.generations / generation_id
        if not root.is_dir() or root.is_symlink():
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        manifest = self._read_manifest(root)
        if manifest.generation_id != generation_id:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        return Generation(manifest, root)

    def active(self) -> Generation:
        if not self.active_link.is_symlink():
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        target = os.readlink(self.active_link)
        if Path(target).is_absolute() or len(Path(target).parts) != 2:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        root = (self.share_root / target).resolve()
        if not root.is_relative_to(self.generations.resolve()) or not root.is_dir():
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        manifest = self._read_manifest(root)
        if root.name != manifest.generation_id:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        head = self._git(root, "rev-parse", "HEAD")
        tree = self._git(root, "rev-parse", "HEAD^{tree}")
        if head != manifest.head or tree != manifest.tree:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        return Generation(manifest, root)

    def _phase(self, generation_id: str) -> str:
        row = cast(
            tuple[str] | None,
            self.journal.execute(
                "SELECT phase FROM activations WHERE generation_id=?", (generation_id,)
            ).fetchone(),
        )
        if row is None:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        return row[0]

    def activate(
        self,
        generation: Generation,
        expected_parent: Generation | None,
        now: datetime,
        *,
        barrier: Callable[[str], None] | None = None,
        lock_held: bool = False,
    ) -> None:
        emit: Callable[[str], None] = barrier or _no_barrier
        manager = nullcontext() if lock_held else self.exclusive()
        with manager:
            phase = self._phase(generation.generation_id)
            current = self.active() if self.active_link.is_symlink() else None
            if current is not None and current.generation_id == generation.generation_id:
                if phase == "switch_intent":
                    changed = self.journal.execute(
                        "UPDATE activations SET phase='activated',updated_at=? "
                        + "WHERE generation_id=? AND phase='switch_intent'",
                        (format_instant(now), generation.generation_id),
                    ).rowcount
                    if changed != 1:
                        raise GenerationError("GENERATION_SPLIT_BRAIN")
                    self.journal.commit()
                    phase = "activated"
                    emit("activation_verify")
                if phase not in {"activated", "disposing", "proved"}:
                    raise GenerationError("GENERATION_SPLIT_BRAIN")
                if phase != "proved":
                    self._complete_disposal(generation, expected_parent, now, emit)
                return
            if phase == "switch_intent":
                if (None if current is None else current.generation_id) != (
                    None if expected_parent is None else expected_parent.generation_id
                ):
                    raise GenerationError("GENERATION_SPLIT_BRAIN")
                relative = Path("vault-generations") / generation.generation_id
                temporary = self.share_root / f".vault-{generation.generation_id}.tmp"
                temporary.unlink(missing_ok=True)
                os.symlink(relative, temporary)
                os.replace(temporary, self.active_link)
                emit("pointer_rename")
                _directory_fsync(self.share_root)
                emit("pointer_parent_fsync")
                changed = self.journal.execute(
                    "UPDATE activations SET phase='activated',updated_at=? "
                    + "WHERE generation_id=? AND phase='switch_intent'",
                    (format_instant(now), generation.generation_id),
                ).rowcount
                if changed != 1:
                    raise GenerationError("GENERATION_SPLIT_BRAIN")
                self.journal.commit()
                emit("activation_verify")
                self._complete_disposal(generation, current, now, emit)
                return
            if phase != "sealed":
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            if (None if current is None else current.generation_id) != (
                None if expected_parent is None else expected_parent.generation_id
            ):
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            relative = Path("vault-generations") / generation.generation_id
            temporary = self.share_root / f".vault-{generation.generation_id}.tmp"
            temporary.unlink(missing_ok=True)
            os.symlink(relative, temporary)
            changed = self.journal.execute(
                "UPDATE activations SET phase='switch_intent',pointer_target=?,updated_at=? "
                + "WHERE generation_id=? AND phase='sealed'",
                (str(relative), format_instant(now), generation.generation_id),
            ).rowcount
            if changed != 1:
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            self.journal.commit()
            emit("switch_intent_fsync")
            os.replace(temporary, self.active_link)
            emit("pointer_rename")
            _directory_fsync(self.share_root)
            emit("pointer_parent_fsync")
            observed = self.active()
            if observed.generation_id != generation.generation_id:
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            changed = self.journal.execute(
                "UPDATE activations SET phase='activated',updated_at=? "
                + "WHERE generation_id=? AND phase='switch_intent'",
                (format_instant(now), generation.generation_id),
            ).rowcount
            if changed != 1:
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            self.journal.commit()
            emit("activation_verify")
            self._complete_disposal(generation, current, now, emit)

    def _complete_disposal(
        self,
        successor: Generation,
        predecessor: Generation | None,
        now: datetime,
        emit: Callable[[str], None],
    ) -> None:
        phase = self._phase(successor.generation_id)
        if predecessor is None and successor.manifest.parent_generation_id is not None:
            candidate = self.generations / successor.manifest.parent_generation_id
            if candidate.is_dir():
                predecessor = Generation(self._read_manifest(candidate), candidate)
        if predecessor is None:
            drain_digest = digest("generation", {"generation_id": None, "readers": [], "fds": []})
            disposal_digest = digest("generation", {"generation_id": None, "disposed": True})
            _ = self.journal.execute(
                "UPDATE activations SET phase='proved',reader_drain_digest=?,disposal_digest=?,updated_at=? "
                + "WHERE generation_id=? AND phase IN ('activated','disposing')",
                (drain_digest, disposal_digest, format_instant(now), successor.generation_id),
            )
            self.journal.commit()
            return
        if self.requests is not None:
            _ = self.requests.prune_dead_readers(predecessor.generation_id)
        readers = () if self.requests is None else self.requests.readers(predecessor.generation_id)
        descriptors = _proc_descriptors(predecessor.root)
        if readers or descriptors:
            raise GenerationError("GENERATION_READER_DRAIN_REQUIRED")
        drain_digest = digest(
            "generation",
            {"generation_id": predecessor.generation_id, "readers": [], "fds": []},
        )
        if phase == "activated":
            changed = self.journal.execute(
                "UPDATE activations SET phase='disposing',reader_drain_digest=?,updated_at=? "
                + "WHERE generation_id=? AND phase='activated'",
                (drain_digest, format_instant(now), successor.generation_id),
            ).rowcount
            if changed != 1:
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            self.journal.commit()
            emit("reader_drain")
        retired = self.retired / predecessor.generation_id
        if predecessor.root.exists():
            _make_writable(predecessor.root)
            if retired.exists():
                _make_writable(retired)
                shutil.rmtree(retired)
            os.replace(predecessor.root, retired)
            _directory_fsync(self.generations)
        if retired.exists():
            _make_writable(retired)
            shutil.rmtree(retired)
            _directory_fsync(self.retired)
        emit("predecessor_disposal")
        disposal_digest = digest(
            "generation",
            {"generation_id": predecessor.generation_id, "disposed": True},
        )
        changed = self.journal.execute(
            "UPDATE activations SET phase='proved',reader_drain_digest=COALESCE(reader_drain_digest,?),"
            + "disposal_digest=?,updated_at=? WHERE generation_id=? AND phase='disposing'",
            (drain_digest, disposal_digest, format_instant(now), successor.generation_id),
        ).rowcount
        if changed != 1:
            raise GenerationError("GENERATION_SPLIT_BRAIN")
        self.journal.commit()

    def activation_digests(self, generation_id: str) -> tuple[str, str, str]:
        row = cast(
            tuple[SqliteCell, SqliteCell, SqliteCell] | None,
            self.journal.execute(
                "SELECT manifest_digest,reader_drain_digest,disposal_digest FROM activations "
                + "WHERE generation_id=? AND phase='proved'",
                (generation_id,),
            ).fetchone(),
        )
        if row is None or not all(isinstance(value, str) for value in row):
            raise GenerationError("GENERATION_NOT_PROVED")
        return cast(tuple[str, str, str], row)

    def predecessor_descriptor_count(self, generation: Generation) -> int:
        return len(_proc_descriptors(generation.root))


def scan_open_generation_descriptors(roots: Iterable[Path]) -> int:
    return sum(len(_proc_descriptors(root)) for root in roots if root.exists())
