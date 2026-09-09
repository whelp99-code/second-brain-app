import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sb.effect_values import format_instant
from sb.scoped_provider_decision import validate_scoped_provider_decision
from sb.scoped_write_request import parse_scoped_write_request


def material():
    raw = json.loads((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    at = datetime.fromisoformat(raw["created_at"])
    request = parse_scoped_write_request(raw, now=at, expected_provider="provider:fixture")
    value = {"kind": "current_scoped_dispatch", "outbox_id": "memout:scoped:v4:" + "a" * 64,
        "dispatch_fence": 1, "provider_instance_id": request.provider_instance_id,
        "request_id": request.request_id, "request_digest": request.request_digest,
        "scope_digest": request.preparation.identity.identity_digest,
        "checked_at": format_instant(at), "valid_until": format_instant(request.expires_at)}
    return request, at, value


def test_live_decision_is_bound_and_frozen():
    request, at, value = material()
    result = validate_scoped_provider_decision(value, request, started=at, now=at)
    assert result.dispatch_fence == 1
    with pytest.raises(FrozenInstanceError):
        result.dispatch_fence = 2


@pytest.mark.parametrize("mode", ["provider", "request", "scope", "outbox", "bool", "float", "overflow",
    "extra", "stale", "future", "expired", "overlong", "rewind", "naive"])
def test_invalid_or_delayed_decision_cannot_authorize(mode):
    request, at, value = material()
    started, now = at, at
    if mode == "provider":
        value["provider_instance_id"] = "provider:other"
    if mode == "request":
        value["request_digest"] = "sha256:" + "b" * 64
    if mode == "scope":
        value["scope_digest"] = "sha256:" + "b" * 64
    if mode == "outbox":
        value["outbox_id"] = "legacy"
    if mode in ("bool", "float", "overflow"):
        value["dispatch_fence"] = {"bool": True, "float": 1.0, "overflow": 9007199254740992}[mode]
    if mode == "extra":
        value["grant"] = True
    if mode == "stale":
        started = now = at + timedelta(milliseconds=1)
    if mode == "future":
        value["checked_at"] = format_instant(at + timedelta(milliseconds=1))
    if mode == "expired":
        now = request.expires_at
    if mode == "overlong":
        value["valid_until"] = format_instant(request.expires_at + timedelta(milliseconds=1))
    if mode == "rewind":
        now = at - timedelta(milliseconds=1)
    if mode == "naive":
        started = at.replace(tzinfo=None)
    with pytest.raises(ValueError, match="SCOPED_PROVIDER_DECISION_INVALID"):
        validate_scoped_provider_decision(value, request, started=started, now=now)
