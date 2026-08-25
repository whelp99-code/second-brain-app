"""Derivation-gated cited page compiler. No vault I/O, no normalize import."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final, Protocol

from sb.config import Config
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import LLMClient, LLMUnavailable
from sb.store import Derivation, DerivationOutput, DerivStatus, deriv_key

COMPILE_STAGE: Final = "compile"
COMPILE_RUN_ID: Final = "compile"
CAPPED_PAGE_ID: Final = "CAPPED"
CAPPED_STATUS: Final = "CAPPED"
SID_LEN: Final = 8
_MD_SUFFIX: Final = ".md"


class CompileLedger(Protocol):
    """Ledger derivation surface used by compile. Matches sb.store.ledger.Ledger."""

    def get_derivation(self, key: str) -> Derivation | None: ...

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None: ...

    def mark_running(self, key: str, run_id: str) -> None: ...

    def mark_done(self, key: str, output: DerivationOutput) -> None: ...

    def mark_failed(self, key: str, error: str) -> None: ...


class _BodyCache:
    """Last compiled bodies keyed by ledger id. Ledger has no body column."""

    def __init__(self) -> None:
        self._data: dict[int, dict[str, str]] = {}

    def get(self, ledger: CompileLedger, page_id: str) -> str:
        stored = self._data.get(id(ledger), {}).get(page_id)
        return "" if stored is None else stored

    def put(self, ledger: CompileLedger, page_id: str, body: str) -> None:
        bucket = self._data.get(id(ledger))
        if bucket is None:
            bucket = {}
            self._data[id(ledger)] = bucket
        bucket[page_id] = body


_BODIES: Final = _BodyCache()


def compile_pages(
    units: list[Unit],
    ledger: CompileLedger,
    llm: LLMClient,
    config: Config,
) -> list[PageSpec]:
    """Compile one cited wiki page per source document.

    Skips a page when its deriv_key is done. Stops at max_llm_calls_compile
    and appends a CAPPED marker PageSpec so the pipeline can report partial.
    """
    cap = config.caps["max_llm_calls_compile"]
    prompt_version = config.llm.prompt_version
    model_id = config.llm.model_id
    template = _prompt_template()
    ctx = _CompileCtx(ledger, llm, template)
    pages: list[PageSpec] = []
    used = 0
    remaining = False
    for page_id, grouped in _group_by_page(units):
        key = deriv_key(
            [unit.unit_id for unit in grouped],
            COMPILE_STAGE,
            prompt_version,
            model_id,
        )
        if not _needs_compile(ledger, key):
            continue
        if used >= cap:
            remaining = True
            break
        pages.append(_compile_one(_PageJob(page_id, key, grouped), ctx))
        used += 1
    if remaining:
        pages.append(_capped_marker())
    return pages


@dataclass(frozen=True, slots=True)
class _PageJob:
    page_id: str
    key: str
    units: tuple[Unit, ...]


@dataclass(frozen=True, slots=True)
class _CompileCtx:
    ledger: CompileLedger
    llm: LLMClient
    template: str


def _compile_one(job: _PageJob, ctx: _CompileCtx) -> PageSpec:
    title = _title(job.units[0].origin)
    existing = _BODIES.get(ctx.ledger, job.page_id)
    prompt = (
        ctx.template.replace("{units_with_sids}", _unit_block(job.units))
        .replace("{existing_page_body_or_empty}", existing)
        .replace("{title}", title)
    )
    ctx.ledger.ensure_derivation(job.key, COMPILE_STAGE, COMPILE_RUN_ID)
    ctx.ledger.mark_running(job.key, COMPILE_RUN_ID)
    try:
        body = ctx.llm.generate(prompt)
    except LLMUnavailable as exc:
        ctx.ledger.mark_failed(job.key, str(exc))
        raise
    _BODIES.put(ctx.ledger, job.page_id, body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    ctx.ledger.mark_done(job.key, DerivationOutput(digest, f"wiki/{job.page_id}.md"))
    return PageSpec(
        page_id=job.page_id,
        title=title,
        body_md=body,
        sources=_sources(job.units),
        status="active",
    )


def _needs_compile(ledger: CompileLedger, key: str) -> bool:
    row = ledger.get_derivation(key)
    return row is None or row.status == DerivStatus.PENDING.value


def _group_by_page(units: Sequence[Unit]) -> list[tuple[str, tuple[Unit, ...]]]:
    grouped: dict[str, list[Unit]] = {}
    for unit in units:
        grouped.setdefault(_page_id(unit.origin), []).append(unit)
    pages: list[tuple[str, tuple[Unit, ...]]] = []
    for page_id in sorted(grouped):
        members = tuple(sorted(grouped[page_id], key=lambda item: item.unit_id))
        pages.append((page_id, members))
    return pages


def _page_id(origin: str) -> str:
    trimmed = origin.removesuffix(_MD_SUFFIX)
    chars: list[str] = []
    for char in trimmed:
        chars.append(char.lower() if char.isalnum() else "-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _title(origin: str) -> str:
    _, sep, rest = origin.partition(":")
    path = rest if sep else origin
    return path.rsplit("/", 1)[-1].removesuffix(_MD_SUFFIX)


def _sources(units: Sequence[Unit]) -> list[SourceCite]:
    order: list[str] = []
    spans: dict[str, list[str]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for unit in units:
        sid = unit.content_hash[:SID_LEN]
        if sid not in meta:
            order.append(sid)
            meta[sid] = (unit.origin, unit.content_hash)
            spans[sid] = []
        spans[sid].append(unit.span)
    return [
        SourceCite(sid=sid, origin=meta[sid][0], hash=meta[sid][1], spans=list(spans[sid]))
        for sid in order
    ]


def _unit_block(units: Sequence[Unit]) -> str:
    lines: list[str] = []
    for unit in units:
        sid = unit.content_hash[:SID_LEN]
        lines.append(f"sid={sid} origin={unit.origin} span={unit.span}")
        lines.append(unit.text)
    return "\n".join(lines)


def _prompt_template() -> str:
    return (files("sb") / "prompts" / "compile.md").read_text(encoding="utf-8")


def _capped_marker() -> PageSpec:
    return PageSpec(
        page_id=CAPPED_PAGE_ID,
        title=CAPPED_STATUS,
        body_md=CAPPED_STATUS,
        sources=[],
        status=CAPPED_STATUS,
    )
