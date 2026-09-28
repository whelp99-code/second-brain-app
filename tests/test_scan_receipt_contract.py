"""K2 shape, arithmetic, end-of-source proof, and frozen schema digests."""

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from sb.personal_observation import ObservationError, parse_scan_receipt

CONTRACTS = Path(__file__).parents[1] / "contracts"
SCHEMA = json.loads((CONTRACTS / "scan-receipt-v1.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
FROZEN_DIGESTS = {
    "personal-source-observation-v1.json": "3b580714bb2d14fb03f888b5a3a32dbe882c9f0f4ecbb7caedbebc5701ba3065",
    "scan-receipt-v1.json": "d9c6fb93b95288e6dd8449fb9e8337033b43afd3c46762c18e39313d6695ca01",
}


def receipt(**changes):
    return {
        "scan_id": "scan-1", "source_id": "mail", "account_id": "synthetic-account",
        "started_at": "2026-09-23T00:00:00.000Z", "finished_at": "2026-09-23T00:01:00.000Z",
        "state": "ok", "checkpoint_before": "cursor-1", "checkpoint_after": "cursor-1",
        "scanned": 0, "accepted": 0, "unchanged": 0, "filtered": 0, "quarantined": 0,
        "deferred": 0, "retryable_errors": 0, "permanent_errors": 0,
        "coverage_start": None, "coverage_end": None, "next_scan_at": None,
        "remaining_known": None, "exhausted": False, "budget": 100,
        "upstream_end_evidence": None, **changes,
    }


def test_counts_must_sum_and_state_enum():
    Draft202012Validator.check_schema(SCHEMA)
    valid = receipt(state="partial", scanned=7, accepted=1, unchanged=1, filtered=1,
                    quarantined=1, deferred=1, retryable_errors=1, permanent_errors=1)
    assert parse_scan_receipt(valid).scanned == 7
    VALIDATOR.validate(valid)
    for field in ("accepted", "unchanged", "filtered", "quarantined", "deferred",
                  "retryable_errors", "permanent_errors", "scanned"):
        count = valid[field]
        assert type(count) is int
        invalid = {**valid, field: count + 1}
        with pytest.raises(ObservationError, match="^SCAN_COUNTS_INVALID$"):
            parse_scan_receipt(invalid)
    for state in ("ok", "partial", "failed", "unavailable", "disabled"):
        assert parse_scan_receipt(receipt(state=state)).state == state
        VALIDATOR.validate(receipt(state=state))
    for state in ("accepted", "exhausted", "unknown", "success"):
        with pytest.raises(ObservationError, match="^SCAN_STATE_INVALID$"):
            parse_scan_receipt(receipt(state=state))
        with pytest.raises(ValidationError):
            VALIDATOR.validate(receipt(state=state))


def test_exhausted_requires_upstream_end_evidence():
    end = receipt(exhausted=True, remaining_known=0, upstream_end_evidence="scan-proof:continuation-end")
    assert parse_scan_receipt(end).exhausted
    VALIDATOR.validate(end)
    for changes in (
        {"upstream_end_evidence": None}, {"upstream_end_evidence": ""},
        {"remaining_known": None}, {"remaining_known": 1}, {"state": "disabled"},
        {"state": "unavailable"}, {"state": "partial"}, {"state": "failed"},
        {"scanned": 1, "deferred": 1}, {"scanned": 1, "retryable_errors": 1},
    ):
        invalid = {**end, **changes}
        with pytest.raises(ValueError):
            parse_scan_receipt(invalid)
        with pytest.raises(ValidationError):
            VALIDATOR.validate(invalid)
    assert not parse_scan_receipt(receipt()).exhausted
    assert not parse_scan_receipt(receipt(remaining_known=0)).exhausted


@pytest.mark.parametrize("filename,expected", FROZEN_DIGESTS.items())
def test_sidecar_digest_frozen(filename, expected):
    schema = CONTRACTS / filename
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == expected
    assert schema.with_suffix(".json.sha256").read_text() == f"{expected}\n"


@pytest.mark.parametrize("changes,error", [
    ({"scanned": 2, "accepted": 2, "budget": 1}, "SCAN_BUDGET_EXCEEDED"),
    ({"scanned": -1}, "INTEGER_INVALID"),
    ({"accepted": True}, "INTEGER_INVALID"),
    ({"budget": 0.0}, "INTEGER_INVALID"),
    ({"remaining_known": -1}, "INTEGER_INVALID"),
    ({"budget": 9007199254740992}, "INTEGER_INVALID"),
    ({"finished_at": "2026-09-22T00:00:00.000Z"}, "SCAN_TIME_INVALID"),
    ({"started_at": "2026-02-30T00:00:00.000Z"}, "TIME_INVALID"),
    ({"coverage_start": "2026-09-22T00:00:00.000Z"}, "SCAN_COVERAGE_INVALID"),
    ({"coverage_start": "2026-09-23T00:00:00.000Z",
      "coverage_end": "2026-09-22T00:00:00.000Z"}, "SCAN_COVERAGE_INVALID"),
    ({"state": "disabled", "checkpoint_after": "cursor-2"}, "SCAN_INACTIVE_PROGRESS"),
    ({"state": "unavailable", "scanned": 1, "accepted": 1}, "SCAN_INACTIVE_PROGRESS"),
    ({"exhausted": 1}, "BOOLEAN_INVALID"),
    ({"unknown": True}, "FIELDS_INVALID"),
])
def test_budget_time_and_checkpoint_invariants(changes, error):
    with pytest.raises(ObservationError, match=f"^{error}$"):
        parse_scan_receipt(receipt(**changes))


def test_unchanged_scan_is_a_new_receipt_not_exhaustion_or_publication():
    first = parse_scan_receipt(receipt(scan_id="scan-1", scanned=4, accepted=4))
    second = parse_scan_receipt(receipt(scan_id="scan-2", scanned=4, unchanged=4))
    assert second.scan_id != first.scan_id
    assert second.accepted == 0 and second.unchanged == 4
    assert second.state == "ok" and not second.exhausted
    assert second.checkpoint_before == second.checkpoint_after
    assert parse_scan_receipt(json.loads(second.canonical_bytes())) == second
    with pytest.raises(FrozenInstanceError):
        second.__setattr__("exhausted", True)
    assert "searchable" not in second.as_dict()
