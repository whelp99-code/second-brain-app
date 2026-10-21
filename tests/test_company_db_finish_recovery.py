"""A prepared finish must recover the same fact, never manufacture one."""

from __future__ import annotations

from pathlib import Path

import pytest

import sb.company_db_freshness as freshness
from sb.company_db_freshness_hash import operation_id_for
from sb.company_freshness import FinishProgressRequest, ReserveProgressRequest
from sb.company_freshness_anchor import AnchorRejected
from tests.test_company_db_freshness import (
    PROVIDER_SCOPE,
    RECEIPT_BINDING,
    freshness_read,
    insert_receipt,
    provider_at,
)


@pytest.mark.parametrize("boundary", ["witness", "extend", "publication"])
@pytest.mark.parametrize("recovery_crash", [False, True])
def test_original_finish_recovers_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    recovery_crash: bool,
) -> None:
    provider = provider_at(tmp_path)
    head = provider.read_freshness(freshness_read(provider)).checkpoint
    assert head is not None
    operation_id = operation_id_for(
        PROVIDER_SCOPE,
        request_id="finish:recovery",
        command_digest=RECEIPT_BINDING,
        operation="accept",
    )
    reserved = provider.reserve_progress(
        ReserveProgressRequest(
            schema_version=2,
            scope=PROVIDER_SCOPE,
            operation_id=operation_id,
            operation="accept",
            expected_checkpoint=head,
            event_digest=RECEIPT_BINDING,
            challenge="finish:recovery:reserve",
        )
    )
    assert reserved.outcome == "reserved"
    assert reserved.checkpoint is not None and reserved.reservation_id is not None
    request = FinishProgressRequest(
        schema_version=2,
        scope=PROVIDER_SCOPE,
        operation_id=operation_id,
        reservation_id=reserved.reservation_id,
        expected_checkpoint=reserved.checkpoint,
        evidence_digest=insert_receipt(provider.database),
        terminal_state="accepted",
        challenge="finish:recovery:finish",
    )
    extended = provider.anchor.read_value()
    with monkeypatch.context() as fault:

        def fail(*_args: object, **_kwargs: object) -> None:
            raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

        if boundary == "witness":
            fault.setattr(freshness, "append_witness_frame", fail)
        elif boundary == "extend":
            fault.setattr(freshness, "extend_if_needed", fail)
        else:
            fault.setattr(freshness, "_insert_evidence_rows", fail)
        failed = provider.finish_progress(request)
        assert failed.outcome == "error"
    if boundary == "publication":
        assert provider.anchor.read_value() != extended
    else:
        assert provider.anchor.read_value() == extended
    if recovery_crash:
        with monkeypatch.context() as fault:
            def crash(*_args: object, **_kwargs: object) -> None:
                raise AnchorRejected("COMPANY_FRESHNESS_REQUIRED")

            fault.setattr(freshness, "_finish_operation", crash)
            assert provider.finish_progress(request).outcome == "error"
    resumed = provider.finish_progress(request)
    assert resumed.outcome == "already_recorded"
    assert resumed.checkpoint is not None
    final_nv = provider.anchor.read_value()
    assert final_nv != extended
    assert provider.finish_progress(request) == resumed
    assert provider.anchor.read_value() == final_nv
    assert (
        provider.read_freshness(
            freshness_read(provider).model_copy(update={"observed_checkpoint": resumed.checkpoint}),
        ).status
        == "ready"
    )
