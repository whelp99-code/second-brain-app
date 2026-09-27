"""Receipt-bound local owner effects using the shared tombstone/generation machinery.

The console is an owner surface, not a JARVIS delegation issuer. Pending plans are
fsynced before tombstone admission, replayable with the same receipt, and scrubbed
of replacement text after publication. No signed request or proof is fabricated.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from sb.config import Config
from sb.correction_rendering import correction_marker, render_correction
from sb.effect_access import apply_with_prior_access
from sb.effect_knowledge import apply_with_prior_knowledge
from sb.effect_values import JsonObject, canonical_bytes, digest, format_instant, parse_instant
from sb.effect_write_models import ClosedModel, ResolvedMemoryTargetModel, TombstoneChainEntryModel
from sb.effect_write_requests import open_request_directory
from sb.erasure import ErasureEngine, ErasurePlan, ReingressGate
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationExpectation,
    GenerationMutation,
    GenerationMutationHooks,
    GenerationOperation,
    generation_runtime_paths,
)
from sb.generation_staging import directory_fsync
from sb.generations import Generation
from sb.life_lock import publication_lock
from sb.managed_copy_disposal import copy_disposal_binding, prepare_copy_disposal
from sb.memory_records import parse_page_records, target_for_record
from sb.page_ids import git_rel
from sb.search import committed_text
from sb.targets import GenerationIdentityV1
from sb.vault import read_page_spec


class OwnerEffectError(ValueError):
    pass


class OwnerEffect(ClosedModel):
    request_id: str
    request_digest: str
    page_id: str
    operation: Literal["correct", "forget"]
    replacement: str | None
    targets: list[ResolvedMemoryTargetModel]
    source_targets: list[dict[str, str | int]]
    source_hashes: list[str]
    tombstone: TombstoneChainEntryModel
    result_generation_id: str | None = None
    result: dict[str, str | int] | None = None


def page_receipt(root: Path, page_id: str) -> JsonObject:
    raw = committed_text(root, git_rel(page_id))
    if raw is None:
        raise OwnerEffectError("EFFECT_PRIOR_STALE")
    body = raw.encode("utf-8")
    return {
        "receipt": {"page_id": page_id,
                    "page_content_digest": "sha256:" + hashlib.sha256(body).hexdigest()},
        "records": [record.as_dict() for record in parse_page_records(body, page_id)],
    }


def save(path: Path, effect: OwnerEffect) -> None:
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        _ = stream.write(effect.model_dump_json())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory_fsync(path.parent)


_save = save


def _prepare(generation: Generation, page_id: str, operation: Literal["correct", "forget"],
             receipt: object, record_id: str, content: str, request_digest: str,
             high_water: tuple[int, str], now: datetime) -> OwnerEffect:
    root = generation.root
    current = page_receipt(root, page_id)
    if receipt != current["receipt"]:
        raise OwnerEffectError("EFFECT_PRIOR_STALE")
    raw = (root / git_rel(page_id)).read_bytes()
    records = parse_page_records(raw, page_id)
    selected = [row for row in records if operation == "forget" or row.record_id == record_id]
    if not selected or (operation == "correct" and len(selected) != 1):
        raise OwnerEffectError("EFFECT_TARGET_INVALID")
    if operation == "correct":
        if not content.strip() or len(content.encode("utf-8")) > 4096:
            raise OwnerEffectError("CORRECTION_CONTENT_INVALID")
        row = selected[0]
        rendered = render_correction(content, correction_marker(raw[row.citation_span_end:]))
        successor = raw[:row.citation_span_start] + rendered.encode() + raw[row.citation_span_end:]
        prospective = parse_page_records(successor, page_id)
        if any(len(item.record_text.encode()) > 4096 for item in prospective):
            raise OwnerEffectError("CORRECTION_RECORDS_INVALID")
        if row.record_text.encode() in successor:
            raise OwnerEffectError("CORRECTION_RETAINS_PRIOR")
    identity = GenerationIdentityV1(generation.manifest.provider_instance_id,
        generation.generation_id, generation.manifest.generation_digest,
        generation.head, generation.tree)
    targets = [ResolvedMemoryTargetModel.model_validate(
        target_for_record(root, identity, (page_id, row, now)).as_dict()) for row in selected]
    # Several citations can describe the same span. Erase that span once.
    targets = list({(row.citation_span_start, row.citation_span_end): row for row in targets}.values())
    spec = read_page_spec(root, page_id)
    if spec is None:
        raise OwnerEffectError("EFFECT_TARGET_INVALID")
    source_targets: list[dict[str, str | int]] = []
    source_hashes: list[str] = []
    for cite in spec.sources:
        if cite.sid not in {row.sid for row in selected} or cite.hash in source_hashes:
            continue
        relative = f"raw/{cite.hash[:2]}/{cite.hash}"
        source = (root / relative).read_bytes()
        if not source or hashlib.sha256(source).hexdigest() != cite.hash:
            raise OwnerEffectError("EFFECT_SOURCE_INVALID")
        if operation == "correct" and source in content.encode("utf-8"):
            raise OwnerEffectError("CORRECTION_RETAINS_PRIOR")
        source_hashes.append(cite.hash)
        # Raw bytes have their own exact inventory span, not an invented page record.
        source_core: dict[str, str | int] = {
            "page_id": relative, "page_content_digest": "sha256:" + cite.hash,
            "source_identity_full": hashlib.sha256(cite.origin.encode()).hexdigest(),
            "content_identity_full": cite.hash,
            "citation_identity_full": hashlib.sha256(relative.encode()).hexdigest(),
            "subject_digest": targets[0].subject_digest,
            "citation_span_start": 0, "citation_span_end": len(source),
        }
        source_targets.append({**source_core, "target_digest": digest("target", source_core)})
    # The erasure scan removes source-linked derived pages even when their wording
    # differs. Bind those exact copies too, so old archives cannot restore them.
    for folder in ("wiki", "daily", "conflicts"):
        for path in sorted((root / folder).rglob("*.md")):
            relative = path.relative_to(root).with_suffix("").as_posix()
            if relative == page_id and operation == "correct":
                continue
            payload = path.read_bytes()
            if relative != page_id and not any(value.encode() in payload for value in source_hashes):
                continue
            content_hash = hashlib.sha256(payload).hexdigest()
            copy_core: dict[str, str | int] = {
                "page_id": relative, "page_content_digest": "sha256:" + content_hash,
                "source_identity_full": targets[0].source_identity_full,
                "content_identity_full": content_hash,
                "citation_identity_full": hashlib.sha256(relative.encode()).hexdigest(),
                "subject_digest": targets[0].subject_digest,
                "citation_span_start": 0, "citation_span_end": len(payload),
            }
            source_targets.append({**copy_core, "target_digest": digest("target", copy_core)})
    request_id = "owner-effect:" + request_digest[7:]
    core: JsonObject = {
        "sequence": high_water[0] + 1, "previous_root": high_water[1],
        "operation": operation, "lane_id": request_id,
        "target_manifest_digest": digest("target_manifest", {
            "targets": [*[t.model_dump(mode="json") for t in targets], *source_targets]}),
        "scope_digest": digest("target_scope", {"page_id": page_id, "record_id": record_id}),
        "authority_receipt_digest": digest("effect_spec", current["receipt"]),
        "payload_digest": digest("effect_content", {"content": content}),
        "keyed_subject_digest": targets[0].subject_digest,
        "effective_at": format_instant(now),
    }
    set_root = digest("tombstone_chain", core)
    return OwnerEffect(request_id=request_id, request_digest=request_digest,
        page_id=page_id, operation=operation, replacement=content if operation == "correct" else None,
        targets=targets, source_targets=source_targets, source_hashes=source_hashes,
        tombstone=TombstoneChainEntryModel.model_validate({**core,
            "tombstone_id": "memtomb:v1:" + set_root[7:], "set_root": set_root}))


def apply_page_effect(config: Config, page_id: str, operation: Literal["correct", "forget"],
                      receipt: object, *, record_id: str = "", content: str = "") -> dict[str, str | int]:
    if page_id.removesuffix(".md").startswith("wiki/life-event-"):
        raise OwnerEffectError("LIFE_EVENT_API_REQUIRED")
    if not isinstance(receipt, dict):
        raise OwnerEffectError("EFFECT_RECEIPT_REQUIRED")
    supplied = cast(dict[object, object], receipt)
    if set(supplied) != {"page_id", "page_content_digest"} or not all(
        isinstance(value, str) for value in supplied.values()
    ):
        raise OwnerEffectError("EFFECT_RECEIPT_REQUIRED")
    checked_receipt = cast(dict[str, str], supplied)
    paths = generation_runtime_paths(config)
    config = replace(config, raw={**config.raw, "state_root": str(paths.state),
        "share_root": str(paths.share), "request_root": str(paths.requests),
        "export_root": str(paths.exports),
        "backup_root": config.backup_root if "backup_root" in config.raw else str(paths.state / "backups")})
    request_digest = "sha256:" + hashlib.sha256(canonical_bytes({
        "page_id": page_id, "operation": operation, "receipt": checked_receipt,
        "record_id": record_id, "content": content})).hexdigest()
    with publication_lock(paths.active):
        service = GenerationMutationService.from_config(config)
        descriptor = open_request_directory(service.requests.pending)
        try:
            # Same lock order as backup and delegated request admission.
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if not paths.active.is_symlink():
                _ = service.mutate(GenerationMutation("owner-migration:" + request_digest[7:],
                    GenerationOperation.EFFECT, datetime.now(UTC),
                    GenerationAuthority(None, None), lambda _root: None))
            folder = paths.state / "owner-effects"
            folder.mkdir(exist_ok=True, mode=0o700)
            path = folder / (request_digest[7:] + ".json")
            with service.store.exclusive():
                if path.exists():
                    effect = OwnerEffect.model_validate_json(path.read_bytes())
                else:
                    effect = _prepare(service.store.active(), page_id, operation, checked_receipt,
                        record_id, content, request_digest, service.requests.tombstone_high_water(),
                        datetime.now(UTC))
                    _save(path, effect)
                if effect.result is not None:
                    return effect.result
                high_water = (effect.tombstone.sequence, effect.tombstone.set_root)
                observed = service.requests.tombstone_high_water()
                if observed == (effect.tombstone.sequence - 1, effect.tombstone.previous_root):
                    _ = service.requests.apply_tombstones([effect.tombstone.model_dump(mode="json")],
                        effect.request_id, parse_instant(effect.tombstone.effective_at),
                        targets=(*(target.model_dump(mode="json") for target in effect.targets),
                                 *(dict(target) for target in effect.source_targets)))
                elif observed != high_water:
                    raise OwnerEffectError("EFFECT_PRIOR_STALE")
            return _publish(config, service, effect, path)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            service.close()


def _publish(config: Config, service: GenerationMutationService, effect: OwnerEffect,
             path: Path) -> dict[str, str | int]:
    now = parse_instant(effect.tombstone.effective_at)
    target = effect.targets[0]
    high_water = (effect.tombstone.sequence, effect.tombstone.set_root)
    gate = ReingressGate(Path(config.state_root) / "reingress.db")
    backup = Path(config.backup_root)
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    roots = (backup, service.lifecycle.exports.root)
    prior = service.store.generations / target.generation_id
    needles = (tuple((prior / git_rel(item.page_id)).read_bytes()[
        item.citation_span_start:item.citation_span_end] for item in effect.targets)
        + tuple((prior / "raw" / value[:2] / value).read_bytes() for value in effect.source_hashes)
        if prior.exists() else None)

    def apply(root: Path) -> None:
        def erase() -> None:
            _ = ErasureEngine(gate).apply_owner(root, ErasurePlan(effect.targets, effect.operation,
                effect.request_id, effect.request_digest, high_water, effect.replacement,
                tuple(effect.source_hashes), effect.operation == "forget"), now)
        apply_with_prior_access(root, lambda: apply_with_prior_knowledge(root, erase))

    def sealed(generation: Generation) -> None:
        _save(path, effect.model_copy(update={"result_generation_id": generation.generation_id}))

    def switching(generation: Generation) -> None:
        def authority() -> None:
            if service.requests.tombstone_high_water() != high_water:
                raise OwnerEffectError("EFFECT_PRIOR_STALE")
        prepare_copy_disposal(service.requests.db, effect.request_id,
            copy_disposal_binding(effect.request_digest, generation.generation_id, roots),
            backup_root=backup, exports=service.lifecycle.exports,
            identities={identity for item in effect.targets for identity in (
                item.target_id, item.source_identity_full, item.content_identity_full,
                item.citation_identity_full)}, needles=needles, now=now,
            authority=authority, barrier=lambda _phase: None)

    try:
        mutation = service.mutate(GenerationMutation(effect.request_id, GenerationOperation.EFFECT,
            now, GenerationAuthority(GenerationExpectation(target.generation_id,
                target.vault_head, target.vault_tree), high_water,
                resume_generation_id=effect.result_generation_id), apply,
            recover=lambda _generation: None,
            hooks=GenerationMutationHooks(sealed, switching, lambda _generation: None)))
        result: dict[str, str | int] = {
            "corrected" if effect.operation == "correct" else "forgotten": effect.page_id,
            "receipt_id": effect.request_id, "commit": mutation.generation.head,
            "tombstone_sequence": high_water[0], "tombstone_set_root": high_water[1],
        }
        _save(path, effect.model_copy(update={"replacement": None,
            "result_generation_id": mutation.generation.generation_id, "result": result}))
        return result
    finally:
        gate.close()
