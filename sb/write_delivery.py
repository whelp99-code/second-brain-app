"""Write-tool result when the provider published nothing.

JARVIS reconcile must treat this payload as not delivered. It is not an
uncertain mid-apply failure: no durable request file was published, so the
lane may stop reconciling (outcome code ``NOTHING_WRITTEN``).

Tool error text is strict JSON, one object, no prefix:

* ``written`` is always false
* ``delivery`` is always ``"not_written"``
* ``code`` is ``NOTHING_WRITTEN`` when the failure is not an already-catalogued
  rejection, otherwise the catalogue code is kept and ``cause`` repeats it
* ``retryable`` is false

A successful accept (``kind: accepted``) means a request file was published.
Do not treat transport loss after that accept as ``not_written``.
"""

from __future__ import annotations

from typing import Final

NOTHING_WRITTEN: Final = "NOTHING_WRITTEN"


def not_written_fields(*, cause: str) -> dict[str, object]:
    """Fields every pre-publish write failure must include."""
    return {
        "written": False,
        "delivery": "not_written",
        "cause": cause,
    }
