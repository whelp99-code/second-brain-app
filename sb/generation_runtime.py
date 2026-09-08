"""Provider-wide generation mutation ownership for every content writer."""

from __future__ import annotations

import os
import shutil
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import final
from uuid import uuid4

from sb.config import Config
from sb.exports import ExportPublisher
from sb.generation_locks import GenerationWriterBusy
from sb.generation_runtime_models import (
    GenerationActivation,
    GenerationAuthority,
    GenerationExpectation,
    GenerationMutation,
    GenerationMutationError,
    GenerationMutationHooks,
    GenerationMutationResult,
    GenerationOperation,
    GenerationRuntimePaths,
    generation_runtime_paths,
)
from sb.generation_staging import (
    copy_legacy_content,
    copy_operational_ledger,
    copy_pending_inbox,
    directory_fsync,
    remove_provisional_git,
)
from sb.generations import Generation, GenerationStore
from sb.inbox import parse_remember, publish_inbox
from sb.provider_lifecycle import MaintenanceResult, ProviderLifecycle
from sb.request_store import RequestStore
from sb.store.ledger import migrate_ledger
from sb.vault import init_vault

__all__ = (
    "GenerationAuthority",
    "GenerationExpectation",
    "GenerationMutation",
    "GenerationMutationError",
    "GenerationMutationHooks",
    "GenerationMutationResult",
    "GenerationMutationService",
    "GenerationOperation",
    "GenerationRuntimePaths",
    "generation_runtime_paths",
)


