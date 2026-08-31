"""Exact committed-record target resolution with full authority identities."""

from __future__ import annotations

import hashlib
import hmac
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from sb.effect_values import digest, format_instant
from sb.page_ids import git_rel


class TargetResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GenerationIdentityV1:
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: str
    vault_head: str
    vault_tree: str


@dataclass(frozen=True, slots=True)
class MemoryTargetSelectorV1:
    page_id: str
    exact_record: str
    source_identity_full: str
    citation_identity_full: str | None = None
    sensitivity: Literal["public", "personal", "sensitive", "restricted"] = "personal"
    source_owner_class: Literal["provider_owned", "external_read_only"] = "provider_owned"
    source_owner_id: str = "provider"
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedMemoryTargetV1:
    schema_version: int
    target_id: str
    target_digest: str
    provider_instance_id: str
    generation_id: str
    generation_manifest_digest: str
    vault_head: str
    vault_tree: str
    page_id: str
    page_blob_oid: str
    page_content_digest: str
    source_identity_full: str
    content_identity_full: str
    citation_identity_full: str
    citation_span_start: int
    citation_span_end: int
    subject_digest: str
    sensitivity: str
    valid_from: str
    valid_until: str
    source_owner_class: str
    source_owner_id_digest: str
    resolved_at: str
    expires_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetScopeV1:
    format: Literal["none", "json"]
    sensitivity_classes: tuple[str, ...]
    valid_from: str
    valid_until: str
    max_records: int
    max_bytes: int
    source_owner_classes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["sensitivity_classes"] = list(self.sensitivity_classes)
        value["source_owner_classes"] = list(self.source_owner_classes)
        return value


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    return completed.stdout if binary else completed.stdout.decode("utf-8").strip()


def _full_identity(value: str, code: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise TargetResolutionError(code)
    return value


def resolve_memory_target(
    root: Path,
    generation: GenerationIdentityV1,
    selector: MemoryTargetSelectorV1,
    *,
    owner_digest_key: bytes,
    subject_digest_key: bytes,
    now: datetime | None = None,
    lifetime: timedelta | None = None,
) -> ResolvedMemoryTargetV1:
    """Resolve one byte-exact citation record from a single committed blob."""
    observed = datetime.now(UTC) if now is None else now.astimezone(UTC)
    target_lifetime = timedelta(minutes=5) if lifetime is None else lifetime
    if not timedelta(seconds=1) <= target_lifetime <= timedelta(minutes=5):
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    rel = git_rel(selector.page_id)
    if not rel.endswith(".md") or not rel.startswith(("wiki/", "daily/", "conflicts/")):
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if head != generation.vault_head or tree != generation.vault_tree:
        raise TargetResolutionError("EFFECT_PRIOR_STALE")
    blob_oid = _git(root, "rev-parse", f"HEAD:{rel}")
    blob = _git(root, "cat-file", "blob", f"HEAD:{rel}", binary=True)
    if not isinstance(blob, bytes) or not isinstance(blob_oid, str):
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    record = selector.exact_record.encode("utf-8")
    if not record:
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    start = blob.find(record)
    if start < 0:
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    if blob.find(record, start + 1) >= 0:
        raise TargetResolutionError("EFFECT_TARGET_AMBIGUOUS")
    source_identity = _full_identity(selector.source_identity_full, "EFFECT_TARGET_INVALID")
    content_identity = hashlib.sha256(record).hexdigest()
    citation_identity = selector.citation_identity_full
    if citation_identity is None:
        citation_identity = hashlib.sha256(
            selector.page_id.encode("utf-8") + b"\0" + record
        ).hexdigest()
    citation_identity = _full_identity(citation_identity, "EFFECT_TARGET_INVALID")
    valid_from = selector.valid_from or format_instant(observed)
    valid_until = selector.valid_until or format_instant(observed + timedelta(days=1))
    core: dict[str, object] = {
        "schema_version": 1,
        "provider_instance_id": generation.provider_instance_id,
        "generation_id": generation.generation_id,
        "generation_manifest_digest": generation.generation_manifest_digest,
        "vault_head": generation.vault_head,
        "vault_tree": generation.vault_tree,
        "page_id": selector.page_id,
        "page_blob_oid": blob_oid,
        "page_content_digest": "sha256:" + hashlib.sha256(blob).hexdigest(),
        "source_identity_full": source_identity,
        "content_identity_full": content_identity,
        "citation_identity_full": citation_identity,
        "citation_span_start": start,
        "citation_span_end": start + len(record),
        "subject_digest": "sha256:"
        + hmac.new(subject_digest_key, selector.page_id.encode("utf-8"), hashlib.sha256).hexdigest(),
        "sensitivity": selector.sensitivity,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "source_owner_class": selector.source_owner_class,
        "source_owner_id_digest": "sha256:"
        + hmac.new(owner_digest_key, selector.source_owner_id.encode("utf-8"), hashlib.sha256).hexdigest(),
        "resolved_at": format_instant(observed),
        "expires_at": format_instant(observed + target_lifetime),
    }
    target_digest = digest("target", core)
    return ResolvedMemoryTargetV1(
        schema_version=1,
        target_id="sbtarget:v1:" + target_digest[7:],
        target_digest=target_digest,
        provider_instance_id=generation.provider_instance_id,
        generation_id=generation.generation_id,
        generation_manifest_digest=generation.generation_manifest_digest,
        vault_head=generation.vault_head,
        vault_tree=generation.vault_tree,
        page_id=selector.page_id,
        page_blob_oid=blob_oid,
        page_content_digest="sha256:" + hashlib.sha256(blob).hexdigest(),
        source_identity_full=source_identity,
        content_identity_full=content_identity,
        citation_identity_full=citation_identity,
        citation_span_start=start,
        citation_span_end=start + len(record),
        subject_digest="sha256:"
        + hmac.new(subject_digest_key, selector.page_id.encode("utf-8"), hashlib.sha256).hexdigest(),
        sensitivity=selector.sensitivity,
        valid_from=valid_from,
        valid_until=valid_until,
        source_owner_class=selector.source_owner_class,
        source_owner_id_digest="sha256:"
        + hmac.new(owner_digest_key, selector.source_owner_id.encode("utf-8"), hashlib.sha256).hexdigest(),
        resolved_at=format_instant(observed),
        expires_at=format_instant(observed + target_lifetime),
    )


def target_manifest_digest(targets: tuple[ResolvedMemoryTargetV1, ...]) -> str:
    ordered = tuple(sorted(targets, key=lambda target: target.target_digest))
    if not ordered or len(ordered) > 64:
        raise TargetResolutionError("EFFECT_TARGET_INVALID")
    if len({target.target_digest for target in ordered}) != len(ordered):
        raise TargetResolutionError("EFFECT_TARGET_AMBIGUOUS")
    return digest("target_manifest", {"targets": [target.as_dict() for target in ordered]})


def target_scope_digest(
    targets: tuple[ResolvedMemoryTargetV1, ...],
    scope: TargetScopeV1,
) -> str:
    ordered = sorted(target.target_digest for target in targets)
    return digest("target_scope", {"target_digests": ordered, "scope": scope.as_dict()})
