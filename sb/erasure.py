"""Generation erasure plus compatibility exports for scan and reingress boundaries."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import final

from sb.correction_rendering import correction_marker, render_correction
from sb.effect_values import canonical_bytes, format_instant
from sb.effect_write_models import CorrectionPayloadModelV2, MemoryEffectWriteRequestV2
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
        removed: list[str] = []
        erased_hashes: set[str] = set()
        prior_records: list[bytes] = []
        for index, target in enumerate(request.targets):
            page = self._page(root, target.page_id)
            try:
                body = page.read_bytes()
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
            if request.operation == "correct" and index == 0:
                payload = request.payload
                if not isinstance(payload, CorrectionPayloadModelV2):
                    raise ErasureError("EFFECT_OPERATION_CONFUSION")
                sid = correction_marker(body[end:])
                replacement = render_correction(payload.content, sid)
                successor = body[:start] + replacement.encode("utf-8") + body[end:]
                if sid is not None:
                    try:
                        prospective = parse_page_records(successor, target.page_id)
                        if any(len(row.record_text.encode("utf-8")) > 4_096 for row in prospective):
                            raise MemoryRecordError("MEMORY_RECORD_PAGE_OVERSIZE")
                    except MemoryRecordError as exc:
                        raise ErasureError("CORRECTION_RECORDS_INVALID") from exc
            else:
                successor = body[:start] + body[end:]
            self._write_private(page, successor)
        targets = {self._page(root, target.page_id) for target in request.targets}
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or ".git" in path.relative_to(root).parts or path in targets:
                continue
            try:
                body = path.read_bytes()
            except OSError as exc:
                raise ErasureError("SURFACE_SCAN_FAILED") from exc
            if any(prior in body for prior in prior_records):
                relative = path.relative_to(root).as_posix()
                if relative.startswith("raw/"):
                    erased_hashes.add(path.name)
                path.unlink()
                removed.append(hashlib.sha256(relative.encode("utf-8")).hexdigest())
        Vault(root).rebind_erased_sources(
            str(request.request_id), frozenset(erased_hashes), ContentAddressedStore(root).put,
        )
        marker_root = root / ".sb" / "memory-effects"
        for target in request.targets:
            marker = {
                "schema_version": 1,
                "operation": request.operation,
                "target_digest": target.target_digest,
                "request_digest": request.request_digest,
                "tombstone_sequence": request.tombstone_high_water.sequence,
                "tombstone_set_root": request.tombstone_high_water.set_root,
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
        self.reingress.block_request(request, now)
        return tuple(sorted(removed))


def purge_matching_managed_copies(roots: Iterable[Path], needles: Sequence[bytes]) -> int:
    removed = 0
    for root in roots:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix(), reverse=True):
            if not path.is_file():
                continue
            raw = path.read_bytes()
            if any(needle in raw for needle in needles):
                path.unlink()
                removed += 1
    return removed


def inventory_json(inventory: SurfaceInventory) -> bytes:
    return canonical_bytes(
        {
            "entries": [asdict(entry) for entry in inventory.entries],
            "manifest_digest": inventory.manifest_digest,
            "scan_errors": inventory.scan_errors,
            "matches": inventory.matches,
        }
    ) + b"\n"