@final
class GenerationMutationService:
    """Serialize base selection, staged mutation, sealing, switch, and disposal."""

    def __init__(
        self,
        store: GenerationStore,
        requests: RequestStore,
        lifecycle: ProviderLifecycle,
    ) -> None:
        self.store = store
        self.requests = requests
        self.lifecycle = lifecycle

    @classmethod
    def from_config(cls, config: Config, *, maintenance_only: bool = False) -> GenerationMutationService:
        paths = generation_runtime_paths(config)
        requests = RequestStore(paths.requests, maintenance_only=maintenance_only)
        store = GenerationStore(
            paths.state,
            paths.share,
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
            requests=requests,
            hybrid=config.search_hybrid,
        )
        exports = ExportPublisher(paths.exports, config.provider_release_sha, requests.exports)
        return cls(store, requests, ProviderLifecycle(exports))

    def close(self) -> None:
        self.store.close()
        self.requests.close()

    def remember(self, content: str, title: str | None, now: datetime) -> Path:
        note = parse_remember(content, title)
        result = self.mutate(
            GenerationMutation(
                mutation_id=f"inbox:{uuid4().hex}",
                operation=GenerationOperation.INBOX,
                now=now,
                authority=GenerationAuthority(None, None),
                apply=lambda root: publish_inbox(root, note),
            )
        )
        return result.value

    def maintain(self, now: datetime) -> MaintenanceResult:
        with self.store.exclusive():
            return self._maintain_locked(now)

    def maintain_if_idle(self, now: datetime) -> MaintenanceResult | None:
        """A read must not wait behind a writer merely to run physical cleanup.

        Writer entry/exit and the maintenance surface still recover disposal.
        This does not bypass the reader pin, tombstone fence, or export expiry.
        """
        try:
            with self.store.try_exclusive():
                return self._maintain_locked(now)
        except GenerationWriterBusy:
            return None

    def _maintain_locked(self, now: datetime) -> MaintenanceResult:
        parent, _legacy = self._current_or_legacy()
        disposed = self.store.discard_abandoned_staging()
        if parent is not None:
            self.store.activate(parent, None, now, lock_held=True)
        result = self.lifecycle.maintain(now)
        return MaintenanceResult(result.disposed_export_digests, disposed)

    @staticmethod
    def _allowed(relative: Path) -> bool:
        return bool(relative.parts) and not any(
            part in {"inbox", "exports", "backups", ".staging", ".retired"}
            for part in relative.parts
        )

    def _current_or_legacy(self) -> tuple[Generation | None, Path | None]:
        legacy = self.store.retired / ".legacy-active"
        if self.store.active_link.is_symlink():
            if legacy.exists():
                shutil.rmtree(legacy)
                directory_fsync(self.store.retired)
            return self.store.active(), None
        if self.store.active_link.is_dir():
            return None, self.store.active_link
        if legacy.is_dir():
            return None, legacy
        if not self.store.active_link.exists() and not self.store.active_link.is_symlink():
            return None, None
        raise GenerationMutationError("GENERATION_SPLIT_BRAIN")

    @staticmethod
    def _matches(generation: Generation, expected: GenerationExpectation | None) -> bool:
        return expected is None or (
            generation.generation_id == expected.generation_id
            and generation.head == expected.head
            and generation.tree == expected.tree
        )

    def _require_authority(
        self,
        parent: Generation | None,
        authority: GenerationAuthority,
        target: tuple[int, str],
    ) -> None:
        if self.requests.tombstone_high_water() != target:
            raise GenerationMutationError("TOMBSTONE_SET_STALE")
        if parent is None and authority.expected_base is not None:
            raise GenerationMutationError("EFFECT_PRIOR_STALE")
        if parent is not None and not self._matches(parent, authority.expected_base):
            raise GenerationMutationError("EFFECT_PRIOR_STALE")
        if parent is not None and authority.expected_base is None:
            observed = (parent.manifest.tombstone_sequence, parent.manifest.tombstone_set_root)
            if observed != target:
                raise GenerationMutationError("TOMBSTONE_SET_STALE")

    def _resume[T](
        self,
        mutation: GenerationMutation[T],
        parent: Generation,
        target: tuple[int, str],
    ) -> GenerationMutationResult[T]:
        if self.requests.tombstone_high_water() != target or (
            parent.manifest.tombstone_sequence,
            parent.manifest.tombstone_set_root,
        ) != target:
            raise GenerationMutationError("TOMBSTONE_SET_STALE")
        predecessor = None
        expected = mutation.authority.expected_base
        if expected is not None:
            candidate = self.store.generations / expected.generation_id
            if candidate.is_dir():
                predecessor = self.store.generation(expected.generation_id)
        if mutation.hooks is not None:
            mutation.hooks.sealed(parent)
            mutation.hooks.switching(parent)
        self.store.activate(
            parent,
            predecessor,
            mutation.now,
            barrier=mutation.barrier,
            lock_held=True,
        )
        if mutation.hooks is not None:
            mutation.hooks.activated(parent)
        if mutation.recover is None:
            raise GenerationMutationError("GENERATION_RECOVERY_INVALID")
        return GenerationMutationResult(parent, mutation.recover(parent), predecessor)

    def mutate[T](self, mutation: GenerationMutation[T]) -> GenerationMutationResult[T]:
        with self.store.writer() as writer:
            parent, legacy = self._current_or_legacy()
            _ = self.store.discard_abandoned_staging()
            _ = self.lifecycle.maintain(mutation.now)
            target = mutation.authority.result_high_water or self.requests.tombstone_high_water()
            if parent is not None and mutation.authority.resume_generation_id == parent.generation_id:
                return self._resume(mutation, parent, target)
            self._require_authority(parent, mutation.authority, target)
            if parent is not None:
                # Finish a prior pointer switch before creating another successor.
                # Otherwise its undisposed predecessor can become an orphan forever.
                self.store.activate(parent, None, mutation.now, lock_held=True)
            values: list[T] = []

            def staged(root: Path) -> None:
                source = parent.root if parent is not None else legacy
                if source is not None:
                    if legacy is not None:
                        copy_legacy_content(source, root)
                    copy_pending_inbox(source, root, self.store.state_root)
                    copy_operational_ledger(source, root)
                # Genesis also needs the canonical log and gitignore; otherwise
                # a first remember cannot pass the required export inventory.
                _ = init_vault(root)
                (root / ".sb").mkdir(parents=True, exist_ok=True, mode=0o700)
                _ = migrate_ledger(root / ".sb" / "ledger.db", backup=False)
                values.append(mutation.apply(root))
                # Pending/failed input survives every mutation. The inbox adapter
                # acknowledges committed input explicitly; only that residue is disposable.
                shutil.rmtree(root / "inbox" / ".done", ignore_errors=True)
                remove_provisional_git(root)
                self._require_authority(parent, mutation.authority, target)

            # A sealed parent stays immutable and protected by generation.lock
            # while the successor is built. Legacy migration still excludes reads.
            with writer.preparing() if parent is not None else nullcontext():
                generation = self.store.build(
                    request_id=mutation.mutation_id,
                    parent=parent,
                    tombstone_sequence=target[0],
                    tombstone_set_root=target[1],
                    created_at=mutation.now.astimezone(UTC),
                    allowed=self._allowed,
                    mutate=staged,
                    barrier=mutation.barrier,
                    model_pass_fds=writer.child_descriptors,
                )
            # flock conversion is not an atomic upgrade. The writer mutex
            # serializes current writers; reject an out-of-protocol pointer move.
            current, current_legacy = self._current_or_legacy()
            if (None if current is None else current.generation_id) != (
                None if parent is None else parent.generation_id
            ) or current_legacy != legacy:
                raise GenerationMutationError("EFFECT_PRIOR_STALE")
            self._require_authority(parent, mutation.authority, target)
            if mutation.hooks is not None:
                mutation.hooks.sealed(generation)
            if mutation.authority.activate:
                self._activate(GenerationActivation(mutation, generation, parent, legacy))
            if len(values) != 1:
                raise GenerationMutationError("GENERATION_MUTATION_INCOMPLETE")
            return GenerationMutationResult(generation, values[0], parent)

    def _activate[T](self, activation: GenerationActivation[T]) -> None:
        mutation = activation.mutation
        generation = activation.generation
        if mutation.hooks is not None:
            mutation.hooks.switching(generation)
        if activation.legacy is not None and self.store.active_link.is_dir():
            retired = self.store.retired / ".legacy-active"
            os.replace(self.store.active_link, retired)
            directory_fsync(self.store.share_root)
        try:
            self.store.activate(
                generation,
                activation.parent,
                mutation.now,
                barrier=mutation.barrier,
                lock_held=True,
            )
        except (OSError, RuntimeError, ValueError):
            retired = self.store.retired / ".legacy-active"
            if not self.store.active_link.is_symlink() and retired.is_dir():
                os.replace(retired, self.store.active_link)
                directory_fsync(self.store.share_root)
            raise
        retired = self.store.retired / ".legacy-active"
        if retired.exists():
            shutil.rmtree(retired)
            directory_fsync(self.store.retired)
        if mutation.hooks is not None:
            mutation.hooks.activated(generation)
