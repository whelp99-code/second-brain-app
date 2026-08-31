"""Copy-on-write sealed generations, read pins, activation, and disposal."""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, cast, final

from pydantic import TypeAdapter

from sb.effect_values import canonical_bytes, digest, format_instant, strict_loads
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
        for directory in (
            state_root,
            share_root,
            self.generations,
            self.staging,
            self.retired,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
        self.lock_path = state_root / "generation.lock"
        lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
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

    @contextmanager
    def exclusive(self) -> Generator[None, None, None]:
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @contextmanager
    def pin(
        self, lease_id: str | None = None, now: datetime | None = None
    ) -> Generator[ReaderPin, None, None]:
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        directory_fd: int | None = None
        generation: Generation | None = None
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
                "git", "-c", "user.name=Second Brain", "-c",
                "user.email=second-brain@local", "-c", "commit.gpgsign=false", *args,
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
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(source)
            if relative.parts[0] in {".git", ".sb"} or relative.name == "generation.json":
                continue
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
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
                    written = 0
                    while written < len(block):
                        count = os.write(target_fd, block[written:])
                        if count <= 0:
                            raise GenerationError("GENERATION_WRITE_FAILED")
                        written += count
                os.fsync(target_fd)
            finally:
                os.close(source_fd)
                if target_fd is not None:
                    os.close(target_fd)

    @staticmethod
    def _inventory(root: Path) -> tuple[list[dict[str, object]], int]:
        rows: list[dict[str, object]] = []
        byte_count = 0
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root)
            if relative.parts[0] == ".git" or relative.name == "generation.json":
                continue
            metadata = path.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise GenerationError("GENERATION_SURFACE_UNSAFE")
            raw = path.read_bytes()
            byte_count += len(raw)
            rows.append(
                {
                    "surface_id": hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest(),
                    "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
            )
        return rows, byte_count

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
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

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
    ) -> Generation:
        staging = self.staging / f"{request_id}.{os.getpid()}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            if parent is not None:
                self._copy_allowed(parent.root, staging, allowed)
            mutate(staging)
            for path in staging.rglob("*"):
                if path.is_symlink():
                    raise GenerationError("GENERATION_SURFACE_UNSAFE")
            _ = self._git(staging, "init", "-q", "--template=", "-b", "main")
            _ = self._git(staging, "add", "-A")
            _ = self._git(
                staging,
                "commit",
                "--allow-empty",
                "-qm",
                "sealed generation",
                timestamp=format_instant(created_at),
            )
            head = self._git(staging, "rev-parse", "HEAD")
            tree = self._git(staging, "rev-parse", "HEAD^{tree}")
            if self._git(staging, "rev-list", "--parents", "-n", "1", "HEAD").count(" ") != 0:
                raise GenerationError("GENERATION_HISTORY_INVALID")
            inventory, byte_count = self._inventory(staging)
            manifests = derived_manifests or {}
            content_manifest = digest("generation", {"files": inventory})
            body: dict[str, object] = {
                "schema_version": 1,
                "provider_instance_id": self.provider_instance_id,
                "provider_release_sha": self.provider_release_sha,
                "parent_generation_id": None if parent is None else parent.generation_id,
                "head": head,
                "tree": tree,
                "tombstone_sequence": tombstone_sequence,
                "tombstone_set_root": tombstone_set_root,
                "content_manifest_digest": content_manifest,
                "ledger_manifest_digest": manifests.get("ledger", digest("generation", {"ledger": []})),
                "lexical_manifest_digest": manifests.get("lexical", digest("generation", {"lexical": []})),
                "vector_manifest_digest": manifests.get("vector", digest("generation", {"vector": []})),
                "briefing_manifest_digest": manifests.get("briefing", digest("generation", {"briefing": []})),
                "file_count": len(inventory),
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
                content_manifest_digest=content_manifest,
                ledger_manifest_digest=str(body["ledger_manifest_digest"]),
                lexical_manifest_digest=str(body["lexical_manifest_digest"]),
                vector_manifest_digest=str(body["vector_manifest_digest"]),
                briefing_manifest_digest=str(body["briefing_manifest_digest"]),
                file_count=len(inventory),
                byte_count=byte_count,
                created_at=format_instant(created_at),
            )
            manifest_path = staging / "generation.json"
            _ = manifest_path.write_bytes(canonical_bytes(asdict(manifest)) + b"\n")
            manifest_path.chmod(0o600)
            self._fsync_tree(staging)
            final = self.generations / generation_id
            if final.exists():
                existing = self._read_manifest(final)
                if existing != manifest:
                    raise GenerationError("GENERATION_SPLIT_BRAIN")
                shutil.rmtree(staging)
                return Generation(existing, final)
            os.replace(staging, final)
            parent_fd = os.open(self.generations, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
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
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _read_manifest(root: Path) -> GenerationManifestV1:
        path = root / "generation.json"
        try:
            value = strict_loads(path.read_bytes(), 65_536)
            if not isinstance(value, dict):
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            return TypeAdapter(GenerationManifestV1).validate_python(value)
        except (OSError, TypeError, ValueError) as exc:
            raise GenerationError("GENERATION_SPLIT_BRAIN") from exc

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

    def activate(self, generation: Generation, expected_parent: Generation | None, now: datetime) -> None:
        with self.exclusive():
            current: Generation | None
            if self.active_link.is_symlink():
                current = self.active()
            else:
                current = None
            if (None if current is None else current.generation_id) != (
                None if expected_parent is None else expected_parent.generation_id
            ):
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            relative = Path("vault-generations") / generation.generation_id
            temporary = self.share_root / f".vault-{generation.generation_id}.tmp"
            temporary.unlink(missing_ok=True)
            os.symlink(relative, temporary)
            _ = self.journal.execute(
                "UPDATE activations SET phase='switch_intent',pointer_target=?,updated_at=? WHERE generation_id=? AND phase='sealed'",
                (str(relative), format_instant(now), generation.generation_id),
            )
            self.journal.commit()
            os.replace(temporary, self.active_link)
            parent_fd = os.open(self.share_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            observed = self.active()
            if observed.generation_id != generation.generation_id:
                raise GenerationError("GENERATION_SPLIT_BRAIN")
            _ = self.journal.execute(
                "UPDATE activations SET phase='activated',updated_at=? WHERE generation_id=? AND phase='switch_intent'",
                (format_instant(now), generation.generation_id),
            )
            if current is not None:
                self._dispose_predecessor(current, generation, now)
            else:
                _ = self.journal.execute(
                    "UPDATE activations SET phase='proved',reader_drain_digest=?,disposal_digest=?,updated_at=? WHERE generation_id=?",
                    (
                        digest("generation", {"readers": []}),
                        digest("generation", {"disposed": []}),
                        format_instant(now),
                        generation.generation_id,
                    ),
                )
            self.journal.commit()

    def _dispose_predecessor(
        self,
        predecessor: Generation,
        successor: Generation,
        now: datetime,
    ) -> None:
        readers = () if self.requests is None else self.requests.readers(predecessor.generation_id)
        if readers:
            raise GenerationError("GENERATION_READER_DRAIN_REQUIRED")
        drain_digest = digest("generation", {"generation_id": predecessor.generation_id, "readers": []})
        _ = self.journal.execute(
            "UPDATE activations SET phase='disposing',reader_drain_digest=?,updated_at=? WHERE generation_id=? AND phase='activated'",
            (drain_digest, format_instant(now), successor.generation_id),
        )
        retired = self.retired / predecessor.generation_id
        os.replace(predecessor.root, retired)
        parent_fd = os.open(self.generations, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        shutil.rmtree(retired)
        retired_fd = os.open(self.retired, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(retired_fd)
        finally:
            os.close(retired_fd)
        disposal_digest = digest(
            "generation",
            {"generation_id": predecessor.generation_id, "disposed": True},
        )
        _ = self.journal.execute(
            "UPDATE activations SET phase='proved',disposal_digest=?,updated_at=? WHERE generation_id=? AND phase='disposing'",
            (disposal_digest, format_instant(now), successor.generation_id),
        )

    def activation_digests(self, generation_id: str) -> tuple[str, str, str]:
        row = cast(
            tuple[object, object, object] | None,
            self.journal.execute(
                "SELECT manifest_digest,reader_drain_digest,disposal_digest FROM activations WHERE generation_id=? AND phase='proved'",
                (generation_id,),
            ).fetchone(),
        )
        if row is None or not all(isinstance(value, str) for value in row):
            raise GenerationError("GENERATION_NOT_PROVED")
        return cast(tuple[str, str, str], row)
