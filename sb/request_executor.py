"""Provider-owned stable request claim, recovery, effect, and proof execution.
# noqa: SIZE_OK -- one fenced provider execution state machine
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sb.disposition import sign_disposition_proof
from sb.effect_values import (
    JsonValue,
    canonical_bytes,
    digest,
    format_instant,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.effect_write_models import MemoryEffectWriteRequestV2
from sb.effect_write_values import model_object, parse_effect_request
from sb.erasure import (
    ErasureEngine,
    IngressIdentity,
    ReingressGate,
    scan_managed_surfaces,
)
from sb.export_models import MemoryExportManifestV1
from sb.exports import ExportPublication, ExportPublisher
from sb.generation_runtime import (
    GenerationAuthority,
    GenerationExpectation,
    GenerationMutation,
    GenerationMutationHooks,
    GenerationMutationService,
    GenerationOperation,
)
from sb.generations import Generation, GenerationError, GenerationStore
from sb.legacy_requests import LegacyRequestImporterV1
from sb.managed_backup_manifest import validate_managed_backups
from sb.managed_copy_disposal import (
    copy_disposal_binding,
    prepare_copy_disposal,
    require_copy_disposal,
)
from sb.provider_lifecycle import ProviderLifecycle
from sb.provider_observations import ProviderObservationInput, create_provider_observations
from sb.provider_surface_scanner import ProviderSurfaceLayout
from sb.remember_page import materialize_remember
from sb.request_store import (
    PHASES,
    Phase,
    RequestLease,
    RequestProofSettlement,
    RequestStatus,
    RequestStore,
)
from sb.scoped_request_execution import load_scoped_execution
from sb.scoped_write_request import ScopedWriteRequest
from sb.task30_barriers import (
    BarrierContext,
    BoundBarrierEmitter,
    NoopBarrierSink,
    Task30BarrierSink,
)
from sb.write_request_values import digest as write_digest
from sb.write_request_values import parse_remember_envelope


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
    legacy_request_roots: tuple[Path, ...] = ()
    search_hybrid: bool = False


@dataclass(frozen=True, slots=True)
class ApplyResult:
    request_id: str | None
    state: Literal["idle", "proved", "reconciling", "failed"]
    phase: str | None
    code: str
    fence: int


class GenerationIdentity(Protocol):
    @property
    def generation_id(self) -> str: ...

    @property
    def head(self) -> str: ...

    @property
    def tree(self) -> str: ...


@dataclass(frozen=True, slots=True)
class FrozenGenerationIdentity:
    generation_id: str
    head: str
    tree: str


@dataclass(frozen=True, slots=True)
class ProviderProofContext:
    request: MemoryEffectWriteRequestV2
    parent: GenerationIdentity
    result: Generation
    prior_needles: tuple[bytes, ...]
    export_manifest: MemoryExportManifestV1 | None
    claimed_at: str
    now: datetime


@final
class RequestExecutor:
    def __init__(
        self,
        config: ExecutorConfig,
        *,
        barrier_sink: Task30BarrierSink | None = None,
        scoped_authority: Callable[[ScopedWriteRequest], bool] | None = None,
    ) -> None:
        self.config = config
        self.barrier_sink = barrier_sink or NoopBarrierSink()
        self.barrier: Callable[[str], None] = BoundBarrierEmitter(
            self.barrier_sink,
            BarrierContext(),
        ).emit
        self.scoped_authority = scoped_authority
        self.store = RequestStore(config.request_root, scoped_v4=scoped_authority is not None)
        self.generations = GenerationStore(
            config.state_root,
            config.share_root,
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
            requests=self.store,
            hybrid=config.search_hybrid,
        )
        self.reingress = ReingressGate(config.state_root / "reingress.db")
        self.erasure = ErasureEngine(self.reingress)
        self.exports = ExportPublisher(
            config.export_root,
            config.provider_release_sha,
            self.store.exports,
        )
        self.lifecycle = ProviderLifecycle(self.exports)
        self.mutations = GenerationMutationService(
            self.generations,
            self.store,
            self.lifecycle,
        )
        if config.legacy_request_roots:
            _ = LegacyRequestImporterV1(
                config.request_root,
                config.legacy_request_roots,
            ).import_once(datetime.now(UTC))
        config.backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.backup_root.chmod(0o700)

    def close(self) -> None:
        self.reingress.close()
        self.generations.close()
        self.store.close()

    def _bind_barrier(self, lease: RequestLease) -> None:
        self.barrier = BoundBarrierEmitter(
            self.barrier_sink,
            BarrierContext(lease.request_id, lease.fence, lease.phase),
        ).emit

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
        if status.identity.schema_version not in ((1, 2, 3, 4) if self.scoped_authority is not None else (1, 2, 3)):
            raise RequestExecutionError("REQUEST_SCHEMA_UNSUPPORTED")
        suffix = f"v{status.identity.schema_version}"
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
        return parse_effect_request(
            loaded.get("request"),
            now=format_instant(now),
            public_keys=self.config.jarvis_public_keys,
            expected_provider=self.config.provider_instance_id,
            external_public_keys=self.config.external_public_keys,
        )

    @staticmethod
    def _active_or_none(store: GenerationStore) -> Generation | None:
        try:
            return store.active()
        except GenerationError:
            if store.active_link.exists() or store.active_link.is_symlink():
                raise
            return None

    def _advance(
        self,
        lease: RequestLease,
        target: Phase,
        now: datetime,
        generation_id: str | None,
    ) -> RequestLease:
        current_index = PHASES.index(lease.phase)
        target_index = PHASES.index(target)
        for index in range(current_index + 1, target_index + 1):
            phase = PHASES[index]
            lease = self.store.transition(lease, phase, now, generation_id=generation_id)
            self._bind_barrier(lease)
        return lease

    def _remember(
        self,
        lease: RequestLease,
        path: Path,
        now: datetime,
    ) -> tuple[RequestLease, Generation, Mapping[str, JsonValue]]:
        status = self.store.get(lease.request_id)
        if status is None:
            raise RequestExecutionError("REQUEST_NOT_FOUND")
        scoped_request = None
        source_access = None
        if status.identity.schema_version == 4:
            request, scoped_request = load_scoped_execution(path, status,
                provider=self.config.provider_instance_id, now=now)
            source_access = scoped_request.preparation.source_access
        else:
            envelope = parse_remember_envelope(path.read_bytes())
            request = envelope.request
            if (envelope.schema_version != status.identity.schema_version
                    or request.request_id != lease.request_id
                    or request.request_digest != status.identity.request_digest):
                raise RequestExecutionError("REQUEST_ENVELOPE_MISMATCH")
            acceptance = strict_loads(status.result_json, 17_408)
            file_digest = write_digest("file_v3" if envelope.schema_version == 3 else "file", asdict(envelope))
            if (not is_json_object(acceptance) or envelope.accepted_at != status.accepted_at
                    or acceptance.get("accepted_at") != envelope.accepted_at
                    or acceptance.get("request_file_digest") != file_digest):
                raise RequestExecutionError("REQUEST_ENVELOPE_MISMATCH")

        def resuming_applied_result() -> bool:
            # The durable pointer can precede the journal's activated transition.
            # Only the exact result bound to this validated request may recover.
            if (scoped_request is None or status.result_generation_id is None
                    or lease.phase not in {"switch_intent", "activated", "disposing", "proved"}):
                return False
            active = self._active_or_none(self.generations)
            return active is not None and active.generation_id == status.result_generation_id

        def require_scoped_authority() -> None:
            if scoped_request is not None and now >= scoped_request.expires_at:
                raise RequestExecutionError("SCOPED_WRITE_REQUEST_EXPIRED")
            if scoped_request is not None and (self.scoped_authority is None
                    or self.scoped_authority(scoped_request) is not True):
                raise RequestExecutionError("SCOPED_WRITE_AUTHORITY_INVALID")

        if not resuming_applied_result():
            require_scoped_authority()
        if request.operation.value != "remember":
            raise RequestExecutionError("REAPPROVAL_REQUIRED")
        content = request.payload["content"]
        source_identity = hashlib.sha256(str(request.candidate_id).encode()).hexdigest()
        content_identity = hashlib.sha256(content.encode()).hexdigest()
        self.reingress.check(IngressIdentity(source=source_identity, content=content_identity))
        resume_id = status.result_generation_id
        parent = (
            self.generations.generation(status.base_generation_id)
            if resume_id is not None and status.base_generation_id is not None
            else (None if resume_id is not None else self._active_or_none(self.generations))
        )
        lease = self._advance(
            lease,
            "staging",
            now,
            None if parent is None else parent.generation_id,
        )

        def materialize(root: Path) -> None:
            require_scoped_authority()
            materialize_remember(
                root, content=content, candidate_id=str(request.candidate_id),
                created_at=request.created_at, release_sha=self.config.provider_release_sha,
                sensitivity=request.sensitivity, source_access=source_access,
            )

        def sealed(generation: Generation) -> None:
            nonlocal lease
            lease = self._advance(lease, "sealed", now, generation.generation_id)

        def switching(generation: Generation) -> None:
            nonlocal lease
            # Recheck while the mutation service holds the writer lock. A new
            # materialization always checks live authority, even on a retry.
            if not resuming_applied_result():
                require_scoped_authority()
            lease = self._advance(lease, "switch_intent", now, generation.generation_id)

        def activated(generation: Generation) -> None:
            nonlocal lease
            lease = self._advance(lease, "activated", now, generation.generation_id)
            lease = self._advance(lease, "disposing", now, generation.generation_id)
            lease = self._advance(lease, "proved", now, generation.generation_id)

        expected = (
            None
            if parent is None
            else GenerationExpectation(parent.generation_id, parent.head, parent.tree)
        )
        mutation = self.mutations.mutate(
            GenerationMutation(
                mutation_id=lease.request_id,
                operation=GenerationOperation.REMEMBER,
                now=parse_instant(request.created_at),
                authority=GenerationAuthority(
                    expected,
                    self.store.tombstone_high_water(),
                    resume_generation_id=resume_id,
                ),
                apply=lambda root: materialize(root),
                recover=lambda _generation: None,
                hooks=GenerationMutationHooks(sealed, switching, activated),
                barrier=self.barrier,
            )
        )
        generation = mutation.generation
        artifact: dict[str, JsonValue] = {
            "schema_version": 1,
            "request_id": lease.request_id,
            "generation_id": generation.generation_id,
            "head": generation.head,
            "tree": generation.tree,
            "content_digest": "sha256:" + content_identity,
        }
        if scoped_request is not None:
            artifact.update(schema_version=4, request_digest=scoped_request.request_digest,
                scope_digest=scoped_request.preparation.identity.identity_digest,
                provider_instance_id=self.config.provider_instance_id)
        return lease, generation, artifact

    @staticmethod
    def _base_identity(request: MemoryEffectWriteRequestV2) -> FrozenGenerationIdentity:
        return FrozenGenerationIdentity(
            request.expected_prior.generation_id,
            request.expected_prior.vault_head,
            request.expected_prior.vault_tree,
        )

    @staticmethod
    def _prior_needles(parent: Generation | None, request: MemoryEffectWriteRequestV2) -> tuple[bytes, ...]:
        if parent is None or not parent.root.exists():
            return ()
        needles: list[bytes] = []
        for target in request.targets:
            page = parent.root / f"{target.page_id}.md"
            body = page.read_bytes()
            start, end = target.citation_span_start, target.citation_span_end
            if not 0 <= start < end <= len(body):
                raise RequestExecutionError("EFFECT_TARGET_INVALID")
            needles.append(body[start:end])
        return tuple(needles)

    def _result_generation(self, status: RequestStatus) -> Generation | None:
        if status.result_generation_id is None:
            return None
        try:
            return self.generations.generation(status.result_generation_id)
        except GenerationError:
            active = self._active_or_none(self.generations)
            if active is not None and active.generation_id == status.result_generation_id:
                return active
            raise

    def _effect(
        self,
        lease: RequestLease,
        request: MemoryEffectWriteRequestV2,
        now: datetime,
    ) -> tuple[
        RequestLease,
        GenerationIdentity,
        Generation,
        tuple[bytes, ...],
        MemoryExportManifestV1 | None,
    ]:
        status = self.store.get(lease.request_id)
        if status is None:
            raise RequestExecutionError("REQUEST_NOT_FOUND")
        active = self._active_or_none(self.generations)
        result = self._result_generation(status)
        base = self._base_identity(request)
        parent: Generation | None = None
        if active is not None and active.generation_id == request.expected_prior.generation_id:
            parent = active
        elif active is not None and result is not None and active.generation_id == result.generation_id:
            candidate = self.generations.generations / request.expected_prior.generation_id
            if candidate.is_dir():
                parent = self.generations.generation(request.expected_prior.generation_id)
        else:
            raise RequestExecutionError("EFFECT_PRIOR_STALE")
        if parent is not None and (
            parent.head != request.expected_prior.vault_head
            or parent.tree != request.expected_prior.vault_tree
        ):
            raise RequestExecutionError("EFFECT_PRIOR_STALE")

        self.reingress.block_request(request, now)
        lease = self._advance(
            lease,
            "staging",
            now,
            request.expected_prior.generation_id,
        )

        if request.operation == "export":
            if active.generation_id != request.expected_prior.generation_id:
                raise RequestExecutionError("EFFECT_PRIOR_STALE")
            with self.generations.exclusive():
                current_generation = self.generations.active()
                if current_generation.generation_id != active.generation_id:
                    raise RequestExecutionError("EFFECT_PRIOR_STALE")
                manifest = self.exports.publish(
                    ExportPublication(
                        request=request,
                        generation=current_generation,
                        now=now,
                        current_high_water=self.store.tombstone_high_water,
                        fence=lease.fence,
                        barrier=self.barrier,
                    )
                )
            lease = self._advance(lease, "proved", now, active.generation_id)
            return lease, base, active, (), manifest

        prior_needles = self._prior_needles(parent, request)
        if parent is None and result is None:
            raise RequestExecutionError("EFFECT_PRIOR_STALE")

        def mutate(root: Path) -> None:
            _ = self.erasure.apply(root, request, now)

        def sealed(generation: Generation) -> None:
            nonlocal lease
            lease = self._advance(lease, "sealed", now, generation.generation_id)

        def switching(generation: Generation) -> None:
            nonlocal lease
            roots = (self.config.backup_root, self.exports.root)

            def authority() -> None:
                if self.store.tombstone_high_water() != (
                    request.tombstone_high_water.sequence, request.tombstone_high_water.set_root,
                ):
                    raise RequestExecutionError("TOMBSTONE_SET_STALE")

            prepare_copy_disposal(self.store.db, request.request_id,
                copy_disposal_binding(request.request_digest, generation.generation_id, roots),
                backup_root=self.config.backup_root, exports=self.exports,
                identities={identity for target in request.targets for identity in (
                    target.target_id, target.source_identity_full,
                    target.content_identity_full, target.citation_identity_full)},
                needles=prior_needles if parent is not None and parent.root.exists() else None,
                now=now, authority=authority, barrier=self.barrier)
            lease = self._advance(lease, "switch_intent", now, generation.generation_id)

        def activated(generation: Generation) -> None:
            nonlocal lease
            lease = self._advance(lease, "activated", now, generation.generation_id)

        mutation = self.mutations.mutate(
            GenerationMutation(
                mutation_id=request.request_id,
                operation=GenerationOperation.EFFECT,
                now=parse_instant(request.created_at),
                authority=GenerationAuthority(
                    GenerationExpectation(
                        request.expected_prior.generation_id,
                        request.expected_prior.vault_head,
                        request.expected_prior.vault_tree,
                    ),
                    (
                        request.tombstone_high_water.sequence,
                        request.tombstone_high_water.set_root,
                    ),
                    resume_generation_id=None if result is None else result.generation_id,
                ),
                apply=lambda root: mutate(root),
                recover=lambda _generation: None,
                hooks=GenerationMutationHooks(sealed, switching, activated),
                barrier=self.barrier,
            )
        )
        result = mutation.generation

        roots = (self.config.backup_root, self.exports.root)
        require_copy_disposal(self.store.db, request.request_id,
            copy_disposal_binding(request.request_digest, result.generation_id, roots), roots)
        lease = self._advance(lease, "disposing", now, result.generation_id)
        inventory = scan_managed_surfaces(
            (
                result.root,
                self.config.request_root,
                self.config.state_root,
                self.config.export_root,
                self.config.backup_root,
                self.generations.staging,
                self.generations.retired,
            ),
            prior_needles,
        )
        if inventory.scan_errors or inventory.matches:
            raise RequestExecutionError("MANAGED_COPY_REMAINS")
        lease = self._advance(lease, "proved", now, result.generation_id)
        return lease, base, result, prior_needles, None

    def _validate_managed_lifecycle(self, result: Generation, now: datetime) -> None:
        self.exports.validate(now)
        if tuple(self.generations.staging.iterdir()) or tuple(self.generations.retired.iterdir()):
            raise RequestExecutionError("MANAGED_COPY_REMAINS")
        generation_names = {
            path.name
            for path in self.generations.generations.iterdir()
            if path.is_dir() and path.name not in {".staging", ".retired"}
        }
        if generation_names != {result.generation_id}:
            raise RequestExecutionError("GENERATION_SPLIT_BRAIN")
        validate_managed_backups(self.config.backup_root)

    def _proof(self, context: ProviderProofContext) -> RequestProofSettlement:
        request = context.request
        result = context.result
        self._validate_managed_lifecycle(result, context.now)
        observations = create_provider_observations(ProviderObservationInput(
            request=request,
            generation=result,
            layout=ProviderSurfaceLayout(
                generation_root=result.root,
                request_root=self.config.request_root,
                state_root=self.config.state_root,
                share_root=self.config.share_root,
                export_root=self.config.export_root,
                backup_root=self.config.backup_root,
                staging_root=self.generations.staging,
                retired_root=self.generations.retired,
            ),
            reingress=self.reingress,
            prior_needles=context.prior_needles,
            export_manifest=context.export_manifest,
            created_at=format_instant(context.now),
        ))
        destructive = request.operation != "export"
        activation, drain, disposal = (
            self.generations.activation_digests(result.generation_id)
            if destructive
            else (None, None, None)
        )
        inventory_digest = observations.surface_manifest.provider_inventory.manifest_digest
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
            "base_generation_id": context.parent.generation_id,
            "base_head": context.parent.head,
            "base_tree": context.parent.tree,
            "result_generation_id": result.generation_id,
            "result_head": result.head,
            "result_tree": result.tree,
            "tombstone_sequence": request.tombstone_high_water.sequence,
            "tombstone_previous_root": previous_root,
            "tombstone_set_root": request.tombstone_high_water.set_root,
            "activation_journal_digest": activation,
            "reader_drain_digest": drain,
            "predecessor_disposal_digest": disposal,
            "backup_disposal_digest": digest("surface", {"backups": inventory_digest})
            if destructive
            else None,
            "export_disposal_digest": digest("surface", {"exports": inventory_digest})
            if destructive
            else None,
            "surface_manifest_digest": observations.surface_manifest.manifest_digest,
            "artifact_manifest_digest": (
                None if observations.artifact is None else observations.artifact.manifest_digest
            ),
            "export_manifest_digest": (
                None if observations.export is None else observations.export.manifest_digest
            ),
            "claimed_at": context.claimed_at,
            "applied_at": format_instant(context.now),
            "completed_at": format_instant(context.now),
        }
        proof = model_object(sign_disposition_proof(body, self.config.provider_signing_key))
        proof_digest = str(proof["proof_digest"])
        return RequestProofSettlement(
            proof=proof,
            proof_digest=proof_digest,
            status_digest=digest("surface", {"state": "proved", "proof": proof_digest}),
            observations=observations,
            now=context.now,
        )

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
        if path.is_file():
            return
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            raw = canonical_bytes(receipt) + b"\n"
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                if written <= 0:
                    raise RequestExecutionError("WRITE_REQUEST_IO_FAILED")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        self._fsync(path.parent)

    def _finalize_proved(self) -> int:
        finalized = 0
        for status in self.store.list_states(("proved",)):
            files = sorted(
                (self.config.request_root / "processing").glob(
                    f"{status.identity.request_id}.*.v{status.identity.schema_version}.json"
                )
            )
            for path in files:
                path.unlink(missing_ok=True)
                finalized += 1
            if files:
                self._fsync(self.config.request_root / "processing")
            self._write_receipt(status, "PROVIDER_PROVED")
        return finalized

    def apply_once(
        self,
        *,
        worker: str = "sb-apply-once",
        now: datetime | None = None,
        lease_ms: int = 60_000,
    ) -> ApplyResult:
        observed = datetime.now(UTC) if now is None else now.astimezone(UTC)
        _ = self.mutations.maintain(observed)
        _ = self._finalize_proved()
        lease = self.store.claim(worker, observed, lease_ms)
        if lease is None:
            return ApplyResult(None, "idle", None, "NO_PENDING_REQUEST", 0)
        self._bind_barrier(lease)
        path: Path | None = None
        activated = lease.phase in {"activated", "disposing", "proved"}
        try:
            path = self._claim_file(lease)
            self.barrier("journal_claim")
            status = self.store.get(lease.request_id)
            if status is None:
                raise RequestExecutionError("REQUEST_NOT_FOUND")
            claimed_at = status.accepted_at
            if status.identity.schema_version in (1, 3) or (status.identity.schema_version == 4 and self.scoped_authority is not None):
                lease, generation, artifact = self._remember(lease, path, observed)
                proof_digest = digest("surface", artifact)
                final_status = self.store.prove(lease, RequestProofSettlement(
                    proof=artifact,
                    proof_digest=proof_digest,
                    status_digest=digest(
                        "surface", {"state": "proved", "proof": proof_digest}
                    ),
                    observations=None,
                    now=observed,
                ))
                activated = True
            elif status.identity.schema_version == 2:
                request = self._parse_v2(path, observed)
                lease, parent, generation, prior_needles, export_manifest = self._effect(
                    lease, request, observed
                )
                activated = lease.phase in {"activated", "disposing", "proved"}
                settlement = self._proof(ProviderProofContext(
                    request=request,
                    parent=parent,
                    result=generation,
                    prior_needles=prior_needles,
                    export_manifest=export_manifest,
                    claimed_at=claimed_at,
                    now=observed,
                ))
                final_status = self.store.prove(lease, settlement)
            else:
                raise RequestExecutionError("REQUEST_SCHEMA_UNSUPPORTED")
            self.barrier("proof_write_fsync")
            path.unlink(missing_ok=True)
            self._fsync(path.parent)
            self._write_receipt(final_status, "PROVIDER_PROVED")
            self.barrier("receipt_final_transition")
            return ApplyResult(lease.request_id, "proved", "proved", "PROVIDER_PROVED", lease.fence)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            code = str(exc) if str(exc) else type(exc).__name__
            status = self.store.get(lease.request_id)
            phase = None if status is None else status.phase
            activated = activated or phase in {"activated", "disposing", "proved"}
            if status is not None and status.result_generation_id is not None:
                current = self._active_or_none(self.generations)
                activated = activated or (
                    current is not None and current.generation_id == status.result_generation_id
                )
            if status is not None and status.identity.operation == "export":
                activated = activated or (self.config.export_root / lease.request_id).is_dir()
            if not activated:
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
