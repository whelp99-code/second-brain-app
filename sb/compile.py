"""Derivation-gated cited page compiler. No vault I/O, no normalize import."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from importlib.resources import files
from typing import Final

from sb.compile_execution import cached_body
from sb.compile_execution import compile_one as _compile_one
from sb.compile_execution import compile_without_llm as _compile_without_llm
from sb.compile_models import COMPILE_RUN_ID, COMPILE_STAGE, CompileLedger, PendingCompile
from sb.compile_models import CompileContext as _CompileCtx
from sb.compile_models import PageJob as _PageJob
from sb.compile_sources import (
    DEFAULT_LINEAGE,
    ORIGIN_DIGEST_LEN,
    SID_LEN,
    lineage_token,
    page_id_for_origin,
)
from sb.compile_sources import group_by_page as _group_by_page
from sb.compile_state import compile_state_report
from sb.config import Config
from sb.contracts import PageSpec, Unit
from sb.llm import LLMClient, LLMUnavailable
from sb.security import protect_compile_egress, protect_units, source_llm_policy
from sb.store import DerivStatus, deriv_key

__all__ = [
    "CAPPED_PAGE_ID",
    "CAPPED_STATUS",
    "COMPILE_RUN_ID",
    "COMPILE_STAGE",
    "ORIGIN_DIGEST_LEN",
    "SID_LEN",
    "CompileLedger",
    "PendingCompile",
    "_CompileCtx",
    "_PageJob",
    "_compile_one",
    "compile_page_key",
    "compile_pages",
    "compile_pending",
    "compile_state_report",
    "page_id_for_origin",
]

CAPPED_PAGE_ID: Final = "CAPPED"
CAPPED_STATUS: Final = "CAPPED"




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
        key = compile_page_key(
            page_id,
            [unit.unit_id for unit in grouped],
            prompt_version,
            model_id,
            lineage=lineage_token(ledger, grouped),
        )
        row = ledger.get_derivation(key)
        if (row is not None and row.status in {DerivStatus.FAILED.value, DerivStatus.PENDING.value}
                and row.attempts >= config.caps["max_derivation_attempts"]):
            remaining = True
            continue
        if not _prepare_compile(ledger, key, config.caps["max_derivation_attempts"]):
            continue
        policies = {
            source_llm_policy(config, unit.origin.partition(":")[0] or "unknown")
            for unit in grouped
        }
        job = _PageJob(page_id, key, grouped)
        try:
            if "deny" in policies:
                item = _compile_without_llm(job, ctx)
            else:
                if used >= cap:
                    remaining = True
                    break
                protected = protect_units(list(grouped), config, ledger=ledger)
                previous = ctx.existing_pages.get(page_id)
                egress = protect_compile_egress(
                    llm, grouped, config, ledger, previous=previous,
                    untracked_context=previous is None and bool(
                        ctx.existing_bodies.get(page_id, cached_body(ledger, page_id))
                    ),
                )
                item = _compile_one(_PageJob(page_id, key, tuple(protected)), replace(ctx, llm=egress))
                used += 1
            pending.append(item)
            if on_page is not None:
                on_page(item)
        except LLMUnavailable as exc:
            if "deny" not in policies:
                used += 1
            if on_error is None:
                raise
            on_error(exc)
            if used >= cap:
                remaining = True
                break
    return pending, remaining


def compile_page_key(
    page_id: str,
    unit_ids: Sequence[str],
    prompt_version: str,
    model_id: str,
    lineage: str = "",
) -> str:
    """Bind parser, model, normalization, and profile revisions to a derivation."""
    identity = ["compile-page-v1:" + page_id, *unit_ids, "lineage:" + (lineage or DEFAULT_LINEAGE)]
    return deriv_key(identity, COMPILE_STAGE, prompt_version, model_id)


def _prepare_compile(ledger: CompileLedger, key: str, max_attempts: int) -> bool:
    row = ledger.get_derivation(key)
    if row is not None and row.status == DerivStatus.FAILED.value:
        return ledger.requeue_failed(key, max_attempts=max_attempts)
    return row is None or row.status == DerivStatus.PENDING.value



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
