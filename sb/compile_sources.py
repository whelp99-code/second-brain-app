"""Stable page identities and citation-preserving compile prompt inputs."""

import hashlib
from collections.abc import Sequence
from typing import Final

from sb.compile_models import CompileLedger
from sb.contracts import SourceCite, Unit

SID_LEN: Final = 8
ORIGIN_DIGEST_LEN: Final = 8
_MD_SUFFIX: Final = ".md"
DEFAULT_LINEAGE: Final = "builtin:.md\x1fnone\x1fv2\x1flocal-only"


def lineage_token(ledger: CompileLedger, units: Sequence[Unit]) -> str:
    parts: list[str] = []
    for unit in units:
        row = ledger.provenance_for_unit(unit.unit_id)
        if row is None:
            continue
        parts.append(
            f"{row.parser_version}\x1f{row.model_version}\x1f"
            + f"{row.normalizer_version}\x1f{row.profile_revision}"
        )
    return "\x1e".join(sorted(parts))


def uncertainty(ledger: CompileLedger, units: Sequence[Unit]) -> str | None:
    for unit in units:
        row = ledger.provenance_for_unit(unit.unit_id)
        if row is not None and row.partial_reason:
            return row.partial_reason
    return None


def with_uncertainty(body: str, reason: str | None) -> str:
    if not reason or f"uncertainty: {reason}" in body:
        return body
    return body.rstrip() + f"\n\nuncertainty: {reason}\n"


def group_by_page(units: Sequence[Unit]) -> list[tuple[str, tuple[Unit, ...]]]:
    grouped: dict[str, list[Unit]] = {}
    for unit in units:
        grouped.setdefault(page_id_for_origin(unit.origin), []).append(unit)
    pages: list[tuple[str, tuple[Unit, ...]]] = []
    for page_id in sorted(grouped):
        members = tuple(sorted(grouped[page_id], key=lambda item: item.unit_id))
        pages.append((page_id, members))
    return pages


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


def title_for_origin(origin: str) -> str:
    _, sep, rest = origin.partition(":")
    path = rest if sep else origin
    return path.rsplit("/", 1)[-1].removesuffix(_MD_SUFFIX)


def sources_for_units(units: Sequence[Unit]) -> list[SourceCite]:
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


def merge_sources(
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


def unit_block(units: Sequence[Unit]) -> str:
    lines: list[str] = []
    for unit in units:
        sid = unit.content_hash[:SID_LEN]
        lines.append(f"sid={sid} origin={unit.origin} span={unit.span}")
        lines.append(unit.text)
    return "\n".join(lines)
