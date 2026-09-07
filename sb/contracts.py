"""Frozen data contracts shared across the second-brain pipeline.

Stdlib only. No I/O, no third-party imports. See draft
`.omo/drafts/second-brain-rebuild.md` contracts K1-K5 for field meanings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, NewType


class WriteOperation(StrEnum):
    REMEMBER = "remember"
    CORRECT = "correct"
    FORGET = "forget"
    EXPORT = "export"
CandidateId = NewType("CandidateId", str)
RequestId = NewType("RequestId", str)
Digest = NewType("Digest", str)


@dataclass(frozen=True, slots=True)
class ExpectedPriorV1:
    source_id: str
    source_version: str
    source_digest: Digest


@dataclass(frozen=True, slots=True)
class JarvisReceiptV1:
    receipt_id: str
    candidate_id: CandidateId
    candidate_digest: Digest
    classification_digest: Digest
    operation: WriteOperation
    decision: Literal["auto_staged", "owner_confirmed"]
    principal_id: Literal["principal:owner"]
    issued_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class MemoryWriteRequestV1:
    candidate_id: CandidateId
    candidate_digest: Digest
    classification_digest: Digest
    idempotency_key: str
    request_id: RequestId
    request_digest: Digest
    operation: WriteOperation
    subject: str
    purpose: str
    sensitivity: str
    retention_days: int
    created_at: str
    expires_at: str
    expected_prior: ExpectedPriorV1 | None
    receipt: JarvisReceiptV1
    receipt_digest: Digest
    payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class MemoryWriteResultV1:
    schema_version: Literal[1]
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
class MemoryWriteErrorV1:
    schema_version: Literal[1]
    kind: Literal["error"]
    code: str
    retryable: Literal[False]


@dataclass(frozen=True, slots=True)
class MemoryWriteInboxEnvelopeV1:
    schema_version: Literal[1]
    state: Literal["pending"]
    accepted_at: str
    request: MemoryWriteRequestV1

VALID_CONFLICT_RELATIONS = frozenset({"supports", "contradicts", "unrelated", "supersedes"})


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Identifies a single item as scanned from a source adapter."""

    source_id: str
    source_uri: str
    source_version: str


@dataclass(frozen=True, slots=True)
class Blob:
    """A content-addressed blob stored in the CAS raw store."""

    hash: str
    size: int


@dataclass(frozen=True, slots=True)
class Unit:
    """A normalized, chunked slice of text ready for compile/conflict stages."""

    unit_id: str
    content_hash: str
    span: str
    text: str
    origin: str


@dataclass(frozen=True, slots=True)
class SourceCite:
    """One entry in a wiki page's frontmatter `sources` list (K1)."""

    sid: str
    origin: str
    hash: str
    spans: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PageSpec:
    """A wiki page ready to be rendered and written by sb.vault."""

    page_id: str
    title: str
    body_md: str
    sources: list[SourceCite]
    status: str
    prompt_version: str | None = None
    model_id: str | None = None
    derivation_key: str | None = None


@dataclass(frozen=True, slots=True)
class ConflictVerdict:
    """Stage-B contradiction-detection verdict (K3)."""

    relation: str
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        if self.relation not in VALID_CONFLICT_RELATIONS:
            raise ValueError(
                f"invalid relation {self.relation!r}; must be one of "
                + f"{sorted(VALID_CONFLICT_RELATIONS)}"
            )


@dataclass(frozen=True, slots=True)
class BriefingInputs:
    """Frozen inputs collected by sb.pipeline and handed to sb.briefing (K4)."""

    yesterday_items: tuple[str, ...]
    open_conflict_pages: tuple[str, ...]
    stale_pages: tuple[str, ...]
    upcoming_items: tuple[str, ...]
    last_brief: str | None
    previous_run_status: str | None
