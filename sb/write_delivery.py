"""Write-tool result when the provider published nothing.

JARVIS reconcile must treat this payload as not delivered. It is not an
uncertain mid-apply failure: no durable request file was published, so the
lane may stop reconciling (outcome code ``NOTHING_WRITTEN``).

Tool error text is strict JSON, one object, no prefix:

* ``written`` is always false
* ``delivery`` is always ``"not_written"``
* ``code`` is ``NOTHING_WRITTEN`` when the failure is not an already-catalogued
  rejection, otherwise the catalogue code is kept and ``cause`` repeats it
* ``retryable`` is false

A successful accept (``kind: accepted``) means a request file was published.
Do not treat transport loss after that accept as ``not_written``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

NOTHING_WRITTEN: Final = "NOTHING_WRITTEN"
WRITTEN_WITH_FOLLOWUP_ERROR: Final = "WRITTEN_WITH_FOLLOWUP_ERROR"
WRITE_OUTCOME_UNKNOWN: Final = "WRITE_OUTCOME_UNKNOWN"
RETRY_GUIDANCE: Final = "Retry the same request. Do not treat this as not delivered."


def not_written_fields(*, cause: str) -> dict[str, object]:
    """Fields every pre-publish write failure must include."""
    return {
        "written": False,
        "delivery": "not_written",
        "cause": cause,
    }


def followup_fields(*, cause: str, path: str, request_id: str | None) -> dict[str, object]:
    """Fields when the durable file is already in the vault but a later step failed."""
    fields: dict[str, object] = {
        "written": True,
        "delivery": "written",
        "cause": cause,
        "path": path,
        "retryable": True,
    }
    if request_id is not None:
        fields["request_id"] = request_id
    return fields


def _safe_request_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    if value.startswith(".") or "/" in value or "\\" in value or "\n" in value or "\x00" in value:
        return None
    return value


def unknown_fields(*, cause: str) -> dict[str, object]:
    """Fields when committed state cannot be determined. Never means not written."""
    return {
        "written": None,
        "delivery": "unknown",
        "cause": cause,
        "retryable": True,
        "retry": RETRY_GUIDANCE,
    }


Evidence = Literal["absent", "present", "unknown"]


@dataclass(frozen=True, slots=True)
class DeliveryLookup:
    evidence: Evidence
    path: str | None = None
    request_id: str | None = None


def _stat_kind(path: Path) -> Literal["missing", "dir", "file", "other", "error"]:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"
    if stat.S_ISLNK(metadata.st_mode):
        return "other"
    if stat.S_ISDIR(metadata.st_mode):
        return "dir"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return "other"


def _relative(path: Path, *roots: Path) -> str:
    for root in roots:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _names(identity: str, schema_version: object) -> tuple[str, ...]:
    if schema_version == 1:
        return (f"{identity}.v1.json", f"{identity}.json")
    if schema_version == 2:
        return (f"{identity}.v2.json",)
    if schema_version == 3:
        return (f"{identity}.v3.json",)
    return (
        f"{identity}.v1.json",
        f"{identity}.v2.json",
        f"{identity}.v3.json",
        f"{identity}.json",
    )


def _scan_dir(directory: Path, identity: str, names: tuple[str, ...]) -> Evidence | Path:
    kind = _stat_kind(directory)
    if kind == "missing" or kind == "other":
        return "absent"
    if kind == "error" or kind == "file":
        return "unknown" if kind == "error" else "absent"
    try:
        entries = list(directory.iterdir())
    except OSError:
        return "unknown"
    suffixes = {name for name in names}
    for entry in entries:
        matched = entry.name in suffixes or (
            entry.name.startswith(f"{identity}.") and entry.name.endswith(".json")
        )
        if not matched:
            continue
        file_kind = _stat_kind(entry)
        if file_kind == "file":
            return entry
        if file_kind == "error":
            return "unknown"
    return "absent"


def _journal_hit(request_root: Path, identity: str) -> Evidence | str:
    database = request_root / "journal.db"
    kind = _stat_kind(database)
    if kind == "missing":
        return "absent"
    if kind != "file":
        return "unknown"
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute(
                "SELECT result_json FROM requests WHERE request_id=?",
                (identity,),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return "unknown"
    if row is None:
        return "absent"
    raw = row[0]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            inbox = loaded.get("inbox_path")
            if isinstance(inbox, str) and inbox:
                return inbox
    return f"journal.db#{identity}"


def classify_delivery(
    request_root: Path, vault_root: Path, request_id: object, schema_version: object
) -> DeliveryLookup:
    """Decide from pending, processing, receipts, and the journal. Lookup errors are unknown."""
    identity = _safe_request_id(request_id)
    if identity is None:
        return DeliveryLookup("absent")
    names = _names(identity, schema_version)
    uncertain = False
    directories = (
        request_root / "pending",
        request_root / "processing",
        request_root / "receipts",
        vault_root / "inbox" / ".requests" / "pending",
    )
    for directory in directories:
        found = _scan_dir(directory, identity, names)
        if isinstance(found, Path):
            return DeliveryLookup("present", _relative(found, request_root, vault_root), identity)
        if found == "unknown":
            uncertain = True
    journal = _journal_hit(request_root, identity)
    if isinstance(journal, str) and journal not in {"absent", "unknown"}:
        return DeliveryLookup("present", journal, identity)
    if journal == "unknown":
        uncertain = True
    if uncertain:
        return DeliveryLookup("unknown", request_id=identity)
    return DeliveryLookup("absent", request_id=identity)
