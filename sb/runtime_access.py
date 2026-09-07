"""Shared desktop generation reads and explicit mutations."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sb.config import Config
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)


@contextmanager
def read_root(config: Config) -> Generator[Path, None, None]:
    root = Path(config.vault_root)
    if not root.is_symlink():
        yield root
        return
    service = GenerationMutationService.from_config(config)
    try:
        with service.store.pin():
            yield service.store.active().root
    finally:
        service.close()


def mutate_root[T](config: Config, operation: GenerationOperation, apply: Callable[[Path], T]) -> T:
    root = Path(config.vault_root)
    if not root.is_symlink() and "share_root" not in config.raw:
        return apply(root)
    service = GenerationMutationService.from_config(config)
    try:
        return service.mutate(GenerationMutation(
            mutation_id=f"desktop:{operation.value}:{uuid4().hex}",
            operation=operation, now=datetime.now(UTC),
            authority=GenerationAuthority(None, None), apply=apply,
        )).value
    finally:
        service.close()
