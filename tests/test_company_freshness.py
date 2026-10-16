from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from sb.company_freshness import (
    MAX_SAFE_INTEGER,
    Checkpoint,
    CompanyFreshnessProvider,
    FinishProgressRequest,
    FinishProgressResponse,
    FreshnessProviderConfig,
    FreshnessScope,
    FreshnessWireError,
    ProgressOperation,
    ReadFreshnessRequest,
    ReadFreshnessResponse,
    ReserveProgressRequest,
    ReserveProgressResponse,
    StoreHeads,
    StoreProgress,
    UnconfiguredCompanyFreshnessProvider,
    provider_from_config,
    require_freshness,
)
from sb.company_memory_authority import CompanyAuthorityRejected
from sb.effect_values import strict_loads

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "company-approver"
    / "company-approver-v2.test-only.json"
)
_DIGEST = "sha256:" + ("ab" * 32)
_SCOPE = FreshnessScope(
    provider_instance_id="provider:TEST_ONLY",
    workspace_id="11111111-1111-4111-8111-111111111111",
)


def test_public_company_db_configuration_cases() -> None:
    extension = strict_loads(
        _FIXTURE.with_name("company-db-freshness-v1.test-only.json").read_bytes(),
        1_048_576,
    )
    assert isinstance(extension, dict)
    cases = extension["configuration_cases"]
    assert isinstance(cases, list) and cases
    for case in cases:
        assert isinstance(case, dict)
        if case["valid"] is True:
            config = FreshnessProviderConfig.model_validate(case["config"], strict=True)
            assert config.model_dump(mode="json") == case["config"]
        else:
            with pytest.raises(ValidationError):
                _ = FreshnessProviderConfig.model_validate(case["config"], strict=True)
    actors = extension["actor_operations"]
    assert isinstance(actors, dict)
    operations = TypeAdapter[ProgressOperation](ProgressOperation)
    for values in actors.values():
        assert isinstance(values, list) and values
        for value in values:
            assert operations.validate_python(value, strict=True) == value


def _store() -> StoreProgress:
    return StoreProgress(
        receipt_sequence=1,
        receipt_root=_DIGEST,
        terminal_sequence=2,
        terminal_root=_DIGEST,
        deletion_sequence=3,
        deletion_root=_DIGEST,
    )


def _checkpoint(*, epoch: int = 1) -> Checkpoint:
    store = _store()
    return Checkpoint(
        operational_epoch=epoch,
        approval_policy_version=1,
        approval_binding_digest=_DIGEST,
        revocation_sequence=0,
        revocation_root=_DIGEST,
        stores=StoreHeads(jarvis=store, second_brain=store),
        intent_sequence=0,
        intent_root=_DIGEST,
    )


def _read(
    challenge: str = "challenge-1",
    observed: Checkpoint | None = None,
) -> ReadFreshnessRequest:
    return ReadFreshnessRequest(
        schema_version=2,
        scope=_SCOPE,
        installation_id="install-1",
        challenge=challenge,
        observed_checkpoint=observed,
    )


def _reserve() -> ReserveProgressRequest:
    return ReserveProgressRequest(
        schema_version=2,
        scope=_SCOPE,
        operation_id=_DIGEST,
        operation="accept",
        expected_checkpoint=_checkpoint(),
        event_digest=_DIGEST,
        challenge="challenge-1",
    )


def _finish() -> FinishProgressRequest:
    return FinishProgressRequest(
        schema_version=2,
        scope=_SCOPE,
        operation_id=_DIGEST,
        reservation_id="reservation-1",
        expected_checkpoint=_checkpoint(),
        evidence_digest=_DIGEST,
        terminal_state="accepted",
        challenge="challenge-1",
    )


