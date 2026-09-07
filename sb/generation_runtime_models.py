"""Typed generation mutation requests, authority, hooks, and runtime paths."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from pathlib import Path

from sb.config import Config
from sb.generations import Generation


class GenerationMutationError(RuntimeError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@unique
class GenerationOperation(StrEnum):
    INGEST = "ingest"
    COMPILE = "compile"
    BRIEF = "brief"
    RUN = "run"
    INBOX = "inbox"
    REMEMBER = "remember"
    EFFECT = "effect"
    RESTORE = "restore"


@dataclass(frozen=True, slots=True)
class GenerationExpectation:
    generation_id: str
    head: str
    tree: str


@dataclass(frozen=True, slots=True)
class GenerationAuthority:
    expected_base: GenerationExpectation | None
    result_high_water: tuple[int, str] | None
    activate: bool = True
    resume_generation_id: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationMutationHooks:
    sealed: Callable[[Generation], None]
    switching: Callable[[Generation], None]
    activated: Callable[[Generation], None]


@dataclass(frozen=True, slots=True)
class GenerationMutation[T]:
    mutation_id: str
    operation: GenerationOperation
    now: datetime
    authority: GenerationAuthority
    apply: Callable[[Path], T]
    recover: Callable[[Generation], T] | None = None
    hooks: GenerationMutationHooks | None = None
    barrier: Callable[[str], None] | None = None


@dataclass(frozen=True, slots=True)
class GenerationMutationResult[T]:
    generation: Generation
    value: T
    predecessor: Generation | None


@dataclass(frozen=True, slots=True)
class GenerationActivation[T]:
    mutation: GenerationMutation[T]
    generation: Generation
    parent: Generation | None
    legacy: Path | None


@dataclass(frozen=True, slots=True)
class GenerationRuntimePaths:
    active: Path
    state: Path
    share: Path
    requests: Path
    exports: Path


def generation_runtime_paths(config: Config) -> GenerationRuntimePaths:
    """Resolve custom vaults to sibling state while preserving exact production defaults."""
    active = Path(config.vault_root)
    custom_vault = "vault_root" in config.raw
    state = Path(config.state_root) if "state_root" in config.raw or not custom_vault else active.parent / ".state"
    share = Path(config.share_root) if "share_root" in config.raw or not custom_vault else active.parent
    requests = (
        Path(config.request_root)
        if "request_root" in config.raw or not custom_vault
        else state / "requests"
    )
    exports = (
        Path(config.export_root)
        if "export_root" in config.raw or not custom_vault
        else state / "exports"
    )
    if share / "vault" != active:
        raise GenerationMutationError("GENERATION_ACTIVE_PATH_INVALID")
    return GenerationRuntimePaths(active, state, share, requests, exports)
