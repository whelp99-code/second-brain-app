"""Cached context must never survive its owning ledger or cross identities."""

import gc
import weakref

import sb.compile as compiler
from sb.store import Derivation, DerivationOutput


class LedgerIdentity:
    def get_derivation(self, key: str) -> Derivation | None:
        return None

    def ensure_derivation(self, key: str, stage: str, run_id: str) -> None:
        pass

    def mark_running(self, key: str, run_id: str) -> None:
        pass

    def mark_done(self, key: str, output: DerivationOutput) -> None:
        pass

    def mark_failed(self, key: str, error: str) -> None:
        pass

    def requeue_failed(self, key: str, *, max_attempts: int | None = None) -> bool:
        del key, max_attempts
        return False


def test_reused_identity_does_not_return_another_ledgers_body(monkeypatch):
    monkeypatch.setattr(compiler, "id", lambda _value: 7, raising=False)
    cache = compiler._BodyCache()
    first = LedgerIdentity()
    second = LedgerIdentity()
    cache.put(first, "page", "private first ledger")
    assert cache.get(first, "page") == "private first ledger"
    assert cache.get(second, "page") == ""
    cache.put(second, "page", "second ledger")
    del first
    gc.collect()
    assert cache.get(second, "page") == "second ledger"


def test_cache_does_not_retain_ledger_or_body_after_collection():
    cache = compiler._BodyCache()
    ledger = LedgerIdentity()
    reference = weakref.ref(ledger)
    cache.put(ledger, "page", "private body")
    del ledger
    gc.collect()
    assert reference() is None
    assert not cache._data
