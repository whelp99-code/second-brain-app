"""Generation erasure plus compatibility exports for scan and reingress boundaries."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import final

from sb.briefing import CANONICAL_RE
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.correction_rendering import correction_marker, render_correction
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_models import (
    CorrectionPayloadModelV2,
    MemoryEffectWriteRequestV2,
    ResolvedMemoryTargetModel,
)
from sb.managed_copy_files import purge_matching_managed_copies
from sb.managed_surface_scan import (
    SurfaceInventory,
    SurfaceInventoryEntry,
    scan_managed_surfaces,
)
from sb.memory_records import MemoryRecordError, parse_page_records
from sb.provider_reingress_observations import observe_reingress_guards
from sb.provider_surface_scanner import scan_provider_surfaces
from sb.provider_surface_scanner_types import ProviderSurfaceLayout
from sb.reingress import ErasureError, IngressIdentity, NewVersionAuthority, ReingressGate
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault

__all__ = (
    "ErasureEngine",
    "ErasureError",
    "IngressIdentity",
    "NewVersionAuthority",
    "ProviderSurfaceLayout",
    "ReingressGate",
    "SurfaceInventory",
    "SurfaceInventoryEntry",
    "inventory_json",
    "observe_reingress_guards",
    "purge_matching_managed_copies",
    "scan_managed_surfaces",
    "scan_provider_surfaces",
)


@dataclass(frozen=True, slots=True)
class ErasurePlan:
    targets: Sequence[ResolvedMemoryTargetModel]
    operation: str
    request_id: str
    request_digest: str
    high_water: tuple[int, str]
    replacement: str | None
    source_hashes: tuple[str, ...] = ()
    remove_pages: bool = False


@final
class ErasureEngine:
    def __init__(self, reingress: ReingressGate) -> None:
        self.reingress = reingress

    @staticmethod
    def _page(root: Path, page_id: str) -> Path:
        relative = page_id if page_id.endswith(".md") else page_id + ".md"
        path = root / relative
        resolved_parent = path.parent.resolve()
        if not resolved_parent.is_relative_to(root.resolve()):
            raise ErasureError("EFFECT_TARGET_INVALID")
        return path

    @staticmethod
    def _write_private(path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            written = 0
            while written < len(value):
                count = os.write(descriptor, value[written:])
                if count <= 0:
                    raise ErasureError("GENERATION_WRITE_FAILED")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    def apply(self, root: Path, request: MemoryEffectWriteRequestV2, now: datetime) -> tuple[str, ...]:
        if request.operation == "export":
            return ()
        replacement = None
        if request.operation == "correct":
            if not isinstance(request.payload, CorrectionPayloadModelV2):
                raise ErasureError("EFFECT_OPERATION_CONFUSION")
            replacement = request.payload.content
        return self._apply(root, ErasurePlan(request.targets, request.operation, request.request_id,
            request.request_digest, (request.tombstone_high_water.sequence,
                request.tombstone_high_water.set_root), replacement), now)

    def suppress_cancellation(
        self, root: Path, intent: CorrectionCancellationIntentV1, now: datetime,
    ) -> tuple[str, ...]:
        """Internal admitted-intent path; never reconstruct or apply the original correction body."""
        return self._apply(root, ErasurePlan((intent.target,), "suppression", intent.intent_id,
            intent.intent_digest, (intent.tombstone.sequence, intent.tombstone.set_root), None), now)

    def apply_owner(self, root: Path, plan: ErasurePlan, now: datetime) -> tuple[str, ...]:
        """Apply a journal-admitted local owner receipt; never a delegated wire request."""
        return self._apply(root, plan, now)

    def _apply(self, root: Path, plan: ErasurePlan, now: datetime) -> tuple[str, ...]:
        removed: list[str] = []
        erased_hashes: set[str] = set()
        prior_records = [(root / "raw" / value[:2] / value).read_bytes()
                         for value in plan.source_hashes]
        originals: dict[Path, bytes] = {}
        edits: dict[Path, list[tuple[int, int, bytes]]] = {}
        for index, target in enumerate(plan.targets):
            if target.page_id.removesuffix(".md").startswith("wiki/life-event-"):
                raise ErasureError("LIFE_EVENT_API_REQUIRED")
            page = self._page(root, target.page_id)
            try:
                if page not in originals:
                    originals[page] = page.read_bytes()
                body = originals[page]
            except OSError as exc:
                raise ErasureError("EFFECT_PRIOR_STALE") from exc
            observed = "sha256:" + hashlib.sha256(body).hexdigest()
            if observed != target.page_content_digest:
                raise ErasureError("EFFECT_PRIOR_STALE")
            start, end = target.citation_span_start, target.citation_span_end
            if not 0 <= start < end <= len(body):
                raise ErasureError("EFFECT_TARGET_INVALID")
            prior = body[start:end]
            if hashlib.sha256(prior).hexdigest() != target.content_identity_full:
                raise ErasureError("EFFECT_TARGET_INVALID")
            prior_records.append(prior)
            if plan.replacement is not None and index == 0:
                sid = correction_marker(body[end:], prior)
                replacement = render_correction(plan.replacement, sid)
                if sid is not None and correction_marker(body[end:]) is None:
                    replacement += f"[^{sid}]"
                replacement_bytes = replacement.encode("utf-8")
                successor = body[:start] + replacement_bytes + body[end:]
                if sid is not None:
                    try:
                        prospective = parse_page_records(successor, target.page_id)
                        if any(len(row.record_text.encode("utf-8")) > 4_096 for row in prospective):
                            raise MemoryRecordError("MEMORY_RECORD_PAGE_OVERSIZE")
                    except MemoryRecordError as exc:
                        raise ErasureError("CORRECTION_RECORDS_INVALID") from exc
            else:
                replacement_bytes = b""
            edits.setdefault(page, []).append((start, end, replacement_bytes))
        for page, spans in edits.items():
            successor = originals[page]
            boundary = len(successor)
            for start, end, replacement_bytes in sorted(spans, reverse=True):
                if end > boundary:
                    raise ErasureError("EFFECT_TARGET_AMBIGUOUS")
                successor = successor[:start] + replacement_bytes + successor[end:]
                boundary = start
            if plan.source_hashes:
                # Daily input evidence is another rendering of the erased raw source,
                # not an unrelated statement to rebind to the correction receipt.
                successor = b"".join(line for line in successor.splitlines(keepends=True)
                    if not ((evidence := CANONICAL_RE.search(line.decode("utf-8")))
                            and evidence.group(2).lower() in plan.source_hashes))
            self._write_private(page, successor)
        if plan.remove_pages:
            for page_id in {target.page_id for target in plan.targets}:
                _ = Vault(root).forget_page(page_id)
        targets = set(originals)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or ".git" in path.relative_to(root).parts or path in targets:
                continue
            try:
                body = path.read_bytes()
            except OSError as exc:
                raise ErasureError("SURFACE_SCAN_FAILED") from exc
            relative = path.relative_to(root).as_posix()
            source_linked_page = relative.startswith(("wiki/", "daily/", "conflicts/"))
            if (any(prior in body for prior in prior_records)
                    or (source_linked_page and any(
                        value.encode("ascii") in body for value in plan.source_hashes))):
                # Hash-only operational history is not a derived content copy.
                # Never erase unrelated ledger rows by unlinking the database.
                if relative == ".sb/ledger.db":
                    raise ErasureError("MANAGED_COPY_REMAINS")
                if relative.startswith("raw/"):
                    erased_hashes.add(path.name)
                path.unlink()
                removed.append(hashlib.sha256(relative.encode("utf-8")).hexdigest())
        Vault(root).rebind_erased_sources(
            plan.request_id, frozenset(erased_hashes), ContentAddressedStore(root).put,
        )
        marker_root = root / ".sb" / "memory-effects"
        for target in plan.targets:
            marker = {
                "schema_version": 1,
                "operation": plan.operation,
                "target_digest": target.target_digest,
                "request_digest": plan.request_digest,
                "tombstone_sequence": plan.high_water[0],
                "tombstone_set_root": plan.high_water[1],
                "effective_at": format_instant(now),
            }
            self._write_private(
                marker_root / f"{target.target_digest[7:]}.json",
                canonical_bytes(marker) + b"\n",
            )
        for prior in prior_records:
            for path in root.rglob("*"):
                if (
                    path.is_file()
                    and ".git" not in path.relative_to(root).parts
                    and prior in path.read_bytes()
                ):
                    raise ErasureError("MANAGED_COPY_REMAINS")
        self.reingress.block_targets(plan.targets, plan.high_water, now,
                                     content_hashes=plan.source_hashes)
        return tuple(sorted(removed))


def inventory_json(inventory: SurfaceInventory) -> bytes:
    return canonical_bytes(
        {
            "entries": [asdict(entry) for entry in inventory.entries],
            "manifest_digest": inventory.manifest_digest,
            "scan_errors": inventory.scan_errors,
            "matches": inventory.matches,
        }
    ) + b"\n"
