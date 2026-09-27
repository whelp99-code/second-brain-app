"""Ledger and pending-output contracts shared by compile execution."""

from dataclasses import dataclass
from typing import Protocol

from sb.contracts import PageSpec
from sb.store import Derivation, DerivationOutput


class CompileLedger(Protocol):
    """Ledger derivation surface used by compile. Matches sb.store.ledger.Ledger."""

    def get_derivation(self, key: str) -> Derivation | None: ...

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None: ...

    def mark_running(self, key: str, run_id: str) -> None: ...

    def mark_done(self, key: str, output: DerivationOutput) -> None: ...

    def mark_failed(self, key: str, error: str) -> None: ...

    def requeue_failed(self, key: str, *, max_attempts: int | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class PendingCompile:
    """A generated page whose derivation is finalized only after durable vault write."""

    page: PageSpec
    key: str
    output: DerivationOutput
    input_sources: tuple[tuple[str, str], ...] = ()
    untracked_context: bool = True
