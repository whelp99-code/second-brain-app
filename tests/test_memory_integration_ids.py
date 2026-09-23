import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from sb.scoped_write_request import parse_scoped_write_request

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts/memory-integration-ids-v1.json"
SCOPED_WRITE_PATH = Path(__file__).parent / "fixtures/scoped_write_request_v4.json"
DOMAIN = b"orca-jarvis/memory-integration-ids/v1\0"
SCOPED_DOMAIN = b"orca-jarvis/memory-scoped-write-request/v4\0"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_contract() -> dict[str, object]:
    loaded = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError("memory-integration-ids contract must be an object")
    return loaded


def _golden(contract: dict[str, object]) -> dict[str, object]:
    golden = contract["golden"]
    if not isinstance(golden, dict):
        raise TypeError("golden envelope must be an object")
    return golden


def test_golden_envelope_digest_matches_contract() -> None:
    contract = _load_contract()
    golden = _golden(contract)
    digest = "sha256:" + hashlib.sha256(DOMAIN + _canonical(golden)).hexdigest()
    assert digest == contract["expected_digest"]
    assert _sha256_file(CONTRACT_PATH) == CONTRACT_PATH.with_suffix(".json.sha256").read_text(encoding="utf-8").strip()


def test_receipt_id_is_retract_digest_of_upload_id() -> None:
    golden = _golden(_load_contract())
    upload_id = golden["upload_id"]
    receipt_id = golden["receipt_id"]
    assert isinstance(upload_id, str) and isinstance(receipt_id, str)
    assert hashlib.sha256(f"retract\0{upload_id}".encode()).hexdigest() == receipt_id


def test_id_owners_and_encodings_are_machine_tokens() -> None:
    contract = _load_contract()
    semantics = contract["semantics"]
    assert isinstance(semantics, dict)
    expected_owners = {
        "attempt_id": "jarvis",
        "fence": "second_brain",
        "operation_id": "jarvis",
        "receipt_id": "second_brain",
        "request_id": "jarvis",
        "upload_id": "phone_history",
    }
    for field, owner in expected_owners.items():
        row = semantics[field]
        assert isinstance(row, dict)
        assert row["owner"] == owner
    golden = _golden(contract)
    assert str(golden["operation_id"]).startswith("memop:v1:")
    assert str(golden["attempt_id"]).startswith("memattempt:pos:v2:")
    assert str(golden["request_id"]).startswith("memreq:scoped:v4:")
    assert len(str(golden["upload_id"])) == 64
    fence = golden["fence"]
    assert isinstance(fence, dict)
    assert fence["dispatch_fence"] == 1
    assert fence["tombstone_sequence"] == 0


def test_jarvis_and_python_share_scoped_write_fixture_bytes() -> None:
    contract = _load_contract()
    assert _sha256_file(SCOPED_WRITE_PATH) == contract["scoped_write_golden_sha256"]
    request = json.loads(SCOPED_WRITE_PATH.read_text(encoding="utf-8"))
    base = {k: v for k, v in request.items() if k not in {"request_digest", "request_id"}}
    digest = "sha256:" + hashlib.sha256(SCOPED_DOMAIN + _canonical(base)).hexdigest()
    assert digest == request["request_digest"]
    assert request["request_id"] == "memreq:scoped:v4:" + digest[7:]
    assert request["request_id"] == _golden(contract)["request_id"]
    parsed = parse_scoped_write_request(
        request,
        now=datetime.fromisoformat(request["created_at"]),
        expected_provider="provider:fixture",
    )
    assert parsed.request_digest == digest


def _reseal(request: dict[str, object]) -> dict[str, object]:
    base = {k: v for k, v in request.items() if k not in {"request_digest", "request_id"}}
    digest = "sha256:" + hashlib.sha256(SCOPED_DOMAIN + _canonical(base)).hexdigest()
    request["request_digest"] = digest
    request["request_id"] = "memreq:scoped:v4:" + digest[7:]
    return request


@pytest.mark.parametrize(
    "field",
    ["grants", "permissions", "roles", "scopes"],
)
def test_client_cannot_self_assign_request_permissions(field: str) -> None:
    request = json.loads(SCOPED_WRITE_PATH.read_text(encoding="utf-8"))
    request[field] = ["write"]
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        parse_scoped_write_request(
            _reseal(request),
            now=datetime.fromisoformat(str(request["created_at"])),
            expected_provider="provider:fixture",
        )


def test_client_cannot_set_writes_authorized_true() -> None:
    request = json.loads(SCOPED_WRITE_PATH.read_text(encoding="utf-8"))
    preparation = request["preparation"]
    assert isinstance(preparation, dict)
    preparation["writes_authorized"] = True
    with pytest.raises(ValueError, match="SCOPED_WRITE_REQUEST_INVALID"):
        parse_scoped_write_request(
            _reseal(request),
            now=datetime.fromisoformat(str(request["created_at"])),
            expected_provider="provider:fixture",
        )
