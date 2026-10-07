"""Execute one page job against local or LLM policy, retaining ledger-owned context."""

import hashlib
from typing import Final

from sb.compile_cache import BodyCache
from sb.compile_models import (
    COMPILE_RUN_ID,
    COMPILE_STAGE,
    CompileContext,
    CompileLedger,
    PageJob,
    PendingCompile,
)
from sb.compile_sources import (
    merge_sources,
    sources_for_units,
    title_for_origin,
    uncertainty,
    unit_block,
    with_uncertainty,
)
from sb.contracts import PageSpec
from sb.llm import LLMUnavailable
from sb.security import SecurityPolicyError
from sb.store import DerivationOutput

_BODIES: Final = BodyCache[CompileLedger]()


def cached_body(ledger: CompileLedger, page_id: str) -> str:
    return _BODIES.get(ledger, page_id)


def compile_without_llm(job: PageJob, ctx: CompileContext) -> PendingCompile:
    title = title_for_origin(job.units[0].origin)
    previous = ctx.existing_pages.get(job.page_id)
    body = with_uncertainty(
        "\n\n".join(unit.text for unit in job.units), uncertainty(ctx.ledger, job.units)
    )
    ctx.ledger.ensure_derivation(job.key, COMPILE_STAGE, COMPILE_RUN_ID)
    ctx.ledger.mark_running(job.key, COMPILE_RUN_ID)
    _BODIES.put(ctx.ledger, job.page_id, body)
    sources = sources_for_units(job.units)
    page = PageSpec(
        page_id=job.page_id,
        title=title,
        body_md=body,
        sources=merge_sources(() if previous is None else previous.sources, sources),
        status="active",
        prompt_version=ctx.prompt_version,
        model_id="local-deny",
        derivation_key=job.key,
    )
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return PendingCompile(
        page,
        job.key,
        DerivationOutput(digest, f"wiki/{job.page_id}.md"),
        tuple(sorted({(unit.origin, unit.content_hash) for unit in job.units})),
        bool(previous is None),
    )


def compile_one(job: PageJob, ctx: CompileContext) -> PendingCompile:
    title = title_for_origin(job.units[0].origin)
    previous = ctx.existing_pages.get(job.page_id)
    existing = (
        previous.body_md
        if previous is not None
        else ctx.existing_bodies.get(job.page_id, _BODIES.get(ctx.ledger, job.page_id))
    )
    prompt = (
        ctx.template.replace("{units_with_sids}", unit_block(job.units))
        .replace("{existing_page_body_or_empty}", existing)
        .replace("{title}", title)
    )
    ctx.ledger.ensure_derivation(job.key, COMPILE_STAGE, COMPILE_RUN_ID)
    ctx.ledger.mark_running(job.key, COMPILE_RUN_ID)
    try:
        body = ctx.llm.generate(prompt)
    except (LLMUnavailable, SecurityPolicyError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) != "SOURCE_ACCESS_RECLASSIFICATION_REQUIRED":
            raise
        ctx.ledger.mark_failed(job.key, str(exc))
        raise
    body = with_uncertainty(body, uncertainty(ctx.ledger, job.units))
    _BODIES.put(ctx.ledger, job.page_id, body)
    sources = sources_for_units(job.units)
    page = PageSpec(
        page_id=job.page_id,
        title=title,
        body_md=body,
        sources=merge_sources(() if previous is None else previous.sources, sources),
        status="active",
        prompt_version=ctx.prompt_version,
        model_id=ctx.model_id,
        derivation_key=job.key,
    )
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return PendingCompile(page, job.key, DerivationOutput(digest, f"wiki/{job.page_id}.md"),
        tuple(sorted({(unit.origin, unit.content_hash) for unit in job.units})),
        bool(existing) and previous is None)
