"""Readiness keeps the independently verified receipt intact on the wire."""

from sb.backup_verification import verify_backup
from sb.config import Config
from sb.effect_values import is_json_object
from sb.readiness import readiness
from tests.json_fixtures import parse_object
from tests.test_readiness import backup, configured
from tests.test_web import request, running

__all__ = ["configured"]


def test_readiness_preserves_verified_receipt_fields_and_order(configured: Config) -> None:
    receipt = verify_backup(backup(configured))
    expected = parse_object(receipt.model_dump_json())
    report = readiness(configured)
    actual = report["backup_verification"]
    assert is_json_object(actual)
    assert actual == expected
    assert list(actual) == list(expected)
    actual_identity = actual["archive_identity"]
    expected_identity = expected["archive_identity"]
    assert is_json_object(actual_identity) and is_json_object(expected_identity)
    assert list(actual_identity) == list(expected_identity)
    assert actual["generation"] is None
    with running(configured) as url:
        code, payload = request(url + "/ready")
    assert code == 200
    assert is_json_object(payload)
    wire_receipt = payload["backup_verification"]
    assert is_json_object(wire_receipt)
    assert wire_receipt == expected
    assert list(wire_receipt) == list(expected)
