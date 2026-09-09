"""Validate a request-bound decision from a trusted JARVIS verifier channel."""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sb.effect_values import parse_instant
from sb.scoped_write_request import ScopedWriteRequest

_KEYS = frozenset({"kind", "outbox_id", "dispatch_fence", "provider_instance_id",
    "request_id", "request_digest", "scope_digest", "checked_at", "valid_until"})


@dataclass(frozen=True, slots=True)
class ScopedProviderDecision:
    outbox_id: str
    dispatch_fence: int
    checked_at: datetime
    valid_until: datetime


def validate_scoped_provider_decision(value: object, request: ScopedWriteRequest, *,
    started: datetime, now: datetime) -> ScopedProviderDecision:
    """The trusted channel authenticates the sender; hashes do not do so.

    Call with the clock sampled immediately before and after that channel call.
    A cached/pre-call decision, backward clock, expiry, extra fields, or another
    request must not authorize admission/execution. Reinvoke the verifier for
    every authority check; the returned decision is not a reusable grant.
    """
    try:
        if not isinstance(value, dict):
            raise TypeError
        data = cast(dict[str, object], value)
        if (frozenset(data) != _KEYS
            or data["kind"] != "current_scoped_dispatch"
            or data["provider_instance_id"] != request.provider_instance_id
            or data["request_id"] != request.request_id
            or data["request_digest"] != request.request_digest
            or data["scope_digest"] != request.preparation.identity.identity_digest):
            raise ValueError
        outbox = data["outbox_id"]
        fence = data["dispatch_fence"]
        if (not isinstance(outbox, str) or re.fullmatch(r"memout:scoped:v4:[0-9a-f]{64}", outbox) is None
            or type(fence) is not int or not 1 <= fence <= 9007199254740991):
            raise ValueError
        checked_raw, until_raw = data["checked_at"], data["valid_until"]
        if not isinstance(checked_raw, str) or not isinstance(until_raw, str):
            raise TypeError
        checked, until = parse_instant(checked_raw), parse_instant(until_raw)
        if (started.tzinfo is None or now.tzinfo is None or now < started
            or not started <= checked <= now < until <= request.expires_at):
            raise ValueError
        return ScopedProviderDecision(outbox, fence, checked, until)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("SCOPED_PROVIDER_DECISION_INVALID") from exc
