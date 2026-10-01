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

import stat
from pathlib import Path
from typing import Final

NOTHING_WRITTEN: Final = "NOTHING_WRITTEN"
WRITTEN_WITH_FOLLOWUP_ERROR: Final = "WRITTEN_WITH_FOLLOWUP_ERROR"


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


def _regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode)


def published_request_file(
    request_root: Path, vault_root: Path, request_id: object, schema_version: object
) -> tuple[str, str] | None:
    """Return ``(path, request_id)`` when a durable request file is already linked."""
    identity = _safe_request_id(request_id)
    if identity is None:
        return None
    if schema_version == 1:
        names = (f"{identity}.v1.json", f"{identity}.json")
    elif schema_version == 2:
        names = (f"{identity}.v2.json",)
    elif schema_version == 3:
        names = (f"{identity}.v3.json",)
    else:
        names = (f"{identity}.v1.json", f"{identity}.v2.json", f"{identity}.v3.json", f"{identity}.json")
    candidates = [request_root / "pending" / name for name in names]
    candidates.append(vault_root / "inbox" / ".requests" / "pending" / f"{identity}.json")
    for path in candidates:
        if not _regular_file(path):
            continue
        for root in (request_root, vault_root):
            try:
                return path.resolve().relative_to(root.resolve()).as_posix(), identity
            except ValueError:
                continue
        return path.as_posix(), identity
    return None
