"""One-time import of owned legacy V1 request finals."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import final

from sb.contracts import WriteOperation
from sb.request_store import RequestStore
from sb.stable_requests import (
    StableRequestError,
    accept_stable_v1_request,
    request_value,
    safe_request_file,
)
from sb.write_request_values import parse_envelope_bytes


@final
class LegacyRequestImporterV1:
    """Import each owned legacy V1 final at most once into the stable journal."""

    def __init__(self, request_root: Path, legacy_roots: tuple[Path, ...]) -> None:
        self.request_root = request_root
        self.legacy_roots = legacy_roots

    def import_once(self, now: datetime) -> tuple[int, int]:
        imported = 0
        reapproval = 0
        store = RequestStore(self.request_root)
        try:
            for root in self.legacy_roots:
                pending = root / "inbox" / ".requests" / "pending"
                if not pending.exists():
                    continue
                metadata = pending.stat(follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                for path in sorted(pending.iterdir(), key=lambda item: item.name):
                    if path.is_symlink():
                        raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                    file_metadata = path.stat(follow_symlinks=False)
                    if not safe_request_file(file_metadata):
                        raise StableRequestError("WRITE_REQUEST_INBOX_UNSAFE")
                    raw = path.read_bytes()
                    locator = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
                    import_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
                    envelope = parse_envelope_bytes(raw)
                    operation = envelope.request.operation
                    if operation is WriteOperation.REMEMBER:
                        accepted = accept_stable_v1_request(
                            self.request_root,
                            request_value(envelope.request),
                            now,
                        )
                        fresh = store.record_import(
                            import_digest,
                            locator,
                            str(accepted.request_id),
                            "published",
                            now,
                        )
                        imported += int(fresh)
                    else:
                        fresh = store.record_import(
                            import_digest,
                            locator,
                            str(envelope.request.request_id),
                            "reapproval_required",
                            now,
                        )
                        reapproval += int(fresh)
                    path.unlink()
                    descriptor = os.open(
                        pending,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                    )
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            return imported, reapproval
        finally:
            store.close()
