"""Schema5-only additive remember wire surface."""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.mcp_write_models import JarvisReceiptModel, MemoryWriteRequestModel, RememberPayloadModel


class MemoryRememberRequestV3Model(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[3]
    body_profile: Literal["plain-text-v1"]
    candidate_id: str
    candidate_digest: str
    classification_digest: str
    idempotency_key: str
    request_id: str
    request_digest: str
    operation: Literal["remember"]
    subject: str
    purpose: Literal["personal_memory"]
    sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    retention_days: int
    created_at: str
    expires_at: str
    expected_prior: None
    receipt: JarvisReceiptModel
    receipt_digest: str
    payload: RememberPayloadModel


type MemoryRememberWriteRequest = Annotated[
    MemoryWriteRequestModel | MemoryEffectWriteRequestV2 | MemoryRememberRequestV3Model,
    Field(discriminator="schema_version"),
]
