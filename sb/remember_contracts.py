"""Additive plain-text remember contracts; the frozen V1 types stay unchanged."""

from dataclasses import dataclass
from typing import Literal

from sb.contracts import CandidateId, Digest, MemoryWriteRequestV1, RequestId, WriteOperation


@dataclass(frozen=True, slots=True)
class MemoryWriteRequestV3(MemoryWriteRequestV1):
    body_profile: Literal["plain-text-v1"] = "plain-text-v1"


@dataclass(frozen=True, slots=True)
class MemoryWriteResultV3:
    schema_version: Literal[3]
    kind: Literal["accepted"]
    state: Literal["pending"]
    candidate_id: CandidateId
    request_id: RequestId
    request_digest: Digest
    idempotency_key: str
    operation: WriteOperation
    accepted_at: str
    inbox_path: str
    request_file_digest: Digest
    replayed: bool


@dataclass(frozen=True, slots=True)
class MemoryWriteInboxEnvelopeV3:
    schema_version: Literal[3]
    state: Literal["pending"]
    accepted_at: str
    request: MemoryWriteRequestV3
