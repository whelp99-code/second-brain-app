"""Ledger and pending-output contracts shared by compile execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from sb.contracts import PageSpec, Unit
from sb.llm import LLMClient
from sb.security import SourceAccessReader
from sb.store import Derivation, DerivationOutput, UnitProvenance


class CompileLedger(SourceAccessReader, Protocol):
    """Ledger derivation surface used by compile. Matches sb.store.ledger.Ledger."""

    def get_derivation(self, key: str) -> Derivation | None: ...

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None: ...

    def mark_running(self, key: str, run_id: str) -> None: ...

    def mark_done(self, key: str, output: DerivationOutput) -> None: ...

    def mark_failed(self, key: str, error: str) -> None: ...

    def requeue_failed(self, key: str, *, max_attempts: int | None = None) -> bool: ...

    def provenance_for_unit(self, unit_id: str) -> UnitProvenance | None: ...


@dataclass(frozen=True, slots=True)
class PendingCompile:
    """A generated page whose derivation is finalized only after durable vault write."""

    page: PageSpec
    key: str
    output: DerivationOutput
    input_sources: tuple[tuple[str, str], ...] = ()
    untracked_context: bool = True

COMPILE_STAGE: Final = "compile"
COMPILE_RUN_ID: Final = "compile"


@dataclass(frozen=True, slots=True)
class PageJob:
    page_id: str
    key: str
    units: tuple[Unit, ...]


@dataclass(frozen=True, slots=True)
class CompileContext:
    ledger: CompileLedger
    llm: LLMClient
    template: str
    existing_bodies: Mapping[str, str]
    existing_pages: Mapping[str, PageSpec]
    prompt_version: str
    model_id: str
