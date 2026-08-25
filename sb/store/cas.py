"""Content-addressed raw store under <vault>/raw/<h[:2]>/<h>."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import override


@dataclass(frozen=True, slots=True)
class CasBlobMissing(Exception):
    """Raised when get() is asked for a hash that is not in the store."""

    content_hash: str

    @override
    def __str__(self) -> str:
        return f"CAS blob missing: {self.content_hash}"


class ContentAddressedStore:
    """Write-once SHA-256 blob store rooted at a vault. Never deletes blobs."""

    _vault_root: Path

    def __init__(self, vault_root: Path | str) -> None:
        self._vault_root = Path(vault_root)

    def put(self, data: bytes) -> str:
        """Store `data` at raw/<h[:2]>/<h> (mode 0444). Idempotent on hash."""
        digest = hashlib.sha256(data).hexdigest()
        dest = self._blob_path(digest)
        if dest.is_file():
            return digest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{digest}.tmp")
        _ = tmp.write_bytes(data)
        tmp.chmod(0o444)
        _ = tmp.replace(dest)
        return digest

    def get(self, content_hash: str) -> bytes:
        """Return the stored bytes for `content_hash`."""
        path = self._blob_path(content_hash)
        if not path.is_file():
            raise CasBlobMissing(content_hash=content_hash)
        return path.read_bytes()

    def exists(self, content_hash: str) -> bool:
        """True when a blob file for `content_hash` is present."""
        return self._blob_path(content_hash).is_file()

    def _blob_path(self, content_hash: str) -> Path:
        return self._vault_root / "raw" / content_hash[:2] / content_hash
