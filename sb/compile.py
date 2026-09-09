"""Derivation-gated cited page compiler. No vault I/O, no normalize import."""

from __future__ import annotations

import hashlib
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final, Protocol

from sb.config import Config
from sb.contracts import PageSpec, SourceCite, Unit
from sb.llm import LLMClient, LLMUnavailable
from sb.security import protect_units
from sb.store import Derivation, DerivationOutput, DerivStatus, deriv_key

COMPILE_STAGE: Final = "compile"
COMPILE_RUN_ID: Final = "compile"
CAPPED_PAGE_ID: Final = "CAPPED"
CAPPED_STATUS: Final = "CAPPED"
SID_LEN: Final = 8
ORIGIN_DIGEST_LEN: Final = 8
_MD_SUFFIX: Final = ".md"


class CompileLedger(Protocol):
    """Ledger derivation surface used by compile. Matches sb.store.ledger.Ledger."""

    def get_derivation(self, key: str) -> Derivation | None: ...

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None: ...

    def mark_running(self, key: str, run_id: str) -> None: ...

    def mark_done(self, key: str, output: DerivationOutput) -> None: ...

    def mark_failed(self, key: str, error: str) -> None: ...

    def requeue_failed(self, key: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class PendingCompile:
    """A generated page whose derivation is finalized only after durable vault write."""

    page: PageSpec
    key: str
    output: DerivationOutput
    input_sources: tuple[tuple[str, str], ...] = ()
    untracked_context: bool = True


class _BodyCache:
    """Bodies belong to one live ledger instance, never a recycled object id."""

    def __init__(self) -> None:
        self._data: dict[int, tuple[weakref.ReferenceType[CompileLedger], dict[str, str]]] = {}

    def get(self, ledger: CompileLedger, page_id: str) -> str:
        entry = self._data.get(id(ledger))
        if entry is None or entry[0]() is not ledger:
            return ""
        return entry[1].get(page_id, "")

    def put(self, ledger: CompileLedger, page_id: str, body: str) -> None:
        key = id(ledger)
        entry = self._data.get(key)
        if entry is None or entry[0]() is not ledger:
            def discard(reference: weakref.ReferenceType[CompileLedger]) -> None:
                current = self._data.get(key)
                if current is not None and current[0] is reference:
                    del self._data[key]

            try:
                reference = weakref.ref(ledger, discard)
            except TypeError:
                # Non-weak-referenceable implementations can supply explicit
                # existing_bodies/pages; retaining them globally is unsafe.
                return
            entry = (reference, {})
            self._data[key] = entry
        entry[1][page_id] = body


_BODIES: Final = _BodyCache()


def compile_pages(
    units: list[Unit],
    ledger: CompileLedger,
    llm: LLMClient,
    config: Config,
    *,
    existing_bodies: Mapping[str, str] | None = None,
    existing_pages: Mapping[str, PageSpec] | None = None,
) -> list[PageSpec]:
    """Compile one cited wiki page per source document.

    Skips a page when its deriv_key is done. Stops at max_llm_calls_compile
    and appends a CAPPED marker PageSpec so the pipeline can report partial.
    """
    pending, capped = compile_pending(
        units,
        ledger,
        llm,
        config,
        existing_bodies=existing_bodies,
        existing_pages=existing_pages,
    )
    for item in pending:
        ledger.mark_done(item.key, item.output)
    pages = [item.page for item in pending]
    if capped:
        pages.append(_capped_marker())
    return pages


def compile_pending(
    units: list[Unit],
    ledger: CompileLedger,
    llm: LLMClient,
    config: Config,
    *,
    existing_bodies: Mapping[str, str] | None = None,
    existing_pages: Mapping[str, PageSpec] | None = None,
    on_page: Callable[[PendingCompile], None] | None = None,
    on_error: Callable[[LLMUnavailable], None] | None = None,
) -> tuple[list[PendingCompile], bool]:
    """Generate pages but leave successful derivations running until the caller commits them."""
    units = protect_units(units, config)
    cap = config.caps["max_llm_calls_compile"]
    prompt_version = config.llm.prompt_version
    model_id = config.llm.model_id
    template = _prompt_template()
    ctx = _CompileCtx(
        ledger,
        llm,
        template,
        existing_bodies or {},
        existing_pages or {},
        prompt_version,
        model_id,
    )
    pending: list[PendingCompile] = []
    used = 0
    remaining = False
    for page_id, grouped in _group_by_page(units):
        key = deriv_key(
            [unit.unit_id for unit in grouped],
            COMPILE_STAGE,
            prompt_version,
            model_id,
        )
        if not _prepare_compile(ledger, key):
            continue
        if used >= cap:
            remaining = True
            break
        try:
            item = _compile_one(_PageJob(page_id, key, grouped), ctx)
            pending.append(item)
            if on_page is not None:
                on_page(item)
        except LLMUnavailable as exc:
            if on_error is None:
                raise
            on_error(exc)
        used += 1
    return pending, remaining


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
    existing_bodies: Mapping[str, str]
    existing_pages: Mapping[str, PageSpec]
    prompt_version: str
    model_id: str


def _compile_one(job: _PageJob, ctx: _CompileCtx) -> PendingCompile:
    title = _title(job.units[0].origin)
    previous = ctx.existing_pages.get(job.page_id)
    existing = (
        previous.body_md
        if previous is not None
        else ctx.existing_bodies.get(job.page_id, _BODIES.get(ctx.ledger, job.page_id))
    )
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
    sources = _sources(job.units)
    page = PageSpec(
        page_id=job.page_id,
        title=title,
        body_md=body,
        sources=_merge_sources(() if previous is None else previous.sources, sources),
        status="active",
        prompt_version=ctx.prompt_version,
        model_id=ctx.model_id,
        derivation_key=job.key,
    )
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return PendingCompile(page, job.key, DerivationOutput(digest, f"wiki/{job.page_id}.md"),
        tuple(sorted({(unit.origin, unit.content_hash) for unit in job.units})),
        bool(existing) and previous is None)


def _prepare_compile(ledger: CompileLedger, key: str) -> bool:
    row = ledger.get_derivation(key)
    if row is not None and row.status == DerivStatus.FAILED.value:
        _ = ledger.requeue_failed(key)
        return True
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
    return page_id_for_origin(origin)


def page_id_for_origin(origin: str) -> str:
    """Return the stable wiki page id used for one source origin."""
    trimmed = origin.removesuffix(_MD_SUFFIX)
    chars: list[str] = []
    for char in trimmed:
        chars.append(char.lower() if char.isalnum() else "-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    digest = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:ORIGIN_DIGEST_LEN]
    return f"{slug.strip('-')}-{digest}"


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


def _merge_sources(
    existing: Sequence[SourceCite], current: Sequence[SourceCite]
) -> list[SourceCite]:
    merged: dict[tuple[str, str, str], SourceCite] = {}
    order: list[tuple[str, str, str]] = []
    for cite in (*existing, *current):
        key = (cite.sid, cite.origin, cite.hash)
        stored = merged.get(key)
        if stored is None:
            order.append(key)
            merged[key] = SourceCite(cite.sid, cite.origin, cite.hash, list(cite.spans))
            continue
        for span in cite.spans:
            if span not in stored.spans:
                stored.spans.append(span)
    return [merged[key] for key in order]


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


def compile_state_report(
    config: Config,
    *,
    dry_run: bool = False,
    project: bool = False,
) -> dict[str, object]:
    """Read the knowledge registry. Never write the vault. Never create status rows."""
    from pathlib import Path

    from sb.knowledge_registry import KnowledgeRegistry
    from sb.search import SearchIndex, resolve_registry_path

    root = Path(config.vault_root)
    explicit = Path(config.knowledge_registry) if "knowledge_registry" in config.raw else None
    path = resolve_registry_path(root, explicit)
    registry = KnowledgeRegistry(path)
    states = registry.read_snapshot()
    counts: dict[str, int] = {}
    for state in states:
        counts[state.knowledge_status] = counts.get(state.knowledge_status, 0) + 1
    projected = False
    if project and not dry_run:
        SearchIndex(vault_root=root, registry_path=path).project()
        projected = True
    return {
        "dry_run": dry_run,
        "state_report": True,
        "vault_written": False,
        "status_created": False,
        "projected": projected,
        "projection_mode": "read-time" if (root / "generation.json").is_file() else "index",
        "registry_path": str(path),
        "pages": [state.as_dict() for state in states],
        "counts": counts,
    }
