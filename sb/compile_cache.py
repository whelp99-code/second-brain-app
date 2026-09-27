"""Weakly owned compile context, isolated by ledger identity and lifetime."""

import weakref


class BodyCache[Owner]:
    """Bodies belong to one live ledger instance, never a recycled object id."""

    def __init__(self) -> None:
        self._data: dict[int, tuple[weakref.ReferenceType[Owner], dict[str, str]]] = {}

    def get(self, ledger: Owner, page_id: str) -> str:
        entry = self._data.get(id(ledger))
        if entry is None or entry[0]() is not ledger:
            return ""
        return entry[1].get(page_id, "")

    def put(self, ledger: Owner, page_id: str, body: str) -> None:
        key = id(ledger)
        entry = self._data.get(key)
        if entry is None or entry[0]() is not ledger:
            def discard(reference: weakref.ReferenceType[Owner]) -> None:
                current = self._data.get(key)
                if current is not None and current[0] is reference:
                    del self._data[key]

            try:
                reference = weakref.ref(ledger, discard)
            except TypeError:
                # Non-weak-referenceable implementations can supply explicit
                # existing_bodies/pages; retaining them globally is unsafe.
                return
            bucket: dict[str, str] = {}
            entry = (reference, bucket)
            self._data[key] = entry
        entry[1][page_id] = body

