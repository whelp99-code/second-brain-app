"""HTTP admission of K7 source observations. Loopback only; no sleep."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from sb.config import Config, TomlValue
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, is_json_object
from sb.observation_admission import observation_journal, read, read_body
from sb.vault import init_vault
from tests.json_fixtures import parse_object
from tests.test_web import _request, _running

MANIFEST = {
    "emitter": "mail-fixture",
    "account_id": "synthetic-account",
    "root": "mail://fixture",
    "source_id": "mail",
    "namespace": "personal",
    "source_policy_revision": "policy-v1",
    "external_processing": "local_only",
}


def _observation() -> JsonObject:
    raw = parse_object(
        (Path(__file__).parent / "fixtures" / "personal-observation" / "mail.json").read_bytes()
    )
    observation = raw["observation"]
    assert is_json_object(observation)
    body = dict(observation)
    body["evidence_spans"] = []
    return body


def _object(value: JsonValue) -> JsonObject:
    assert is_json_object(value)
    return value


def _payload() -> bytes:
    return canonical_bytes(_observation())


def _config(root: Path, *, emitters: list[dict[str, str]] | None = None) -> Config:
    raw: dict[str, TomlValue] = {"vault_root": str(root)}
    if emitters is not None:
        raw["observation_emitters"] = _toml_rows(emitters)
    return Config(raw=raw)


def _toml_rows(rows: list[dict[str, str]]) -> list[TomlValue]:
    converted: list[TomlValue] = []
    for row in rows:
        item: dict[str, TomlValue] = {}
        for key, value in row.items():
            item[key] = value
        converted.append(item)
    return converted


def test_post_source_observations_returns_receipt_after_durable_write(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    payload = _payload()
    config = _config(root, emitters=[MANIFEST])
    with _running(config) as base:
        status, body = _request(
            f"{base}/api/source-observations",
            method="POST",
            payload={"emitter": "mail-fixture", "payload_base64": base64.b64encode(payload).decode("ascii")},
        )
    assert status == 201
    assert is_json_object(body)
    receipt_id = body["receipt_id"]
    assert isinstance(receipt_id, str)
    assert body["state"] == "accepted_pending"
    assert body["searchable"] is False
    assert body["state"] != "searchable"
    stored = read(root, receipt_id)
    assert stored is not None
    assert stored.as_dict()["state"] == "accepted_pending"
    assert read_body(root, receipt_id) == payload
    journal = observation_journal(root)
    assert (journal / "bodies" / receipt_id[:2] / receipt_id).is_file()
    assert (journal / "receipts" / receipt_id[:2] / f"{receipt_id}.json").is_file()


def test_get_receipt_state_and_404(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    payload = _payload()
    config = _config(root, emitters=[MANIFEST])
    with _running(config) as base:
        created, body = _request(
            f"{base}/api/source-observations",
            method="POST",
            payload={"emitter": "mail-fixture", "payload_base64": base64.b64encode(payload).decode("ascii")},
        )
        receipt_id_value = _object(body)["receipt_id"]
        assert isinstance(receipt_id_value, str)
        receipt_id = receipt_id_value
        status, fetched = _request(f"{base}/api/source-observations/{receipt_id}")
        missing, missing_body = _request(f"{base}/api/source-observations/{'ab' * 32}")
    assert created == 201
    assert status == 200
    fetched_body = _object(fetched)
    assert fetched_body["state"] == "accepted_pending"
    assert fetched_body["searchable"] is False
    assert missing == 404
    assert missing_body == {"error": "not found"}


def test_unregistered_emitter_403(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    payload = _payload()
    config = _config(root)
    with _running(config) as base:
        status, body = _request(
            f"{base}/api/source-observations",
            method="POST",
            payload={"emitter": "mail-fixture", "payload_base64": base64.b64encode(payload).decode("ascii")},
        )
    assert status == 403
    assert body == {"error": "EMITTER_UNREGISTERED"}
    assert not observation_journal(root).exists()


def test_existing_upload_and_remember_queued_responses_unchanged(tmp_path: Path) -> None:
    root = init_vault(tmp_path / "vault").root
    config = _config(root, emitters=[MANIFEST])
    upload = b"# desktop upload\\nunchanged queue\\n"
    with _running(config) as base:
        remembered_status, remembered = _request(
            f"{base}/api/remember",
            method="POST",
            payload={"title": "queue check", "content": "still an inbox path"},
        )
        upload_status, uploaded = _request(
            f"{base}/api/uploads",
            method="POST",
            payload={
                "filename": "note.md",
                "relative_path": "note.md",
                "device_id": "mac",
                "content_sha256": hashlib.sha256(upload).hexdigest(),
                "content_base64": base64.b64encode(upload).decode("ascii"),
            },
        )
    assert remembered_status == 201
    remembered_body = _object(remembered)
    assert set(remembered_body) == {"inbox_path"}
    inbox_path = remembered_body["inbox_path"]
    assert isinstance(inbox_path, str)
    assert inbox_path.startswith("inbox/")
    assert upload_status == 201
    uploaded_body = _object(uploaded)
    assert uploaded_body["state"] == "queued"
    assert {"upload_id", "state", "inbox_path", "content_sha256"} <= set(uploaded_body)
    assert "accepted_pending" not in uploaded_body.values()