class _ScriptedProvider:
    response: ReadFreshnessResponse | Exception
    calls: int

    def __init__(self, response: ReadFreshnessResponse | Exception) -> None:
        self.response = response
        self.calls = 0

    def read_freshness(self, request: ReadFreshnessRequest) -> ReadFreshnessResponse:
        del request
        self.calls += 1
        response = self.response
        if isinstance(response, Exception):
            raise response
        return response

    def reserve_progress(
        self,
        request: ReserveProgressRequest,
    ) -> ReserveProgressResponse | FreshnessWireError:
        del request
        raise AssertionError("reserve is outside this script")

    def finish_progress(
        self,
        request: FinishProgressRequest,
    ) -> FinishProgressResponse | FreshnessWireError:
        del request
        raise AssertionError("finish is outside this script")


def _labeled_json(text: str, label: str) -> str:
    key = f'"{label}": '
    start = text.index(key) + len(key)
    while text[start].isspace():
        start += 1
    if text[start] != "{":
        raise TypeError("labeled fixture value must be an object")
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            escaped = char == "\\" and not escaped
            in_string = not (char == '"' and not escaped)
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise TypeError("labeled fixture object did not close")


def test_fixture_config_and_error_are_exact() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    config = FreshnessProviderConfig.model_validate_json(
        _labeled_json(text, "freshness_provider"),
    )
    error = FreshnessWireError.model_validate_json(
        _labeled_json(text, "expected_unconfigured_error"),
    )
    assert config.model_dump() == {"schema_version": 2, "kind": "unconfigured"}
    assert error.model_dump() == {
        "schema_version": 2,
        "outcome": "error",
        "code": "COMPANY_FRESHNESS_REQUIRED",
    }


def test_config_rejects_other_kinds_and_ignores_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SB_FRESHNESS_KIND", "ready")
    monkeypatch.setenv("SB_FRESHNESS_PROVIDER", "memory")
    with pytest.raises(ValidationError):
        _ = FreshnessProviderConfig.model_validate({"schema_version": 2, "kind": "memory"})
    provider = provider_from_config(
        FreshnessProviderConfig(schema_version=2, kind="unconfigured"),
    )
    assert isinstance(provider, UnconfiguredCompanyFreshnessProvider)
    assert provider.read_freshness(_read()).status == "unavailable"


def test_unconfigured_read_echoes_scope_and_never_ready() -> None:
    provider: CompanyFreshnessProvider = UnconfiguredCompanyFreshnessProvider()
    first = provider.read_freshness(_read("challenge-a"))
    other = FreshnessScope(
        provider_instance_id="provider:OTHER",
        workspace_id="22222222-2222-4222-8222-222222222222",
    )
    second = provider.read_freshness(_read("challenge-b").model_copy(update={"scope": other}))
    assert first.status == "unavailable"
    assert first.checkpoint is None
    assert first.scope == _SCOPE
    assert first.challenge == "challenge-a"
    assert second.challenge == "challenge-b"
    assert second.scope == other
    assert first.model_dump()["status"] != "ready"
    assert second.model_dump()["status"] != "ready"


def test_unconfigured_reserve_and_finish_match_fixture_and_write_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = FreshnessWireError.model_validate_json(
        _labeled_json(_FIXTURE.read_text(encoding="utf-8"), "expected_unconfigured_error"),
    ).model_dump()
    monkeypatch.chdir(tmp_path)
    provider = UnconfiguredCompanyFreshnessProvider()
    reserved = provider.reserve_progress(_reserve())
    finished = provider.finish_progress(_finish())
    assert reserved.model_dump() == fixture
    assert finished.model_dump() == fixture
    assert reserved.outcome == "error"
    assert list(tmp_path.iterdir()) == []


