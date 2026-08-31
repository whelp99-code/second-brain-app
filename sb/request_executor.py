"""Provider-owned stable request claim, recovery, effect, and proof execution."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.disposition import (
    MemorySurfaceEntryV1,
    create_surface_manifest,
    sign_disposition_proof,
)
from sb.effect_values import canonical_bytes, digest, format_instant, is_json_object, strict_loads
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import model_object, parse_effect_request
from sb.erasure import (
    ErasureEngine,
    ReingressGate,
    purge_matching_managed_copies,
    scan_managed_surfaces,
)
from sb.exports import ExportPublisher
from sb.generations import Generation, GenerationError, GenerationStore
from sb.request_store import RequestLease, RequestStatus, RequestStore
from sb.write_request_values import parse_envelope_bytes


class RequestExecutionError(RuntimeError):
    pass


def _empty_public_keys() -> dict[str, Ed25519PublicKey]:
    return {}


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    request_root: Path
    state_root: Path
    share_root: Path
    export_root: Path
    backup_root: Path
    provider_instance_id: str
    provider_release_sha: str
    provider_signing_key_id: str
    provider_signing_key: Ed25519PrivateKey
    jarvis_public_keys: Mapping[str, Ed25519PublicKey]
    external_public_keys: Mapping[str, Ed25519PublicKey] = field(default_factory=_empty_public_keys)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    request_id: str | None
    state: Literal["idle", "proved", "reconciling", "failed"]
    phase: str | None
    code: str
    fence: int


def _no_barrier(_phase: str) -> None:
    return


@final
class RequestExecutor:
    def __init__(
        self,
        config: ExecutorConfig,
        *,
        barrier: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.barrier: Callable[[str], None] = barrier or _no_barrier
        self.store = RequestStore(config.request_root)
        self.generations = GenerationStore(
            config.state_root,
            config.share_root,
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
            requests=self.store,
        )
        self.reingress = ReingressGate(config.state_root / "reingress.db")
        self.erasure = ErasureEngine(self.reingress)
        self.exports = ExportPublisher(config.export_root, config.provider_release_sha)
        config.backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.backup_root.chmod(0o700)

    def close(self) -> None:
        self.reingress.close()
        self.generations.close()
        self.store.close()

    @staticmethod
    def _fsync(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _claim_file(self, lease: RequestLease) -> Path:
        status = self.store.get(lease.request_id)
        if status is None:
            raise RequestExecutionError("REQUEST_NOT_FOUND")
        suffix = "v2" if status.identity.schema_version == 2 else "v1"
        pending = self.config.request_root / "pending" / f"{lease.request_id}.{suffix}.json"
        processing = self.config.request_root / "processing"
        target = processing / f"{lease.request_id}.{lease.fence}.{suffix}.json"
        if target.exists():
            return target
        candidates = sorted(processing.glob(f"{lease.request_id}.*.{suffix}.json"))
        source = pending if pending.exists() else (candidates[0] if len(candidates) == 1 else None)
        if source is None:
            raise RequestExecutionError("REQUEST_FILE_MISSING")
        os.replace(source, target)
        self._fsync(source.parent)
        if source.parent != target.parent:
            self._fsync(target.parent)
        self.barrier("claim_rename_fsync")
        return target

    def _parse_v2(self, path: Path, now: datetime) -> MemoryEffectWriteRequestV2:
        loaded = strict_loads(path.read_bytes(), 262_144)
        if not is_json_object(loaded):
            raise RequestExecutionError("EFFECT_REQUEST_INVALID")
        raw = loaded.get("request")
        return parse_effect_request(
            raw,
            now=format_instant(now),
            public_keys=self.config.jarvis_public_keys,
            expected_provider=self.config.provider_instance_id,
            external_public_keys=self.config.external_public_keys,
        )

    @staticmethod
    def _active_or_none(store: GenerationStore) -> Generation | None:
        try:
            return store.active()
        except GenerationError as exc:
            if store.active_link.exists() or store.active_link.is_symlink():
                raise
            del exc
            return None

    @staticmethod
    def _allowed(relative: Path) -> bool:
        if not relative.parts:
            return False
        forbidden = {"inbox", "exports", "backups", ".staging", ".retired"}
        return not any(part in forbidden for part in relative.parts)

    def _remember(
        self,
        lease: RequestLease,
        path: Path,
        now: datetime,
    ) -> tuple[Generation, Mapping[str, object]]:
        envelope = parse_envelope_bytes(path.read_bytes())
        request = envelope.request
        if request.operation.value != "remember":
            raise RequestExecutionError("REAPPROVAL_REQUIRED")
        content = request.payload["content"]
        source_identity = hashlib.sha256(str(request.candidate_id).encode()).hexdigest()
        content_identity = hashlib.sha256(content.encode()).hexdigest()
        self.reingress.check(
            source_identity=source_identity,
            content_identity=content_identity,
        )
        parent = self._active_or_none(self.generations)
        lease = self.store.transition(
            lease,
            "staging",
            now,
            generation_id=None if parent is None else parent.generation_id,
        )
        self.barrier("staging")

        def materialize(root: Path) -> None:
            page_id = "wiki/memory-" + content_identity[:16]
            page = root / f"{page_id}.md"
            page.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _ = page.write_text(content, encoding="utf-8")
            page.chmod(0o600)

        generation = self.generations.build(
            request_id=str(request.request_id),
            parent=parent,
            tombstone_sequence=0 if parent is None else parent.manifest.tombstone_sequence,
            tombstone_set_root=(
                "sha256:7fb694c8abb7c9a4477aa38381c49446493bc4da1c01b50690c1db5b2c20b9d3"
                if parent is None
                else parent.manifest.tombstone_set_root
            ),
            created_at=now,
            allowed=self._allowed,
            mutate=materialize,
        )
        lease = self.store.transition(lease, "sealed", now, generation_id=generation.generation_id)
        self.barrier("sealed")
        lease = self.store.transition(
            lease, "switch_intent", now, generation_id=generation.generation_id
        )
        self.barrier("switch_intent")
        self.generations.activate(generation, parent, now)
        lease = self.store.transition(lease, "activated", now, generation_id=generation.generation_id)
        self.barrier("activated")
        lease = self.store.transition(lease, "disposing", now, generation_id=generation.generation_id)
        lease = self.store.transition(lease, "proved", now, generation_id=generation.generation_id)
        artifact: dict[str, object] = {
            "schema_version": 1,
            "request_id": str(request.request_id),
            "generation_id": generation.generation_id,
            "head": generation.head,
            "tree": generation.tree,
            "content_digest": "sha256:" + content_identity,
        }
        return generation, artifact

    def _effect(
        self,
        lease: RequestLease,
        request: MemoryEffectWriteRequestV2,
        now: datetime,
    ) -> tuple[RequestLease, Generation, Mapping[str, object] | None, str | None]:
        parent = self._active_or_none(self.generations)
        if parent is None:
            raise RequestExecutionError("EFFECT_PRIOR_STALE")
        if (
            parent.generation_id != request.expected_prior.generation_id
            or parent.head != request.expected_prior.vault_head
            or parent.tree != request.expected_prior.vault_tree
        ):
            raise RequestExecutionError("EFFECT_PRIOR_STALE")
        self.reingress.block_request(request, now)
        lease = self.store.transition(lease, "staging", now, generation_id=parent.generation_id)
        self.barrier("staging")
        if request.operation == "export":
            manifest = self.exports.publish(
                request,
                parent,
                now,
                current_high_water=self.store.tombstone_high_water,
                fence=lease.fence,
            )
            lease = self.store.transition(lease, "sealed", now, generation_id=parent.generation_id)
            self.barrier("sealed")
            lease = self.store.transition(
                lease, "switch_intent", now, generation_id=parent.generation_id
            )
            lease = self.store.transition(lease, "activated", now, generation_id=parent.generation_id)
            lease = self.store.transition(lease, "disposing", now, generation_id=parent.generation_id)
            lease = self.store.transition(lease, "proved", now, generation_id=parent.generation_id)
            return lease, parent, None, manifest.manifest_digest

        prior_needles: list[bytes] = []
        for target in request.targets:
            page = parent.root / f"{target.page_id}.md"
            body = page.read_bytes()
            prior_needles.append(body[target.citation_span_start : target.citation_span_end])

        def mutate(root: Path) -> None:
            _ = self.erasure.apply(root, request, now)

        generation = self.generations.build(
            request_id=request.request_id,
            parent=parent,
            tombstone_sequence=request.tombstone_high_water.sequence,
            tombstone_set_root=request.tombstone_high_water.set_root,
            created_at=now,
            allowed=self._allowed,
            mutate=mutate,
        )
        lease = self.store.transition(lease, "sealed", now, generation_id=generation.generation_id)
        self.barrier("sealed")
        lease = self.store.transition(
            lease, "switch_intent", now, generation_id=generation.generation_id
        )
        self.barrier("switch_intent")
        self.generations.activate(generation, parent, now)
        lease = self.store.transition(lease, "activated", now, generation_id=generation.generation_id)
        self.barrier("activated")
        intersecting_identities = {
            identity
            for target in request.targets
            for identity in (
                target.target_id,
                target.source_identity_full,
                target.content_identity_full,
                target.citation_identity_full,
            )
        }
        _ = self.exports.invalidate(intersecting_identities)
        _ = purge_matching_managed_copies((self.config.backup_root,), tuple(prior_needles))
        lease = self.store.transition(lease, "disposing", now, generation_id=generation.generation_id)
        inventory = scan_managed_surfaces(
            (
                generation.root,
                self.config.request_root,
                self.config.export_root,
                self.config.backup_root,
            ),
            tuple(prior_needles),
        )
        if inventory.scan_errors or inventory.matches:
            raise RequestExecutionError("MANAGED_COPY_REMAINS")
        lease = self.store.transition(lease, "proved", now, generation_id=generation.generation_id)
        artifact: Mapping[str, object] | None = None
        if request.operation == "correct":
            artifact = {
                "schema_version": 1,
                "request_id": request.request_id,
                "target_id": request.targets[0].target_id,
                "content_digest": request.delegation.payload_digest,
                "generation_id": generation.generation_id,
            }
        return lease, generation, artifact, None

    def _proof(
        self,
        request: MemoryEffectWriteRequestV2,
        parent: Generation,
        result: Generation,
        artifact: Mapping[str, object] | None,
        export_manifest_digest: str | None,
        claimed_at: str,
        now: datetime,
    ) -> Mapping[str, object]:
        inventory = scan_managed_surfaces(
            (
                result.root,
                self.config.request_root / "receipts",
                self.config.export_root,
                self.config.backup_root,
            ),
            (),
        )
        surface_entry = MemorySurfaceEntryV1(
            owner="second_brain",
            surface_id=hashlib.sha256(result.generation_id.encode()).hexdigest(),
            manifest_digest=inventory.manifest_digest,
            readable=inventory.scan_errors == 0,
            file_count=sum(entry.file_count for entry in inventory.entries),
            row_count=0,
            object_count=0,
            fd_count=0,
            scan_digest=inventory.manifest_digest,
            match_count=inventory.matches,
            errors=[error for entry in inventory.entries for error in entry.errors],
            content_digests=[],
        )
        surface = create_surface_manifest(
            provider_instance_id=self.config.provider_instance_id,
            generation_id=result.generation_id,
            vault_head=result.head,
            vault_tree=result.tree,
            tombstone_sequence=request.tombstone_high_water.sequence,
            tombstone_set_root=request.tombstone_high_water.set_root,
            surfaces=[surface_entry],
            created_at=format_instant(now),
        )
        destructive = request.operation != "export"
        activation, drain, disposal = (
            self.generations.activation_digests(result.generation_id)
            if destructive
            else (None, None, None)
        )
        previous_root = (
            request.tombstone_chain_delta[-1].previous_root
            if request.tombstone_chain_delta
            else request.tombstone_high_water.set_root
        )
        body = {
            "schema_version": 1,
            "proof_type": "correction" if request.operation == "correct" else request.operation,
            "provider_instance_id": self.config.provider_instance_id,
            "provider_release_sha": self.config.provider_release_sha,
            "provider_signing_key_id": self.config.provider_signing_key_id,
            "request_id": request.request_id,
            "request_digest": request.request_digest,
            "envelope_digest": request.envelope_digest,
            "idempotency_key": request.idempotency_key,
            "delegation_id": request.delegation.delegation_id,
            "delegation_digest": request.delegation.delegation_digest,
            "lane_id": request.lane_id,
            "operation": request.operation,
            "payload_digest": request.delegation.payload_digest,
            "target_manifest_digest": request.target_manifest_digest,
            "scope_digest": request.scope_digest,
            "base_generation_id": parent.generation_id,
            "base_head": parent.head,
            "base_tree": parent.tree,
            "result_generation_id": result.generation_id,
            "result_head": result.head,
            "result_tree": result.tree,
            "tombstone_sequence": request.tombstone_high_water.sequence,
            "tombstone_previous_root": previous_root,
            "tombstone_set_root": request.tombstone_high_water.set_root,
            "activation_journal_digest": activation,
            "reader_drain_digest": drain,
            "predecessor_disposal_digest": disposal,
            "backup_disposal_digest": digest("surface", {"backups": []}) if destructive else None,
            "export_disposal_digest": digest("surface", {"exports": []}) if destructive else None,
            "surface_manifest_digest": surface.manifest_digest,
            "artifact_manifest_digest": None if artifact is None else digest("surface", artifact),
            "export_manifest_digest": export_manifest_digest,
            "claimed_at": claimed_at,
            "applied_at": format_instant(now),
            "completed_at": format_instant(now),
        }
        return model_object(sign_disposition_proof(body, self.config.provider_signing_key))

    def _write_receipt(self, status: RequestStatus, code: str) -> None:
        receipt = {
            "schema_version": status.identity.schema_version,
            "request_id": status.identity.request_id,
            "state": status.state,
            "request_digest": status.identity.request_digest,
            "envelope_digest": status.identity.envelope_digest,
            "status_digest": status.status_digest,
            "proof_digest": status.proof_digest,
            "code": code,
            "updated_at": status.updated_at,
        }
        path = self.config.request_root / "receipts" / f"{status.identity.request_id}.json"
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            payload = canonical_bytes(receipt) + b"\n"
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        self._fsync(path.parent)

    def apply_once(
        self,
        *,
        worker: str = "sb-apply-once",
        now: datetime | None = None,
        lease_ms: int = 60_000,
    ) -> ApplyResult:
        observed = datetime.now(UTC) if now is None else now.astimezone(UTC)
        lease = self.store.claim(worker, observed, lease_ms)
        if lease is None:
            return ApplyResult(None, "idle", None, "NO_PENDING_REQUEST", 0)
        path: Path | None = None
        activated = False
        try:
            path = self._claim_file(lease)
            self.barrier("journal_claim")
            status = self.store.get(lease.request_id)
            if status is None:
                raise RequestExecutionError("REQUEST_NOT_FOUND")
            claimed_at = format_instant(observed)
            if status.identity.schema_version == 1:
                generation, artifact = self._remember(lease, path, observed)
                current = self.store.get(lease.request_id)
                if current is None or current.phase != "proved":
                    raise RequestExecutionError("REQUEST_PHASE_INVALID")
                proof_digest = digest("surface", artifact)
                final_status = self.store.prove(
                    RequestLease(lease.request_id, lease.fence, lease.owner, "proved"),
                    artifact,
                    proof_digest,
                    digest("surface", {"state": "proved", "proof": proof_digest}),
                    observed,
                )
                activated = True
            else:
                request = self._parse_v2(path, observed)
                parent = self.generations.active()
                final_lease, generation, artifact, export_digest = self._effect(
                    lease, request, observed
                )
                activated = final_lease.phase in {"activated", "disposing", "proved"}
                proof = self._proof(
                    request,
                    parent,
                    generation,
                    artifact,
                    export_digest,
                    claimed_at,
                    observed,
                )
                proof_digest = str(proof["proof_digest"])
                final_status = self.store.prove(
                    final_lease,
                    proof,
                    proof_digest,
                    digest("surface", {"state": "proved", "proof": proof_digest}),
                    observed,
                )
            path.unlink(missing_ok=True)
            self._fsync(path.parent)
            self._write_receipt(final_status, "PROVIDER_PROVED")
            self.barrier("receipt_fsync")
            return ApplyResult(
                lease.request_id,
                "proved",
                "proved",
                "PROVIDER_PROVED",
                lease.fence,
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            code = str(exc) if str(exc) else type(exc).__name__
            status = self.store.get(lease.request_id)
            phase = None if status is None else status.phase
            if not activated and phase not in {"activated", "disposing", "proved"}:
                final_status = self.store.terminal(
                    lease.request_id,
                    "failed",
                    digest("surface", {"state": "failed", "code": code}),
                    observed,
                )
                if path is not None:
                    path.unlink(missing_ok=True)
                    self._fsync(path.parent)
                self._write_receipt(final_status, code)
                return ApplyResult(lease.request_id, "failed", phase, code, lease.fence)
            return ApplyResult(lease.request_id, "reconciling", phase, code, lease.fence)
