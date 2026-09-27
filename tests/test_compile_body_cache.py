"""Cached context must never survive its owning ledger or cross identities."""

import gc
import weakref

import pytest

import sb.compile_cache as cache_module
from sb.compile_cache import BodyCache


class LedgerIdentity:
    """A weak-referenceable identity; the cache never invokes ledger methods."""


class TrackedBody(str):
    """Observe cached body lifetime without inspecting cache implementation."""


def test_reused_identity_does_not_return_another_ledgers_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reused_id(_value: LedgerIdentity) -> int:
        return 7

    monkeypatch.setattr(cache_module, "id", reused_id, raising=False)
    cache = BodyCache[LedgerIdentity]()
    first = LedgerIdentity()
    second = LedgerIdentity()
    cache.put(first, "page", "private first ledger")
    assert cache.get(first, "page") == "private first ledger"
    assert cache.get(second, "page") == ""
    cache.put(second, "page", "second ledger")
    del first
    _ = gc.collect()
    assert cache.get(second, "page") == "second ledger"


def test_cache_does_not_retain_ledger_or_body_after_collection() -> None:
    cache = BodyCache[LedgerIdentity]()
    ledger = LedgerIdentity()
    body = TrackedBody("private body")
    reference = weakref.ref(ledger)
    body_reference = weakref.ref(body)
    cache.put(ledger, "page", body)
    del ledger, body
    _ = gc.collect()
    assert reference() is None
    assert body_reference() is None


def test_non_weak_referenceable_owner_does_not_cache_body() -> None:
    cache = BodyCache[int]()
    cache.put(7, "page", "private body")
    assert cache.get(7, "page") == ""
