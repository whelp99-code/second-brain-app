"""Read-only source status and conservative content-retention operations."""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sb.config import Config
from sb.security import source_policy_snapshot
from sb.store import parse_page_frontmatter
from sb.store.ledger import Ledger

_HEX: Final = frozenset("0123456789abcdef")
_PAGE_FOLDERS: Final = ("wiki", "daily", "conflicts")


class GovernanceError(RuntimeError):
    """Raised when an operator governance action is unsafe or unapproved."""


@dataclass(frozen=True, slots=True)
class RetentionReport:
    raw_blobs: int
    raw_bytes: int
    protected_blobs: int
    orphan_blobs: tuple[str, ...]
    invalid_blobs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_blobs": self.raw_blobs,
            "raw_bytes": self.raw_bytes,
            "protected_blobs": self.protected_blobs,
            "orphan_blobs": list(self.orphan_blobs),
            "orphan_count": len(self.orphan_blobs),
            "invalid_blobs": list(self.invalid_blobs),
            "invalid_count": len(self.invalid_blobs),
        }


def source_status(config: Config) -> tuple[dict[str, object], ...]:
    """Return a content-free status view of configured source policies."""
    return source_policy_snapshot(config)


def retention_report(vault_root: Path | str) -> RetentionReport:
    """Classify verified CAS blobs without mutating the Vault."""
    root = Path(vault_root).expanduser().resolve(strict=False)
    raw, invalid = _raw_files(root)
    protected = _page_hashes(root) | _ledger_hashes(root)
    orphans = tuple(sorted(set(raw) - protected))
    return RetentionReport(
        raw_blobs=len(raw),
        raw_bytes=sum(path.stat().st_size for path in raw.values()),
        protected_blobs=len(set(raw) & protected),
        orphan_blobs=orphans,
        invalid_blobs=tuple(sorted(invalid)),
    )


def collect_orphans(
    vault_root: Path | str,
    *,
    apply: bool = False,
    confirmed: bool = False,
) -> RetentionReport:
    """Dry-run by default; delete only verified unreferenced CAS with confirmation."""
    root = Path(vault_root).expanduser().resolve(strict=False)
    if not apply:
        return retention_report(root)
    if not confirmed:
        raise GovernanceError("orphan deletion requires --apply --confirm")
    with _exclusive_vault(root):
        report = retention_report(root)
        raw, _invalid = _raw_files(root)
        for digest in report.orphan_blobs:
            path = raw.get(digest)
            if path is None:
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise GovernanceError(f"failed to delete orphan {digest}: {exc}") from exc
            parent = path.parent
            raw_root = root / "raw"
            if parent != raw_root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    return retention_report(root)


@contextmanager
def _exclusive_vault(root: Path) -> Generator[None, None, None]:
    lock = root / ".sb" / "run.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GovernanceError("vault is busy; retention mutation refused") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and set(value) <= _HEX


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _raw_files(root: Path) -> tuple[dict[str, Path], set[str]]:
    raw_root = root / "raw"
    found: dict[str, Path] = {}
    invalid: set[str] = set()
    if not raw_root.is_dir():
        return found, invalid
    for path in sorted(raw_root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(raw_root).as_posix()
        digest = path.name
        if (
            not _valid_digest(digest)
            or path.parent.name != digest[:2]
            or _safe_hash(path) != digest
        ):
            invalid.add(relative)
            continue
        found[digest] = path
    return found, invalid


def _safe_hash(path: Path) -> str | None:
    try:
        return _sha256(path)
    except OSError:
        return None


def _page_hashes(root: Path) -> set[str]:
    protected: set[str] = set()
    for folder in _PAGE_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            facts = parse_page_frontmatter(text)
            if facts is None:
                continue
            protected.update(
                digest for _origin, digest in facts.sources if _valid_digest(digest)
            )
    return protected


def _ledger_hashes(root: Path) -> set[str]:
    if not (root / ".sb" / "ledger.db").is_file():
        return set()
    with Ledger(root) as ledger:
        return {
            item.content_hash
            for item in ledger.list_source_items()
            if _valid_digest(item.content_hash)
        }
