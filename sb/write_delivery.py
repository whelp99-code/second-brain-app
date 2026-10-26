"""Evidence-bound write-tool failure outcomes.

Only an exact validated request artifact or journal identity proves delivery.
An unreadable or malformed observation remains unknown, never success or absence.
A known nonmatching request is not delivery evidence for the rejected submission.
These read-only lookups neither accept a request nor retry its effects.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sb.effect_values import (
    JsonObject,
    canonical_bytes,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.effect_write_values import MAX_EFFECT_FILE_BYTES, model_object, parse_effect_request
from sb.request_publication import recover_publication
from sb.stable_requests import request_value
from sb.write_request_values import (
    DIGEST,
    WriteRequestRejected,
    parse_remember_envelope,
    parse_request,
    parse_request_v3,
)

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


def _scan_dir(directory: Path, identity: str, names: tuple[str, ...]) -> Evidence | list[Path]:
    kind = _stat_kind(directory)
    if kind == "missing":
        return "absent"
    if kind != "dir":
        return "unknown"
    try:
        entries = list(directory.iterdir())
    except OSError:
        return "unknown"
    suffixes = {name for name in names}
    found: list[Path] = []
    for entry in entries:
        matched = entry.name in suffixes or (
            entry.name.startswith(f"{identity}.") and entry.name.endswith(".json")
        )
        if not matched:
            continue
        file_kind = _stat_kind(entry)
        if file_kind == "file":
            found.append(entry)
        else:
            return "unknown"
    return found


def _validated_request(
    raw: JsonObject,
    accepted: str,
    *,
    public_keys: Mapping[str, Ed25519PublicKey] | None,
    provider_instance_id: str | None,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None,
) -> JsonObject:
    version = raw.get("schema_version")
    if version == 1:
        return request_value(parse_request(raw, parse_instant(accepted)))
    if version == 3:
        return request_value(parse_request_v3(raw, parse_instant(accepted)))
    if version == 2:
        return model_object(
            parse_effect_request(
                raw,
                now=accepted,
                public_keys=public_keys,
                expected_provider=provider_instance_id,
                external_public_keys=external_public_keys,
            )
        )
    raise ValueError("WRITE_REQUEST_INVALID")


def _journal_hit(
    request_root: Path,
    raw: JsonObject,
    *,
    public_keys: Mapping[str, Ed25519PublicKey] | None,
    provider_instance_id: str | None,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None,
) -> Evidence | str:
    database = request_root / "journal.db"
    kind = _stat_kind(database)
    if kind == "missing":
        return "absent"
    if kind != "file":
        return "unknown"
    try:
        uri = database.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = cast(
                tuple[object, ...] | None,
                connection.execute(
                    "SELECT schema_version,request_digest,envelope_digest,idempotency_key,accepted_at,result_json FROM requests WHERE request_id=?",
                    (raw.get("request_id"),),
                ).fetchone(),
            )
    except (OSError, sqlite3.Error):
        return "unknown"
    if row is None:
        return "absent"
    version, request_digest, envelope_digest, idempotency_key, accepted, result_json = row
    if not isinstance(accepted, str) or not isinstance(result_json, str):
        return "unknown"
    if (
        version not in (1, 2, 3)
        or not isinstance(request_digest, str)
        or DIGEST.fullmatch(request_digest) is None
        or not isinstance(idempotency_key, str)
    ):
        return "unknown"
    if (
        version == 2
        and (not isinstance(envelope_digest, str) or DIGEST.fullmatch(envelope_digest) is None)
        or version != 2
        and envelope_digest is not None
    ):
        return "unknown"
    try:
        _ = parse_instant(accepted)
        loaded = strict_loads(result_json, MAX_EFFECT_FILE_BYTES)
    except ValueError:
        return "unknown"
    if not is_json_object(loaded) or loaded.get("kind") != "accepted":
        return "unknown"
    expected: dict[str, object] = {
        "schema_version": version,
        "request_id": raw.get("request_id"),
        "request_digest": request_digest,
        "idempotency_key": idempotency_key,
        "accepted_at": accepted,
    }
    if version == 2:
        expected["envelope_digest"] = envelope_digest
    for field, value in expected.items():
        if loaded.get(field) != value:
            return "unknown"
    locator = loaded.get("queue_locator" if version == 2 else "inbox_path")
    if (
        not isinstance(locator, str)
        or not locator
        or Path(locator).is_absolute()
        or ".." in Path(locator).parts
    ):
        return "unknown"
    try:
        request = _validated_request(
            raw,
            accepted,
            public_keys=public_keys,
            provider_instance_id=provider_instance_id,
            external_public_keys=external_public_keys,
        )
    except (ValueError, WriteRequestRejected):
        return "absent"
    if (version, request_digest, envelope_digest, idempotency_key) != (
        request["schema_version"],
        request["request_digest"],
        request.get("envelope_digest"),
        request["idempotency_key"],
    ):
        return "absent"
    if loaded.get("operation") != request["operation"]:
        return "unknown"
    return locator


def classify_delivery(
    request_root: Path,
    vault_root: Path,
    raw: JsonObject,
    *,
    public_keys: Mapping[str, Ed25519PublicKey] | None = None,
    provider_instance_id: str | None = None,
    external_public_keys: Mapping[str, Ed25519PublicKey] | None = None,
) -> DeliveryLookup:
    """Only exact validated request evidence is present; unreadable evidence is unknown."""
    identity = _safe_request_id(raw.get("request_id"))
    if identity is None:
        return DeliveryLookup("absent")
    names = _names(identity, raw.get("schema_version"))
    uncertain = False

    def validate_json(payload: bytes, _expected: bytes) -> None:
        _ = strict_loads(payload, MAX_EFFECT_FILE_BYTES)

    directories = (
        request_root / "pending",
        request_root / "processing",
        request_root / "receipts",
        vault_root / "inbox" / ".requests" / "pending",
    )
    for directory in directories:
        found = _scan_dir(directory, identity, names)
        if isinstance(found, list):
            for path in found:
                try:
                    payload = recover_publication(
                        path,
                        b"",
                        max_bytes=MAX_EFFECT_FILE_BYTES,
                        validate_recovery=validate_json,
                    )
                    envelope = strict_loads(payload, MAX_EFFECT_FILE_BYTES)
                    if not is_json_object(envelope):
                        raise ValueError("WRITE_REQUEST_INVALID")
                    accepted = envelope.get("accepted_at")
                    if not isinstance(accepted, str) or envelope.get("state") != "pending":
                        raise ValueError("WRITE_REQUEST_INVALID")
                    if envelope.get("schema_version") in (1, 3):
                        stored = request_value(parse_remember_envelope(payload).request)
                    else:
                        value = envelope.get("request")
                        if envelope.get("schema_version") != 2 or not is_json_object(value):
                            raise ValueError("WRITE_REQUEST_INVALID")
                        stored = _validated_request(
                            value,
                            accepted,
                            public_keys=public_keys,
                            provider_instance_id=provider_instance_id,
                            external_public_keys=external_public_keys,
                        )
                except (OSError, ValueError, WriteRequestRejected):
                    uncertain = True
                    continue
                try:
                    submitted = _validated_request(
                        raw,
                        accepted,
                        public_keys=public_keys,
                        provider_instance_id=provider_instance_id,
                        external_public_keys=external_public_keys,
                    )
                except (ValueError, WriteRequestRejected):
                    continue
                if canonical_bytes(stored) == canonical_bytes(submitted):
                    return DeliveryLookup(
                        "present", _relative(path, request_root, vault_root), identity
                    )
        if found == "unknown":
            uncertain = True
    journal = _journal_hit(
        request_root,
        raw,
        public_keys=public_keys,
        provider_instance_id=provider_instance_id,
        external_public_keys=external_public_keys,
    )
    if isinstance(journal, str) and journal not in {"absent", "unknown"}:
        return DeliveryLookup("present", journal, identity)
    if journal == "unknown":
        uncertain = True
    if uncertain:
        return DeliveryLookup("unknown", request_id=identity)
    return DeliveryLookup("absent", request_id=identity)
