"""Cached context must never survive its owning ledger or cross identities."""

import gc
import weakref

import sb.compile as compiler


class LedgerIdentity:
    pass


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
