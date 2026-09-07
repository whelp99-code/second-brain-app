"""Provider-derived schema-4 memory record identities from one pinned generation."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

from sb.effect_values import JsonObject, canonical_bytes, digest, format_instant
from sb.page_ids import git_rel
from sb.targets import GenerationIdentityV1, ResolvedMemoryTargetV1

_RECORD_DOMAIN: Final = b"second-brain/memory-record/v1\0"
_CITATION: Final = re.compile(r"\[\^([0-9a-f]{8,64})\]")
_DEFINITION: Final = re.compile(r"^\[\^([0-9a-f]{8,64})\]:\s*(\S.*)$")
_MAX_RECORDS: Final = 64


class MemoryRecordError(ValueError):
    """A committed page cannot provide an unambiguous schema-4 record."""


@dataclass(frozen=True, slots=True)
class MemoryRecordV1:
    schema_version: Literal[1]
    record_id: str
    record_digest: str
    sid: str
    record_text: str
    record_text_digest: str
    citation_span_start: int
    citation_span_end: int
    source_identity_full: str
    content_identity_full: str
    citation_identity_full: str
    sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    source_owner_class: Literal["provider_owned", "external_read_only"]
    source_owner_id_digest: str
    origin_label: str
    valid_from: str
    valid_until: str

    def as_dict(self) -> JsonObject:
        return asdict(self)


def _git(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(["git", *arguments], cwd=root, check=False, capture_output=True)
    if result.returncode != 0:
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record_digest(value: JsonObject) -> str:
    return "sha256:" + _hash(_RECORD_DOMAIN + canonical_bytes(value))


def _frontmatter(raw: bytes) -> tuple[dict[str, str], int]:
    if not raw.startswith(b"---"):
        return {}, 0
    boundary = raw.find(b"\n---", 3)
    if boundary < 0:
        return {}, 0
    block = raw[3:boundary].decode("utf-8").lstrip("\n")
    values: dict[str, str] = {}
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip():
            values[key.strip()] = value.strip().strip("'\"")
    body_start = boundary + 4
    while body_start < len(raw) and raw[body_start] == 0x0A:
        body_start += 1
    return values, body_start


def _sensitivity(value: str | None) -> Literal["public", "personal", "sensitive", "restricted"]:
    allowed: dict[str | None, Literal["public", "personal", "sensitive", "restricted"]] = {
        "public": "public", "personal": "personal", "sensitive": "sensitive",
        "restricted": "restricted", None: "personal", "": "personal",
    }
    selected = allowed.get(value)
    if selected is None:
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    return selected


def _validity(updated: str | None, observed: datetime) -> tuple[str, str]:
    if updated is None:
        start = observed
    else:
        try:
            start = datetime.fromisoformat(f"{updated}T00:00:00+00:00")
        except ValueError as exc:
            raise MemoryRecordError("EFFECT_TARGET_INVALID") from exc
    return format_instant(start), format_instant(start + timedelta(days=1))


def records_for_page(
    root: Path,
    page_id: str,
    generation: GenerationIdentityV1,
    observed: datetime | None = None,
) -> tuple[MemoryRecordV1, ...]:
    """Derive closed records from exact committed statement bytes under one generation pin."""
    rel = git_rel(page_id)
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if head != generation.vault_head or tree != generation.vault_tree:
        raise MemoryRecordError("MEMORY_GENERATION_CHANGED")
    raw = _git(root, "cat-file", "blob", f"HEAD:{rel}", binary=True)
    if not isinstance(raw, bytes):
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    metadata, body_start = _frontmatter(raw)
    body = raw[body_start:].decode("utf-8")
    definitions: dict[str, str] = {}
    for line in body.splitlines():
        matched = _DEFINITION.fullmatch(line.strip())
        if matched is not None:
            definitions[matched.group(1)] = matched.group(2)
    sensitivity = _sensitivity(metadata.get("sensitivity"))
    valid_from, valid_until = _validity(metadata.get("updated"), observed or datetime.now(UTC))
    rows: list[MemoryRecordV1] = []
    search_offset = body_start
    previous_statement: tuple[str, int] | None = None
    for line in body.splitlines(keepends=True):
        encoded = line.encode("utf-8")
        line_start = raw.find(encoded, search_offset)
        search_offset = line_start + len(encoded)
        stripped = line.rstrip("\r\n")
        markers = tuple(_CITATION.finditer(stripped))
        if not markers:
            if stripped and not stripped.startswith("#") and _DEFINITION.fullmatch(stripped) is None:
                previous_statement = (stripped, line_start)
            continue
        if stripped.lstrip().startswith("[^" + markers[0].group(1) + "]:"):
            continue
        inline_text = stripped[: markers[0].start()].strip()
        if inline_text:
            statement = (inline_text, line_start)
        elif previous_statement is not None:
            statement = previous_statement
        else:
            raise MemoryRecordError("EFFECT_TARGET_INVALID")
        previous_end = 0
        for marker in markers:
            fragment = stripped[previous_end:marker.start()].strip()
            if fragment:
                prefix_bytes = stripped[:previous_end].encode("utf-8")
                statement = (fragment, line_start + len(prefix_bytes))
            previous_end = marker.end()
            sid = marker.group(1)
            origin = definitions.get(sid)
            if origin is None:
                raise MemoryRecordError("EFFECT_TARGET_INVALID")
            text, statement_start = statement
            text_bytes = text.encode("utf-8")
            span = raw.find(text_bytes, statement_start, max(line_start + len(encoded), statement_start + len(text_bytes) + 1))
            if span < 0:
                raise MemoryRecordError("EFFECT_TARGET_INVALID")
            source_identity = _hash(origin.encode("utf-8"))
            content_identity = _hash(text_bytes)
            citation_identity = _hash(
                page_id.encode("utf-8")
                + b"\0"
                + sid.encode("ascii")
                + b"\0"
                + str(span).encode("ascii")
                + b":"
                + str(span + len(text_bytes)).encode("ascii")
            )
            owner_class: Literal["provider_owned", "external_read_only"] = (
                "external_read_only" if origin.startswith("external:") else "provider_owned"
            )
            record_text_digest = "sha256:" + content_identity
            owner_digest = "sha256:" + _hash(("owner\0" + source_identity).encode())
            origin_label = "External source" if owner_class == "external_read_only" else "Second Brain"
            core: JsonObject = {
                "schema_version": 1, "sid": sid, "record_text": text,
                "record_text_digest": record_text_digest, "citation_span_start": span,
                "citation_span_end": span + len(text_bytes), "source_identity_full": source_identity,
                "content_identity_full": content_identity, "citation_identity_full": citation_identity,
                "sensitivity": sensitivity, "source_owner_class": owner_class,
                "source_owner_id_digest": owner_digest, "origin_label": origin_label,
                "valid_from": valid_from, "valid_until": valid_until,
            }
            record_digest = _record_digest(core)
            rows.append(MemoryRecordV1(
                schema_version=1, record_id="sbrecord:v1:" + record_digest[7:],
                record_digest=record_digest, sid=sid, record_text=text,
                record_text_digest=record_text_digest, citation_span_start=span,
                citation_span_end=span + len(text_bytes), source_identity_full=source_identity,
                content_identity_full=content_identity, citation_identity_full=citation_identity,
                sensitivity=sensitivity, source_owner_class=owner_class,
                source_owner_id_digest=owner_digest, origin_label=origin_label,
                valid_from=valid_from, valid_until=valid_until,
            ))
            if len(rows) > _MAX_RECORDS:
                raise MemoryRecordError("MEMORY_RECORD_PAGE_OVERSIZE")
    return tuple(sorted(rows, key=lambda row: (row.citation_span_start, row.record_id)))


def find_record(
    root: Path,
    generation: GenerationIdentityV1,
    identity: tuple[str, str],
) -> tuple[str, MemoryRecordV1]:
    """Locate one provider-derived record without accepting caller page or metadata authority."""
    raw = _git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", "wiki", "daily", "conflicts")
    if not isinstance(raw, str):
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    paths = tuple(path for path in raw.splitlines() if path.endswith(".md"))
    if len(paths) > 4_096:  # protocol-wide bounded generation page scan
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    record_id, record_digest = identity
    matches: list[tuple[str, MemoryRecordV1]] = []
    for path in paths:
        page_id = path[:-3]
        for record in records_for_page(root, page_id, generation):
            if record.record_id == record_id and record.record_digest == record_digest:
                matches.append((page_id, record))
    if len(matches) != 1:
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    return matches[0]


def target_for_record(
    root: Path,
    generation: GenerationIdentityV1,
    selection: tuple[str, MemoryRecordV1, datetime],
) -> ResolvedMemoryTargetV1:
    """Construct the existing Task-30 target from one schema-4 record authority."""
    page_id, record, observed = selection
    rel = git_rel(page_id)
    blob_oid = _git(root, "rev-parse", f"HEAD:{rel}")
    blob = _git(root, "cat-file", "blob", f"HEAD:{rel}", binary=True)
    if not isinstance(blob_oid, str) or not isinstance(blob, bytes):
        raise MemoryRecordError("EFFECT_TARGET_INVALID")
    page_digest = "sha256:" + _hash(blob)
    subject_digest = "sha256:" + _hash(("subject\0" + page_id).encode())
    resolved_at = format_instant(observed)
    expires_at = format_instant(observed + timedelta(minutes=5))
    core: JsonObject = {
        "schema_version": 1, "provider_instance_id": generation.provider_instance_id,
        "generation_id": generation.generation_id,
        "generation_manifest_digest": generation.generation_manifest_digest,
        "vault_head": generation.vault_head, "vault_tree": generation.vault_tree,
        "page_id": page_id, "page_blob_oid": blob_oid, "page_content_digest": page_digest,
        "source_identity_full": record.source_identity_full,
        "content_identity_full": record.content_identity_full,
        "citation_identity_full": record.citation_identity_full,
        "citation_span_start": record.citation_span_start,
        "citation_span_end": record.citation_span_end, "subject_digest": subject_digest,
        "sensitivity": record.sensitivity, "valid_from": record.valid_from,
        "valid_until": record.valid_until, "source_owner_class": record.source_owner_class,
        "source_owner_id_digest": record.source_owner_id_digest, "resolved_at": resolved_at,
        "expires_at": expires_at,
    }
    target_digest = digest("target", core)
    return ResolvedMemoryTargetV1(
        schema_version=1, target_id="sbtarget:v1:" + target_digest[7:],
        target_digest=target_digest, provider_instance_id=generation.provider_instance_id,
        generation_id=generation.generation_id,
        generation_manifest_digest=generation.generation_manifest_digest,
        vault_head=generation.vault_head, vault_tree=generation.vault_tree,
        page_id=page_id, page_blob_oid=blob_oid, page_content_digest=page_digest,
        source_identity_full=record.source_identity_full,
        content_identity_full=record.content_identity_full,
        citation_identity_full=record.citation_identity_full,
        citation_span_start=record.citation_span_start,
        citation_span_end=record.citation_span_end, subject_digest=subject_digest,
        sensitivity=record.sensitivity, valid_from=record.valid_from,
        valid_until=record.valid_until, source_owner_class=record.source_owner_class,
        source_owner_id_digest=record.source_owner_id_digest,
        resolved_at=resolved_at, expires_at=expires_at,
    )
