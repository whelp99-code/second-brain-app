"""Closed parsing and identity checks for memory-write requests."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Never, TypeGuard, override

from sb.contracts import (
    CandidateId,
    Digest,
    ExpectedPriorV1,
    JarvisReceiptV1,
    MemoryWriteRequestV1,
    RequestId,
    WriteOperation,
)
from sb.page_ids import git_rel
from sb.vault import PathEscapeError

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
MAX_REQUEST_BYTES: Final = 16_384
MAX_ENVELOPE_BYTES: Final = 17_408
DOMAINS: Final = {
    "receipt": b"orca-jarvis/memory-write-receipt/v1\0",
    "idempotency": b"orca-jarvis/memory-write-idempotency/v1\0",
    "request": b"orca-jarvis/memory-write-request/v1\0",
    "file": b"second-brain/inbox-write-request/v1\0",
}
DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
CANDIDATE: Final = re.compile(r"memcand:pos:v1:[0-9a-f]{64}\Z")
REQUEST: Final = re.compile(r"memreq:pos:v1:[0-9a-f]{64}\Z")
IDEMPOTENCY: Final = re.compile(r"memidem:pos:v1:[0-9a-f]{64}\Z")
RECEIPT: Final = re.compile(r"receipt:memory:[0-9a-f]{64}\Z")
INSTANT: Final = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z")
SENSITIVITIES: Final = ("public", "personal", "sensitive", "restricted")
ROOT_KEYS: Final = frozenset({"schema_version", "candidate_id", "candidate_digest", "classification_digest", "idempotency_key", "request_id", "request_digest", "operation", "subject", "purpose", "sensitivity", "retention_days", "created_at", "expires_at", "expected_prior", "receipt", "receipt_digest", "payload"})
RECEIPT_KEYS: Final = frozenset({"schema_version", "receipt_id", "candidate_id", "candidate_digest", "classification_digest", "operation", "decision", "principal_id", "issued_at", "expires_at"})


@dataclass(frozen=True, slots=True)
class WriteRequestRejected(Exception):
    code: str

    @override
    def __str__(self) -> str:
        return self.code


def reject(code: str) -> Never:
    raise WriteRequestRejected(code)


def _is_record(value: JsonValue) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict)


def _record(value: JsonValue, keys: frozenset[str]) -> dict[str, JsonValue]:
    if not _is_record(value):
        reject("WRITE_REQUEST_INVALID")
    if frozenset(value) != keys:
        reject("WRITE_REQUEST_INVALID")
    return value


def _text(value: JsonValue, maximum: int, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str):
        reject("WRITE_REQUEST_INVALID")
    invalid = not value or value != value.strip() or unicodedata.normalize("NFC", value) != value
    invalid = invalid or len(value.encode("utf-8")) > maximum
    invalid = invalid or any(ord(char) < 32 or ord(char) == 127 for char in value)
    if invalid:
        reject("WRITE_REQUEST_INVALID")
    if pattern is not None and pattern.fullmatch(value) is None:
        reject("WRITE_REQUEST_IDENTITY_INVALID")
    return value


def _instant(value: JsonValue) -> datetime:
    text = _text(value, 24)
    if INSTANT.fullmatch(text) is None:
        reject("WRITE_REQUEST_INVALID")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INVALID") from exc
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != text:
        reject("WRITE_REQUEST_INVALID")
    return parsed


def canonical_bytes(value: JsonValue) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise WriteRequestRejected("WRITE_REQUEST_INVALID") from exc


def digest(domain: str, value: JsonValue) -> Digest:
    return Digest("sha256:" + hashlib.sha256(DOMAINS[domain] + canonical_bytes(value)).hexdigest())


def _operation(value: JsonValue) -> WriteOperation:
    try:
        return WriteOperation(_text(value, 8))
    except ValueError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_OPERATION_INVALID") from exc


def _decision(value: JsonValue) -> Literal["auto_staged", "owner_confirmed"]:
    text = _text(value, 15)
    if text == "auto_staged":
        return "auto_staged"
    if text == "owner_confirmed":
        return "owner_confirmed"
    reject("WRITE_REQUEST_RECEIPT_INVALID")


def _receipt(
    raw: JsonValue,
    request: dict[str, JsonValue],
    created: datetime,
    now: datetime,
) -> JarvisReceiptV1:
    try:
        value = _record(raw, RECEIPT_KEYS)
        operation = _operation(value["operation"])
        issued, expires = _instant(value["issued_at"]), _instant(value["expires_at"])
    except WriteRequestRejected as exc:
        raise WriteRequestRejected("WRITE_REQUEST_RECEIPT_INVALID") from exc
    if value["schema_version"] != 1 or value["principal_id"] != "principal:owner":
        reject("WRITE_REQUEST_RECEIPT_INVALID")
    if not created <= issued < expires or not issued <= now < expires:
        reject("WRITE_REQUEST_RECEIPT_INVALID")
    for key in ("candidate_id", "candidate_digest", "classification_digest", "operation"):
        if value[key] != request[key]:
            reject("WRITE_REQUEST_RECEIPT_INVALID")
    receipt_id = _text(value["receipt_id"], 79)
    if RECEIPT.fullmatch(receipt_id) is None:
        reject("WRITE_REQUEST_RECEIPT_INVALID")
    return JarvisReceiptV1(receipt_id, CandidateId(_text(value["candidate_id"], 79)), Digest(_text(value["candidate_digest"], 71)), Digest(_text(value["classification_digest"], 71)), operation, _decision(value["decision"]), "principal:owner", _text(value["issued_at"], 24), _text(value["expires_at"], 24))


def _prior(raw: JsonValue) -> ExpectedPriorV1 | None:
    if raw is None:
        return None
    value = _record(raw, frozenset({"source_id", "source_version", "source_digest"}))
    raw_source_id = value["source_id"]
    if not isinstance(raw_source_id, str):
        reject("WRITE_REQUEST_PATH_INVALID")
    try:
        relative = git_rel(raw_source_id)
    except PathEscapeError as exc:
        raise WriteRequestRejected("WRITE_REQUEST_PATH_INVALID") from exc
    source_id = relative.removesuffix(".md")
    if not source_id.startswith(("wiki/", "daily/", "conflicts/")):
        reject("WRITE_REQUEST_PATH_INVALID")
    version, source_digest = _text(value["source_version"], 44), _text(value["source_digest"], 71)
    if re.fullmatch(r"git:[0-9a-f]{40}", version) is None or DIGEST.fullmatch(source_digest) is None:
        reject("WRITE_REQUEST_INVALID")
    return ExpectedPriorV1(source_id, version, Digest(source_digest))


def _payload(operation: WriteOperation, raw: JsonValue) -> dict[str, str]:
    expected = {WriteOperation.REMEMBER: {"content"}, WriteOperation.CORRECT: {"content"}, WriteOperation.FORGET: {"disposition"}, WriteOperation.EXPORT: {"format", "scope"}}[operation]
    value = _record(raw, frozenset(expected))
    parsed = {key: _text(item, 4_096) for key, item in value.items()}
    valid = operation in {WriteOperation.REMEMBER, WriteOperation.CORRECT}
    valid = valid or operation == WriteOperation.FORGET and parsed == {"disposition": "owner_requested"}
    valid = valid or operation == WriteOperation.EXPORT and parsed == {"format": "json", "scope": "subject"}
    if not valid:
        reject("WRITE_REQUEST_OPERATION_CONFUSION")
    return parsed


def parse_request(raw: JsonValue, now: datetime) -> MemoryWriteRequestV1:
    """Parse external JSON-compatible input into the closed V1 contract."""
    value = _record(raw, ROOT_KEYS)
    if len(canonical_bytes(value)) > MAX_REQUEST_BYTES:
        reject("WRITE_REQUEST_OVERSIZE")
    if value["schema_version"] != 1:
        reject("WRITE_REQUEST_INVALID")
    candidate = _text(value["candidate_id"], 79, CANDIDATE)
    candidate_digest = _text(value["candidate_digest"], 71, DIGEST)
    classification = _text(value["classification_digest"], 71, DIGEST)
    idempotency = _text(value["idempotency_key"], 80, IDEMPOTENCY)
    request_id = _text(value["request_id"], 79, REQUEST)
    request_digest = _text(value["request_digest"], 71, DIGEST)
    operation = _operation(value["operation"])
    created, expires = _instant(value["created_at"]), _instant(value["expires_at"])
    if not created <= now < expires or expires - created > timedelta(hours=24):
        reject("WRITE_REQUEST_INVALID")
    prior = _prior(value["expected_prior"])
    purpose, retention = {WriteOperation.REMEMBER: ("personal_memory", range(1, 3651)), WriteOperation.CORRECT: ("personal_memory", range(1, 3651)), WriteOperation.FORGET: ("data_erasure", {30}), WriteOperation.EXPORT: ("data_portability", {1})}[operation]
    retention_days = value["retention_days"]
    if value["purpose"] != purpose or not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days not in retention:
        reject("WRITE_REQUEST_OPERATION_CONFUSION")
    if operation == WriteOperation.REMEMBER and prior is not None:
        reject("WRITE_REQUEST_PRIOR_FORBIDDEN")
    if operation != WriteOperation.REMEMBER and prior is None:
        reject("WRITE_REQUEST_PRIOR_REQUIRED")
    sensitivity = _text(value["sensitivity"], 10)
    if sensitivity not in SENSITIVITIES:
        reject("WRITE_REQUEST_INVALID")
    receipt = _receipt(value["receipt"], value, created, now)
    if value["receipt_digest"] != digest("receipt", value["receipt"]):
        reject("WRITE_REQUEST_RECEIPT_INVALID")
    expected_idempotency = digest("idempotency", {"candidate_id": candidate, "candidate_digest": candidate_digest, "classification_digest": classification, "operation": operation.value})
    if idempotency != "memidem:pos:v1:" + expected_idempotency[7:]:
        reject("WRITE_REQUEST_IDENTITY_INVALID")
    base = {key: item for key, item in value.items() if key not in {"request_id", "request_digest"}}
    expected_request = digest("request", base)
    if request_id != "memreq:pos:v1:" + request_digest[7:]:
        reject("WRITE_REQUEST_IDENTITY_INVALID")
    if request_digest != expected_request:
        reject("WRITE_REQUEST_REPLAY_CONFLICT")
    return MemoryWriteRequestV1(CandidateId(candidate), Digest(candidate_digest), Digest(classification), idempotency, RequestId(request_id), Digest(request_digest), operation, _text(value["subject"], 512), purpose, sensitivity, retention_days, _text(value["created_at"], 24), _text(value["expires_at"], 24), prior, receipt, Digest(_text(value["receipt_digest"], 71)), _payload(operation, value["payload"]))
