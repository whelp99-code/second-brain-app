from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sb.effect_values import JsonObject, JsonValue, format_instant
from sb.scoped_provider_decision import validate_scoped_provider_decision
from sb.scoped_write_request import parse_scoped_write_request
from tests.json_fixtures import parse_object


def material():
    raw = parse_object((Path(__file__).parent / "fixtures/scoped_write_request_v4.json").read_text())
    created_at = raw["created_at"]
    assert isinstance(created_at, str)
    at = datetime.fromisoformat(created_at)
    request = parse_scoped_write_request(raw, now=at, expected_provider="provider:fixture")
    value: JsonObject = {"kind": "current_scoped_dispatch", "outbox_id": "memout:scoped:v4:" + "a" * 64,
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
        setattr(result, 'dispatch_fence', 2)  # noqa: B010


@pytest.mark.parametrize("mode", ["provider", "request", "scope", "outbox", "bool", "float", "overflow",
    "extra", "stale", "future", "expired", "overlong", "rewind", "naive"])
def test_invalid_or_delayed_decision_cannot_authorize(mode: str):
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
        _ = validate_scoped_provider_decision(value, request, started=started, now=now)


def test_live_millisecond_decision_accepts_submillisecond_python_clock():
    request, at, value = material()
    result = validate_scoped_provider_decision(value, request,
        started=at + timedelta(microseconds=100), now=at + timedelta(microseconds=900))
    assert result.checked_at == at


@pytest.mark.parametrize("mode", ["valid", "expired", "rewind", "stale", "denied", "transport"])
def test_authority_reinvokes_channel_and_checks_each_response(mode: str):
    from sb.scoped_provider_decision import create_scoped_provider_authority

    request, at, value = material()
    calls: list[bytes] = []
    current = [at]
    def verify(payload: bytes) -> JsonValue:
        assert isinstance(payload, bytes) and payload == request.canonical
        calls.append(payload)
        if len(calls) == 1:
            return dict(value)
        if mode == "transport":
            raise OSError("channel unavailable")
        if mode == "denied":
            return True
        response = dict(value)
        response["checked_at"] = format_instant(current[0])
        if mode == "expired":
            current[0] = request.expires_at
        elif mode == "rewind":
            current[0] -= timedelta(microseconds=1)
        elif mode == "stale":
            response["checked_at"] = format_instant(at)
        return response
    authorize = create_scoped_provider_authority(verify, clock=lambda: current[0])
    assert authorize(request)
    current[0] += timedelta(milliseconds=1)
    if mode == "transport":
        with pytest.raises(OSError, match="channel unavailable"):
            _ = authorize(request)
    else:
        assert authorize(request) is (mode == "valid")
    assert len(calls) == 2


def test_submillisecond_expiry_and_rewind_are_not_rounded_away():
    request, at, value = material()
    value["valid_until"] = format_instant(at + timedelta(milliseconds=1))
    for started, finished in [(at, at + timedelta(microseconds=1001)),
                             (at + timedelta(microseconds=500), at + timedelta(microseconds=499))]:
        with pytest.raises(ValueError, match="SCOPED_PROVIDER_DECISION_INVALID"):
            _ = validate_scoped_provider_decision(value, request, started=started, now=finished)


@pytest.mark.parametrize("mode", ["valid", "admission_expiry", "execution_expiry"])
def test_composed_channel_gates_real_admission_and_execution(tmp_path: Path, mode: str):
    from sb.request_executor import RequestExecutor
    from sb.request_store import RequestStore
    from sb.scoped_provider_decision import create_scoped_provider_authority
    from sb.scoped_request_acceptance import accept_scoped_request
    from tests.task30_process_harness import executor_config

    request, at, value = material()
    current = [at]
    calls: list[bytes] = []
    def verify(payload: bytes) -> JsonValue:
        assert payload == request.canonical
        calls.append(payload)
        decision = dict(value)
        decision["checked_at"] = format_instant(current[0])
        decision["valid_until"] = format_instant(at + timedelta(milliseconds=1))
        boundary = 2 if mode == "admission_expiry" else 3
        if mode != "valid" and len(calls) == boundary:
            # Request remains valid; only the current policy decision expires
            # while this channel call is in flight.
            current[0] = at + timedelta(milliseconds=1)
        return decision
    authorize = create_scoped_provider_authority(verify, clock=lambda: current[0])
    config = executor_config(tmp_path)
    if mode == "admission_expiry":
        with pytest.raises(ValueError, match="SCOPED_WRITE_AUTHORITY_INVALID"):
            _ = accept_scoped_request(config.request_root, parse_object(request.canonical),
                expected_provider=config.provider_instance_id, clock=lambda: current[0],
                validate_authority=authorize)
        store = RequestStore(config.request_root, scoped_v4=True)
        try:
            assert store.get(request.request_id) is None
        finally:
            store.close()
        return
    accepted = accept_scoped_request(config.request_root, parse_object(request.canonical),
        expected_provider=config.provider_instance_id, clock=lambda: current[0],
        validate_authority=authorize)
    executor = RequestExecutor(config, scoped_authority=authorize)
    try:
        result = executor.apply_once(worker="fixture:composed", now=at)
        if mode == "valid":
            assert result.state == "proved", result
            assert len(calls) == 5
        else:
            assert result.state == "failed" and result.code == "SCOPED_WRITE_AUTHORITY_INVALID"
            assert not executor.generations.active_link.exists()
            stored = executor.store.get(accepted.request_id)
            assert stored is not None
            assert stored.proof_json is None
            assert len(calls) == 3
    finally:
        executor.close()
