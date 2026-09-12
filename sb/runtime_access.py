"""Shared desktop generation reads and explicit mutations."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
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
    service = GenerationMutationService.from_config(config, maintenance_only=True)
    try:
        with service.store.pin(f"desktop-read:{uuid4().hex}", datetime.now(UTC)) as pin:
            yield pin.generation.root
    finally:
        service.close()


@contextmanager
def read_config(config: Config) -> Generator[Config, None, None]:
    """Preserve configuration while binding every vault lookup to one reader pin."""
    with read_root(config) as root:
        yield replace(config, raw={**config.raw, "vault_root": str(root)})


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
