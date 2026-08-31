"""Strict MCP boundary models for the V1 memory-write request."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict


class _ClosedModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class ExpectedPriorModel(_ClosedModel):
    source_id: str
    source_version: str
    source_digest: str


class JarvisReceiptModel(_ClosedModel):
    schema_version: Literal[1]
    receipt_id: str
    candidate_id: str
    candidate_digest: str
    classification_digest: str
    operation: Literal["remember", "correct", "forget", "export"]
    decision: Literal["auto_staged", "owner_confirmed"]
    principal_id: Literal["principal:owner"]
    issued_at: str
    expires_at: str


class RememberPayloadModel(_ClosedModel):
    content: str


class CorrectPayloadModel(_ClosedModel):
    content: str


class ForgetPayloadModel(_ClosedModel):
    disposition: Literal["owner_requested"]


class ExportPayloadModel(_ClosedModel):
    format: Literal["json"]
    scope: Literal["subject"]


type WritePayloadModel = (
    RememberPayloadModel | CorrectPayloadModel | ForgetPayloadModel | ExportPayloadModel
)


class MemoryWriteResultModel(_ClosedModel):
    schema_version: Literal[1]
    kind: Literal["accepted"]
    state: Literal["pending"]
    candidate_id: str
    request_id: str
    request_digest: str
    idempotency_key: str
    operation: Literal["remember", "correct", "forget", "export"]
    accepted_at: str
    inbox_path: str
    request_file_digest: str
    replayed: bool


class MemoryWriteRequestModel(_ClosedModel):
    schema_version: Literal[1]
    candidate_id: str
    candidate_digest: str
    classification_digest: str
    idempotency_key: str
    request_id: str
    request_digest: str
    operation: Literal["remember", "correct", "forget", "export"]
    subject: str
    purpose: Literal["personal_memory", "data_erasure", "data_portability"]
    sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    retention_days: int
    created_at: str
    expires_at: str
    expected_prior: ExpectedPriorModel | None
    receipt: JarvisReceiptModel
    receipt_digest: str
    payload: WritePayloadModel
