"""Permanent provider tombstone reingress authority."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import final

from sb.effect_values import format_instant
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.sqlite_values import OPTIONAL_INTEGER_ROW


class ErasureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IngressIdentity:
    source: str
    content: str
    subject: str | None = None
    citation: str | None = None


@dataclass(frozen=True, slots=True)
class NewVersionAuthority:
    identity: IngressIdentity
    authority_digest: str
    approved_at: datetime


@final
class ReingressGate:
    """Persist blocked stable source/subject identities before every ingress write."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None)
        _ = self.db.execute("PRAGMA journal_mode=DELETE")
        _ = self.db.execute("PRAGMA synchronous=FULL")
        _ = self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS blocked_identities(
              identity_kind TEXT NOT NULL CHECK(identity_kind IN ('source','subject','content','citation')),
              identity_digest TEXT NOT NULL,
              tombstone_sequence INTEGER NOT NULL,
              tombstone_set_root TEXT NOT NULL,
              blocked_at TEXT NOT NULL,
              PRIMARY KEY(identity_kind,identity_digest)
            );
            CREATE TABLE IF NOT EXISTS new_version_exceptions(
              source_identity_digest TEXT NOT NULL,
              content_identity_digest TEXT NOT NULL,
              authority_digest TEXT NOT NULL UNIQUE,
              approved_at TEXT NOT NULL,
              PRIMARY KEY(source_identity_digest,content_identity_digest)
            );
            CREATE TRIGGER IF NOT EXISTS blocked_no_update BEFORE UPDATE ON blocked_identities
              BEGIN SELECT RAISE(ABORT,'immutable blocked identity'); END;
            CREATE TRIGGER IF NOT EXISTS blocked_no_delete BEFORE DELETE ON blocked_identities
              BEGIN SELECT RAISE(ABORT,'immutable blocked identity'); END;
            """
        )
        path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def block_request(self, request: MemoryEffectWriteRequestV2, now: datetime) -> None:
        if request.operation not in {"correct", "forget"}:
            return
        rows: list[tuple[str, str, int, str, str]] = []
        for target in request.targets:
            rows.extend(
                (
                    (
                        "source", target.source_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root, format_instant(now),
                    ),
                    (
                        "content", target.content_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root, format_instant(now),
                    ),
                    (
                        "citation", target.citation_identity_full,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root, format_instant(now),
                    ),
                    (
                        "subject", target.subject_digest,
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root, format_instant(now),
                    ),
                )
            )
        _ = self.db.executemany(
            "INSERT OR IGNORE INTO blocked_identities VALUES(?,?,?,?,?)",
            rows,
        )

    def check(self, identity: IngressIdentity) -> None:
        checks = [("source", identity.source), ("content", identity.content)]
        if identity.subject is not None:
            checks.append(("subject", identity.subject))
        if identity.citation is not None:
            checks.append(("citation", identity.citation))
        blocked = False
        for kind, candidate in checks:
            row = OPTIONAL_INTEGER_ROW.validate_python(self.db.execute(
                "SELECT 1 FROM blocked_identities WHERE identity_kind=? AND identity_digest=?",
                (kind, candidate),
            ).fetchone())
            blocked = blocked or row is not None
        if not blocked:
            return
        exception = OPTIONAL_INTEGER_ROW.validate_python(self.db.execute(
            "SELECT 1 FROM new_version_exceptions "
            + "WHERE source_identity_digest=? AND content_identity_digest=?",
            (identity.source, identity.content),
        ).fetchone())
        if exception is None:
            raise ErasureError("TOMBSTONE_REINGRESS_BLOCKED")

    def check_content(self, content: bytes) -> None:
        candidates = {hashlib.sha256(content).hexdigest()}
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        candidates.update(
            hashlib.sha256(part.encode("utf-8")).hexdigest()
            for part in {text, *text.splitlines(), *text.split("\n\n")}
            if part
        )
        placeholders = ",".join("?" for _candidate in candidates)
        row = OPTIONAL_INTEGER_ROW.validate_python(self.db.execute(
            "SELECT 1 FROM blocked_identities WHERE identity_kind='content' "
            + f"AND identity_digest IN ({placeholders}) LIMIT 1",
            tuple(sorted(candidates)),
        ).fetchone())
        if row is not None:
            raise ErasureError("TOMBSTONE_REINGRESS_BLOCKED")

    def allow_new_version(self, authority: NewVersionAuthority) -> None:
        _ = self.db.execute(
            "INSERT INTO new_version_exceptions VALUES(?,?,?,?)",
            (
                authority.identity.source,
                authority.identity.content,
                authority.authority_digest,
                format_instant(authority.approved_at),
            ),
        )
