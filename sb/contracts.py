"""Frozen data contracts shared across the second-brain pipeline.

Stdlib only. No I/O, no third-party imports. See draft
`.omo/drafts/second-brain-rebuild.md` contracts K1-K5 for field meanings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
