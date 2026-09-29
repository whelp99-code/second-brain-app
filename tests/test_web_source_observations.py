"""HTTP admission of K7 source observations. Loopback only; no sleep."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import cast

from sb.config import Config
from sb.effect_values import canonical_bytes
from sb.observation_admission import observation_journal, read, read_body
from sb.vault import init_vault
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


def _observation() -> dict[str, object]:
    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "personal-observation" / "mail.json").read_text()
    )
    body = dict(raw["observation"])
    body["evidence_spans"] = []
    return body


def _payload() -> bytes:
    return canonical_bytes(_observation())


def _config(root: Path, *, emitters: list[dict[str, str]] | None = None) -> Config:
    raw: dict[str, object] = {"vault_root": str(root)}
    if emitters is not None:
        raw["observation_emitters"] = emitters
    return Config(raw=raw)


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
    receipt = cast(dict[str, object], body)
    receipt_id = str(receipt["receipt_id"])
    assert receipt["state"] == "accepted_pending"
    assert receipt["searchable"] is False
    assert receipt["state"] != "searchable"
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
        receipt_id = str(cast(dict[str, object], body)["receipt_id"])
        status, fetched = _request(f"{base}/api/source-observations/{receipt_id}")
        missing, missing_body = _request(f"{base}/api/source-observations/{'ab' * 32}")
    assert created == 201
    assert status == 200
    assert cast(dict[str, object], fetched)["state"] == "accepted_pending"
    assert cast(dict[str, object], fetched)["searchable"] is False
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
    assert set(cast(dict[str, object], remembered)) == {"inbox_path"}
    assert str(cast(dict[str, object], remembered)["inbox_path"]).startswith("inbox/")
    assert upload_status == 201
    uploaded_body = cast(dict[str, object], uploaded)
    assert uploaded_body["state"] == "queued"
    assert {"upload_id", "state", "inbox_path", "content_sha256"} <= set(uploaded_body)
    assert "accepted_pending" not in uploaded_body.values()
