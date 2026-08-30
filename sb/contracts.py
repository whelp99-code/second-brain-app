"""Frozen data contracts shared across the second-brain pipeline.

Stdlib only. No I/O, no third-party imports. See draft
`.omo/drafts/second-brain-rebuild.md` contracts K1-K5 for field meanings.
"""
# pyright: reportAny=none, reportUnknownVariableType=none

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

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
class TerminalWorkSummaryV1:
    """Verified, bounded terminal closeout suitable for durable memory."""

    memory_candidate_id: str
    jarvis_closeout_id: str
    jarvis_receipt_digest: str
    project_id: str
    host_scope: tuple[str, ...]
    terminal_count: int
    started_at: str
    finished_at: str
    outcome: str
    verified: bool
    purpose: str
    work_performed: tuple[str, ...] = ()
    verified_results: tuple[str, ...] = ()
    failures: tuple[dict[str, str], ...] = ()
    artifacts: tuple[str, ...] = ()
    commits: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    improvements: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    schema: str = "terminal-work-summary-v1"

    def __post_init__(self) -> None:
        if self.schema != "terminal-work-summary-v1":
            raise ValueError(f"unsupported summary schema: {self.schema}")
        for name in (
            "memory_candidate_id",
            "jarvis_closeout_id",
            "jarvis_receipt_digest",
            "project_id",
            "purpose",
            "started_at",
            "finished_at",
            "outcome",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.terminal_count < 0:
            raise ValueError("terminal_count must be non-negative")
        if not self.verified:
            raise ValueError("only verified closeouts can become durable memory")
        if not self.jarvis_receipt_digest.startswith("sha256:"):
            raise ValueError("jarvis_receipt_digest must be sha256:<hex>")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TerminalWorkSummaryV1:
        def text(name: str) -> str:
            raw = value.get(name)
            if not isinstance(raw, str):
                raise TypeError(f"{name} must be a string")
            return raw

        def texts(name: str) -> tuple[str, ...]:
            raw = value.get(name, ())
            if not isinstance(raw, (list, tuple)):
                raise TypeError(f"{name} must be a list")
            if not all(isinstance(item, str) for item in raw):
                raise TypeError(f"{name} must contain strings")
            return tuple(cast(str, item) for item in raw)

        raw_failures = value.get("failures", ())
        failures: tuple[dict[str, str], ...]
        if not isinstance(raw_failures, (list, tuple)):
            raise TypeError("failures must be a list")
        parsed_failures: list[dict[str, str]] = []
        for item in raw_failures:
            if not isinstance(item, Mapping) or not all(
                isinstance(key, str) and isinstance(inner, str) for key, inner in item.items()
            ):
                raise TypeError("failures must contain string maps")
            parsed_failures.append(dict(cast(Mapping[str, str], item)))
        failures = tuple(parsed_failures)
        terminals = value.get("terminal_count", 0)
        verified = value.get("verified", False)
        if not isinstance(terminals, int) or isinstance(terminals, bool):
            raise TypeError("terminal_count must be an integer")
        if not isinstance(verified, bool):
            raise TypeError("verified must be a boolean")
        return cls(
            memory_candidate_id=text("memory_candidate_id"),
            jarvis_closeout_id=text("jarvis_closeout_id"),
            jarvis_receipt_digest=text("jarvis_receipt_digest"),
            project_id=text("project_id"),
            host_scope=texts("host_scope"),
            terminal_count=terminals,
            started_at=text("started_at"),
            finished_at=text("finished_at"),
            outcome=text("outcome"),
            verified=verified,
            purpose=text("purpose"),
            work_performed=texts("work_performed"),
            verified_results=texts("verified_results"),
            failures=failures,
            artifacts=texts("artifacts"),
            commits=texts("commits"),
            issues=texts("issues"),
            improvements=texts("improvements"),
            next_actions=texts("next_actions"),
            source_refs=texts("source_refs"),
            schema=text("schema") if "schema" in value else "terminal-work-summary-v1",
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "memory_candidate_id": self.memory_candidate_id,
            "jarvis_closeout_id": self.jarvis_closeout_id,
            "jarvis_receipt_digest": self.jarvis_receipt_digest,
            "project_id": self.project_id,
            "host_scope": list(self.host_scope),
            "terminal_count": self.terminal_count,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outcome": self.outcome,
            "verified": self.verified,
            "purpose": self.purpose,
            "work_performed": list(self.work_performed),
            "verified_results": list(self.verified_results),
            "failures": [dict(item) for item in self.failures],
            "artifacts": list(self.artifacts),
            "commits": list(self.commits),
            "issues": list(self.issues),
            "improvements": list(self.improvements),
            "next_actions": list(self.next_actions),
            "source_refs": list(self.source_refs),
        }

    def render_markdown(self) -> str:
        lines = [
            f"# Terminal work: {self.project_id}",
            "",
            f"- Purpose: {self.purpose}",
            f"- Outcome: {self.outcome}",
            f"- Verified: {str(self.verified).lower()}",
            f"- Closeout: `{self.jarvis_closeout_id}`",
            f"- Candidate: `{self.memory_candidate_id}`",
            f"- Receipt: `{self.jarvis_receipt_digest}`",
            "",
        ]
        sections = (
            ("Work performed", self.work_performed),
            ("Verified results", self.verified_results),
            ("Failures", tuple(_failure_text(item) for item in self.failures)),
            ("Artifacts", self.artifacts),
            ("Commits", self.commits),
            ("Issues", self.issues),
            ("Improvements", self.improvements),
            ("Next actions", self.next_actions),
            ("Source refs", self.source_refs),
        )
        for title, entries in sections:
            if entries:
                lines.append(f"## {title}")
                lines.extend(f"- {entry}" for entry in entries)
                lines.append("")
        return "\n".join(lines).rstrip()


def _failure_text(item: Mapping[str, str]) -> str:
    return "; ".join(f"{key}: {item[key]}" for key in sorted(item))


def canonical_json(value: object) -> bytes:
    """Serialize a JSON-compatible value deterministically for contract digests."""
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
