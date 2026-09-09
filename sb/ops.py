"""Operational status, diagnostics, retry, backup, and restore helpers."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tarfile
from collections.abc import Generator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Final, cast, override

from sb.config import Config
from sb.pipeline import audit_citations
from sb.redaction import redact_credentials
from sb.store import DerivStatus, assert_ledger_integrity, load_ledger_tables
from sb.store.ledger import CURRENT_SCHEMA_VERSION, Ledger, ledger_schema_version, migrate_ledger

BACKUP_FORMAT: Final = "second-brain-backup-v1"
_MAX_BACKUP_FILES: Final = 100_000
_MAX_BACKUP_BYTES: Final = 10 * 1024 * 1024 * 1024
_BACKUP_EXCLUDES: Final = frozenset(
    {
        ".sb/run.lock",
        ".sb/search.db",
        ".sb/search.db-shm",
        ".sb/search.db-wal",
        ".sb/ledger.db-shm",
        ".sb/ledger.db-wal",
    }
)
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
_SENSITIVE_DETAIL: Final = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]+|"
    + r"(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret)"
    + r"\s*[:=]\s*[^\s,;]+)"
)


@dataclass(slots=True)
class OperationError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class BackupResult:
    archive: Path
    checksum: str
    files: int
    bytes: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    destination: Path
    files: int
    bytes: int
    previous: Path | None


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _git_value(root: Path, *args: str) -> str | None:
    completed = _git(root, *args)
    return completed.stdout.strip() if completed.returncode == 0 else None


@contextmanager
def _exclusive_vault(root: Path) -> Generator[None, None, None]:
    lock = root / ".sb" / "run.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationError("vault is busy; backup or restore refused") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _checkpoint_ledger(root: Path) -> None:
    path = root / ".sb" / "ledger.db"
    if not path.is_file():
        return
    assert_ledger_integrity(path)
    try:
        with closing(sqlite3.connect(str(path), timeout=10.0)) as conn:
            _ = cast(
                tuple[object, ...] | None,
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(),
            )
    except sqlite3.DatabaseError as exc:
        raise OperationError(f"ledger checkpoint failed: {exc}") from exc


def _backup_files(root: Path, output: Path) -> list[Path]:
    found: list[Path] = []
    output_resolved = output.resolve(strict=False)
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if (relative in _BACKUP_EXCLUDES and not (relative == ".sb/search.db" and (root / "generation.json").is_file())) or path.resolve(strict=False) == output_resolved:
            continue
        if relative.endswith((".tmp", ".swp")):
            continue
        found.append(path)
    return found


def _package_version() -> str:
    try:
        return metadata.version("second-brain")
    except metadata.PackageNotFoundError:
        return "1.0.0"


def _safe_detail(value: str | None, *, limit: int = 240) -> str:
    if not value:
        return ""
    redacted = redact_credentials(_SENSITIVE_DETAIL.sub("[REDACTED]", value))
    return redacted if len(redacted) <= limit else redacted[: limit - 1] + "…"


def create_backup(
    vault_root: Path | str, output: Path | str, *, origin: str | None = None,
) -> BackupResult:
    """Create an atomic, checksummed full-vault backup while no run is active."""
    root = Path(vault_root).resolve(strict=False)
    archive = Path(output).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise OperationError(f"vault does not exist: {root}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_vault(root):
        _checkpoint_ledger(root)
        files = _backup_files(root, archive)
        entries: list[dict[str, str | int]] = []
        total = 0
        for path in files:
            size = path.stat().st_size
            total += size
            if len(entries) >= _MAX_BACKUP_FILES or total > _MAX_BACKUP_BYTES:
                raise OperationError("backup exceeds the resource budget")
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha256(path),
                    "size": size,
                    "mode": stat.S_IMODE(path.stat().st_mode) & 0o700,
                }
            )
        manifest = {
            "format": BACKUP_FORMAT,
            "origin": f"vault:{root}" if origin is None else origin,
            "created_at": datetime.now(UTC).isoformat(),
            "app_version": _package_version(),
            "schema_version": ledger_schema_version(root / ".sb" / "ledger.db"),
            "git_head": _git_value(root, "rev-parse", "HEAD") or "",
            "files": entries,
        }
        with NamedTemporaryFile(
            dir=archive.parent, prefix=f".{archive.name}.", delete=False
        ) as raw:
            temporary = Path(raw.name)
        try:
            with tarfile.open(temporary, mode="w:gz", format=tarfile.PAX_FORMAT) as bundle:
                payload = json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                info.mode = 0o600
                info.mtime = 0
                from io import BytesIO

                bundle.addfile(info, BytesIO(payload))
                for path in files:
                    relative = path.relative_to(root).as_posix()
                    bundle.add(path, arcname=f"vault/{relative}", recursive=False)
            os.replace(temporary, archive)
        finally:
            if temporary.exists():
                temporary.unlink()
    checksum = _sha256(archive)
    sidecar = archive.with_name(f"{archive.name}.sha256")
    _ = sidecar.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    _ = sidecar.chmod(0o600)
    return BackupResult(archive, checksum, len(entries), total)


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise OperationError(f"unsafe backup path: {value}")
    return Path(*pure.parts)


def read_backup_manifest(bundle: tarfile.TarFile) -> dict[str, JsonValue]:
    try:
        member = bundle.getmember("manifest.json")
    except KeyError as exc:
        raise OperationError("backup manifest is missing") from exc
    source = bundle.extractfile(member)
    if source is None:
        raise OperationError("backup manifest is unreadable")
    try:
        parsed = cast(JsonValue, json.loads(source.read().decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationError("backup manifest is invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("format") != BACKUP_FORMAT:
        raise OperationError("unsupported backup format")
    return parsed


def _manifest_entries(manifest: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    value = manifest.get("files")
    if not isinstance(value, list):
        raise OperationError("backup manifest files are invalid")
    entries: list[dict[str, JsonValue]] = []
    for item in value:
        if not isinstance(item, dict):
            raise OperationError("backup manifest entry is invalid")
        entries.append(item)
    return entries


def _verify_sidecar(archive: Path) -> None:
    sidecar = archive.with_name(f"{archive.name}.sha256")
    if not sidecar.is_file():
        return
    expected = sidecar.read_text(encoding="utf-8").split(maxsplit=1)[0]
    if len(expected) != 64 or _sha256(archive) != expected:
        raise OperationError("backup checksum mismatch")


@contextmanager
def _exclusive_restore(destination: Path) -> Generator[None, None, None]:
    """Keep the lock outside the directory that publication replaces."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(os.fsencode(destination.name)).hexdigest()
    lock = destination.parent / f".sb-restore-{name}.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
            raise OperationError("RESTORE_LOCK_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationError("RESTORE_DESTINATION_BUSY") from exc
        yield
    finally:
        os.close(fd)
    # Never unlink a lock file: another process may already have opened it.


def restore_backup(
    archive_path: Path | str,
    destination: Path | str,
    *,
    force: bool = False,
) -> RestoreResult:
    """Validate every byte and atomically restore a backup into a destination."""
    archive = Path(archive_path).expanduser().resolve(strict=False)
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if not archive.is_file():
        raise OperationError(f"backup does not exist: {archive}")
    _verify_sidecar(archive)
    with _exclusive_restore(destination_path):
        return _restore_backup_locked(archive, destination_path, force=force)


def _restore_backup_locked(archive: Path, destination_path: Path, *, force: bool) -> RestoreResult:
    parent = destination_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(mkdtemp(prefix=f".{destination_path.name}.restore-", dir=parent))
    files = 0
    total = 0
    try:
        with tarfile.open(archive, mode="r:*") as bundle:
            manifest = read_backup_manifest(bundle)
            entries = _manifest_entries(manifest)
            if len(entries) > _MAX_BACKUP_FILES:
                raise OperationError("backup file count exceeds the resource budget")
            seen: set[str] = set()
            for entry in entries:
                raw_path = entry.get("path")
                raw_hash = entry.get("sha256")
                raw_size = entry.get("size")
                raw_mode = entry.get("mode", 0o600)
                if not isinstance(raw_path, str) or not isinstance(raw_hash, str):
                    raise OperationError("backup manifest entry fields are invalid")
                if not isinstance(raw_size, int) or not isinstance(raw_mode, int):
                    raise OperationError("backup manifest entry metadata is invalid")
                relative = _safe_relative(raw_path)
                if raw_path in seen:
                    raise OperationError(f"duplicate backup path: {raw_path}")
                seen.add(raw_path)
                try:
                    member = bundle.getmember(f"vault/{raw_path}")
                except KeyError as exc:
                    raise OperationError(f"backup member is missing: {raw_path}") from exc
                if not member.isfile() or member.issym() or member.islnk():
                    raise OperationError(f"unsupported backup member: {raw_path}")
                source = bundle.extractfile(member)
                if source is None:
                    raise OperationError(f"backup member is unreadable: {raw_path}")
                payload = source.read(_MAX_BACKUP_BYTES - total + 1)
                total += len(payload)
                files += 1
                if total > _MAX_BACKUP_BYTES or len(payload) != raw_size:
                    raise OperationError("backup bytes exceed the resource budget or size mismatch")
                if hashlib.sha256(payload).hexdigest() != raw_hash:
                    raise OperationError(f"backup member checksum mismatch: {raw_path}")
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _ = target.write_bytes(payload)
                _ = target.chmod((raw_mode & 0o700) or 0o600)
        ledger = temporary / ".sb" / "ledger.db"
        if ledger.is_file():
            assert_ledger_integrity(ledger)
        reasons = audit_citations(temporary)
        if reasons:
            raise OperationError("restored vault citation audit failed: " + "; ".join(reasons[:5]))
        previous: Path | None = None
        if destination_path.exists():
            if not force and any(destination_path.iterdir()):
                raise OperationError("restore destination is not empty; use --force")
            if any(destination_path.iterdir()):
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                # Reserve a fresh sibling even when multiple restores share a second.
                previous = Path(mkdtemp(
                    prefix=f"{destination_path.name}.pre-restore-{stamp}-", dir=parent
                ))
                os.replace(destination_path, previous)
        try:
            # Replacing an empty directory is atomic on supported POSIX hosts.
            # Keep it in place until publication succeeds so failure preserves it.
            os.replace(temporary, destination_path)
        except OSError:
            if previous is not None:
                # Publication failed after moving the old vault aside. Restore
                # its original entry point, without overwriting a new occupant.
                try:
                    if os.path.lexists(destination_path):
                        raise OSError("restore destination appeared during publication")
                    os.replace(previous, destination_path)
                except OSError as rollback_error:
                    raise OperationError(
                        f"RESTORE_ROLLBACK_FAILED: previous vault preserved at {previous}"
                    ) from rollback_error
            raise
        return RestoreResult(destination_path, files, total, previous)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def retry_failed(
    vault_root: Path | str,
    *,
    stage: str | None = None,
    limit: int | None = None,
) -> int:
    with Ledger(vault_root) as ledger:
        selected = list(ledger.list_derivations(status=DerivStatus.FAILED.value, stage=stage))
        if limit is not None:
            selected = selected[:max(limit, 0)]
        if any(row.stage == "brief" for row in selected):
            # Brief execution rebuilds today's key; it cannot replay arbitrary
            # historical keys without their frozen inputs and target date.
            # Reject the whole selection before resetting any other attempts.
            raise OperationError(
                "BRIEF_REPLAY_INPUTS_UNAVAILABLE: historical brief retry is held; "
                "failed rows and attempts are preserved"
            )
        return ledger.retry_failed(stage=stage, limit=limit, reset_attempts=True)


def status_snapshot(config: Config) -> dict[str, object]:
    root = Path(config.vault_root)
    db = root / ".sb" / "ledger.db"
    derivations: dict[str, int] = {status.value: 0 for status in DerivStatus}
    runs: dict[str, int] = {}
    failed: list[dict[str, object]] = []
    failed_by_stage: dict[str, int] = {}
    last_run: dict[str, object] | None = None
    recent_stages: list[dict[str, object]] = []
    if db.is_file():
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='run_stage'").fetchone():
                for row in conn.execute(
                    "SELECT run_id,stage,status,errors,detail FROM run_stage "
                    "ORDER BY started_at DESC,run_id DESC LIMIT 10"
                ):
                    recent_stages.append({
                        "run_id": row[0], "stage": row[1], "status": row[2],
                        "errors": row[3], "error": _safe_detail(row[4]),
                    })
        tables = load_ledger_tables(db)
        for row in tables.derivations.values():
            derivations[row.status] = derivations.get(row.status, 0) + 1
            if row.status == DerivStatus.FAILED.value:
                failed_by_stage[row.stage] = failed_by_stage.get(row.stage, 0) + 1
            if row.status == DerivStatus.FAILED.value and len(failed) < 20:
                failed.append(
                    {
                        "key": row.deriv_key,
                        "stage": row.stage,
                        "attempts": row.attempts,
                        "error": _safe_detail(row.error),
                        "retry_hold_reason": "BRIEF_REPLAY_INPUTS_UNAVAILABLE"
                        if row.stage == "brief" else None,
                    }
                )
        ordered = sorted(tables.runs.values(), key=lambda row: (row.started_at, row.run_id))
        for row in ordered:
            runs[row.status] = runs.get(row.status, 0) + 1
        if ordered:
            last_run = asdict(ordered[-1])
    page_counts = {
        name: sum(1 for _ in (root / name).rglob("*.md")) if (root / name).is_dir() else 0
        for name in ("wiki", "daily", "conflicts")
    }
    raw_files = (
        [path for path in (root / "raw").rglob("*") if path.is_file()]
        if (root / "raw").is_dir()
        else []
    )
    return {
        "vault_root": str(root),
        "initialized": (root / ".git").is_dir(),
        "schema_version": ledger_schema_version(db),
        "schema_current": CURRENT_SCHEMA_VERSION,
        "git_head": _git_value(root, "rev-parse", "HEAD") if root.is_dir() else None,
        "git_clean": _git_value(root, "status", "--porcelain") == ""
        if (root / ".git").is_dir()
        else False,
        "last_run": last_run,
        "recent_stages": recent_stages,
        "run_counts": runs,
        "derivation_counts": derivations,
        "failed_derivations": failed,
        "failed_by_stage": failed_by_stage,
        "failed_details_omitted": sum(failed_by_stage.values()) - len(failed),
        "pages": page_counts,
        "raw": {"files": len(raw_files), "bytes": sum(path.stat().st_size for path in raw_files)},
    }


def doctor(config: Config) -> tuple[DoctorCheck, ...]:
    root = Path(config.vault_root)
    checks: list[DoctorCheck] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append(DoctorCheck(name, status, detail))

    add("python", "pass", f"Python runtime available; app {_package_version()}")
    add("git", "pass" if shutil.which("git") else "fail", shutil.which("git") or "git not found")
    if not root.is_dir():
        add("vault", "fail", f"vault missing: {root}")
        return tuple(checks)
    mode = stat.S_IMODE(root.stat().st_mode)
    add("vault", "pass" if mode & 0o077 == 0 else "warn", f"path={root} mode={oct(mode)}")
    add(
        "git-repository",
        "pass" if (root / ".git").is_dir() else "fail",
        "initialized" if (root / ".git").is_dir() else "missing .git",
    )
    db = root / ".sb" / "ledger.db"
    if db.is_file():
        try:
            assert_ledger_integrity(db)
            version = ledger_schema_version(db)
            add(
                "ledger",
                "pass" if version == CURRENT_SCHEMA_VERSION else "warn",
                f"schema={version}/{CURRENT_SCHEMA_VERSION}",
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic boundary
            add("ledger", "fail", str(exc))
    else:
        add("ledger", "warn", "ledger not created yet")
    reasons = audit_citations(root)
    add(
        "citations",
        "pass" if not reasons else "fail",
        "ok" if not reasons else "; ".join(reasons[:5]),
    )
    for source in config.source_roots:
        path = source.get("root")
        if not path:
            continue
        source_path = Path(path)
        status = "pass" if source_path.is_dir() and not source_path.is_symlink() else "fail"
        add(
            f"source:{source.get('id', source.get('adapter', 'unknown'))}", status, str(source_path)
        )
    if root.is_symlink():
        try:
            from sb.generation_runtime_models import generation_runtime_paths
            from sb.generations import GenerationStore
            paths = generation_runtime_paths(config)
            manifest = GenerationStore._read_manifest(paths.active.resolve())
            valid = (_git_value(root, "rev-parse", "HEAD") == manifest.head
                     and _git_value(root, "rev-parse", "HEAD^{tree}") == manifest.tree)
            add("generation", "pass" if valid else "fail", manifest.generation_id)
        except (OSError, RuntimeError, ValueError) as exc:
            add("generation", "fail", str(exc))
    command = config.llm.argv_template[0] if config.llm.argv_template else ""
    llm_status = "pass" if command and shutil.which(command) else "warn"
    add(
        "llm-cli",
        llm_status,
        command if llm_status == "pass" else f"not found: {command or '<empty>'}",
    )
    scheduler = Path(__file__).resolve().parent.parent / "deploy" / "systemd"
    add("scheduler-assets", "pass" if scheduler.is_dir() else "warn", str(scheduler))
    return tuple(checks)


def migrate_status(vault_root: Path | str, *, apply: bool) -> dict[str, object]:
    path = Path(vault_root) / ".sb" / "ledger.db"
    before = ledger_schema_version(path)
    backup = migrate_ledger(path, backup=True) if apply else None
    after = ledger_schema_version(path)
    return {
        "before": before,
        "after": after,
        "current": CURRENT_SCHEMA_VERSION,
        "pending": max(CURRENT_SCHEMA_VERSION - after, 0),
        "backup": str(backup) if backup is not None else None,
    }