def test_checkpoint_and_progress_validation() -> None:
    with pytest.raises(ValidationError):
        _ = StoreProgress.model_validate({**_store().model_dump(), "receipt_sequence": -1})
    with pytest.raises(ValidationError):
        _ = StoreProgress.model_validate(
            {**_store().model_dump(), "receipt_sequence": MAX_SAFE_INTEGER + 1},
        )
    with pytest.raises(ValidationError):
        _ = Checkpoint.model_validate({**_checkpoint().model_dump(), "operational_epoch": 0})
    with pytest.raises(ValidationError):
        _ = Checkpoint.model_validate({**_checkpoint().model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        _ = ReadFreshnessResponse(
            schema_version=2,
            scope=_SCOPE,
            challenge="challenge-1",
            status="ready",
            checkpoint=None,
        )
    with pytest.raises(ValidationError):
        _ = ReadFreshnessResponse(
            schema_version=2,
            scope=_SCOPE,
            challenge="challenge-1",
            status="unavailable",
            checkpoint=_checkpoint(),
        )
    with pytest.raises(ValidationError):
        _ = ReserveProgressResponse(
            schema_version=2,
            scope=_SCOPE,
            challenge="challenge-1",
            outcome="conflict",
            checkpoint=_checkpoint(),
            reservation_id="reservation-1",
        )
    with pytest.raises(ValidationError):
        _ = FinishProgressResponse(
            schema_version=2,
            scope=_SCOPE,
            challenge="challenge-1",
            outcome="conflict",
            checkpoint=_checkpoint(),
        )
    with pytest.raises(ValidationError):
        _ = FinishProgressResponse.model_validate(
            {
                "schema_version": 2,
                "scope": _SCOPE.model_dump(),
                "challenge": "challenge-1",
                "outcome": "recorded",
                "checkpoint": _checkpoint().model_dump(),
                "reservation_id": "reservation-1",
            },
        )


def test_require_freshness_rejects_unconfigured_without_cache() -> None:
    provider = UnconfiguredCompanyFreshnessProvider()
    request = _read(observed=_checkpoint())
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = require_freshness(provider, request)
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = require_freshness(provider, request)


def test_require_freshness_accepts_only_matching_observed_echo() -> None:
    from tests.company_approver_test_freshness import TestOnlyMemoryFreshnessProvider

    observed = _checkpoint()
    provider = TestOnlyMemoryFreshnessProvider(_SCOPE, observed)
    bound: CompanyFreshnessProvider = provider
    assert require_freshness(bound, _read(observed=observed)) == observed
    reserved = provider.reserve_progress(_reserve())
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_PROGRESS_UNCERTAIN"):
        _ = require_freshness(bound, _read(observed=provider.checkpoint))
    recorded = provider.finish_progress(
        _finish().model_copy(
            update={
                "expected_checkpoint": provider.checkpoint,
                "reservation_id": reserved.reservation_id,
            },
        ),
    )
    assert recorded.outcome == "recorded"
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_OPERATIONAL_ROLLBACK"):
        _ = require_freshness(bound, _read(observed=observed))


def test_require_freshness_maps_mismatch_timeout_and_oserror() -> None:
    observed = _checkpoint()
    mismatch = ReadFreshnessResponse(
        schema_version=2,
        scope=_SCOPE,
        challenge="challenge-1",
        status="mismatch",
        checkpoint=None,
    )
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_OPERATIONAL_ROLLBACK"):
        _ = require_freshness(_ScriptedProvider(mismatch), _read(observed=observed))
    diverged = ReadFreshnessResponse(
        schema_version=2,
        scope=_SCOPE,
        challenge="challenge-1",
        status="ready",
        checkpoint=_checkpoint(epoch=2),
    )
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_OPERATIONAL_ROLLBACK"):
        _ = require_freshness(_ScriptedProvider(diverged), _read(observed=observed))
    swapped = ReadFreshnessResponse(
        schema_version=2,
        scope=FreshnessScope(
            provider_instance_id="provider:OTHER",
            workspace_id="22222222-2222-4222-8222-222222222222",
        ),
        challenge="other-challenge",
        status="ready",
        checkpoint=observed,
    )
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = require_freshness(_ScriptedProvider(swapped), _read(observed=observed))
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = require_freshness(_ScriptedProvider(TimeoutError("slow")), _read(observed=observed))
    with pytest.raises(CompanyAuthorityRejected, match="COMPANY_FRESHNESS_REQUIRED"):
        _ = require_freshness(_ScriptedProvider(OSError("down")), _read(observed=observed))
