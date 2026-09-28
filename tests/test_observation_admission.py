"""K7 file-journal admission. No clock, sleep, network, or live vault."""

import hashlib
import json
from pathlib import Path

import pytest

from sb.config import Config
from sb.effect_values import canonical_bytes
from sb.observation_admission import (
    STATES,
    AdmissionError,
    admit,
    advance,
    is_searchable,
    observation_journal,
    read,
    read_body,
)
from sb.personal_observation import TrustedSourceManifest

MANIFEST = {
    "emitter": "mail-fixture",
    "account_id": "synthetic-account",
    "root": "mail://fixture",
    "source_id": "mail",
    "namespace": "personal",
    "source_policy_revision": "policy-v1",
    "external_processing": "local_only",
}
COMMIT = "a" * 40
GENERATION = "sbgen:v1:" + ("b" * 64)


def _observation(**overrides: object) -> dict[str, object]:
    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "personal-observation" / "mail.json").read_text()
    )
    body = dict(raw["observation"])
    body["evidence_spans"] = []
    body.update(overrides)
    return body


def _payload(**overrides: object) -> bytes:
    return canonical_bytes(_observation(**overrides))


def _config(*rows: dict[str, str]) -> Config:
    return Config(raw={"observation_emitters": [dict(row) for row in rows]})


def _admit(root: Path, payload: bytes | None = None, emitter: str = "mail-fixture"):
    return admit(root, _payload() if payload is None else payload, emitter=emitter, config=_config(MANIFEST))


def test_admit_persists_bytes_and_receipt_before_returning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = _payload()
    seen: dict[str, bool] = {}
    import sb.observation_admission as module

    real = module.os.replace

    def spy(src: Path, dst: Path) -> None:
        real(src, dst)
        if str(dst).endswith(".json"):
            receipt_id = Path(dst).stem
            assert read_body(tmp_path, receipt_id) == payload
            assert read(tmp_path, receipt_id) is not None
            seen["receipt_after_bytes"] = True

    monkeypatch.setattr(module.os, "replace", spy)
    receipt = _admit(tmp_path, payload)
    assert seen["receipt_after_bytes"] is True
    assert receipt.state == "accepted_pending"
    assert read_body(tmp_path, receipt.receipt_id) == payload
    assert read(tmp_path, receipt.receipt_id) == receipt
    journal = observation_journal(tmp_path)
    assert journal == tmp_path.resolve() / ".sb" / "observations"
    assert (journal / "bodies" / receipt.receipt_id[:2] / receipt.receipt_id).is_file()
    assert not (tmp_path / "wiki").exists()


def test_same_key_same_body_returns_same_receipt_after_response_loss(tmp_path: Path):
    payload = _payload()
    first = _admit(tmp_path, payload)
    # The caller never observed `first`; the retry is the only response it gets.
    second = _admit(tmp_path, payload)
    assert second == first
    assert second.idempotency_key == first.observation_id
    assert second.as_dict() == first.as_dict()
    bodies = list((observation_journal(tmp_path) / "bodies").rglob(first.receipt_id))
    assert bodies == [observation_journal(tmp_path) / "bodies" / first.receipt_id[:2] / first.receipt_id]


def test_same_key_different_body_is_conflict(tmp_path: Path):
    first = _admit(tmp_path)
    other = _payload(parser_version="mail-v2", content_sha256="cd" * 32)
    with pytest.raises(AdmissionError, match="^OBSERVATION_CONFLICT$") as caught:
        _admit(tmp_path, other)
    assert caught.value.code == "OBSERVATION_CONFLICT"
    assert read(tmp_path, first.receipt_id) == first
    assert read_body(tmp_path, first.receipt_id) == _payload()
    assert hashlib.sha256(other).hexdigest() != first.payload_sha256


def test_unregistered_emitter_rejected(tmp_path: Path):
    payload = _payload()
    with pytest.raises(AdmissionError, match="^EMITTER_UNREGISTERED$"):
        admit(tmp_path, payload, emitter="mail-fixture", config=Config(raw={}))
    with pytest.raises(AdmissionError, match="^EMITTER_UNREGISTERED$"):
        admit(tmp_path, payload, emitter="other-emitter", config=_config(MANIFEST))
    assert not observation_journal(tmp_path).exists()
    TrustedSourceManifest(**MANIFEST)


def test_states_enum_and_unknown_not_searchable(tmp_path: Path):
    assert STATES == (
        "accepted_pending",
        "processing",
        "published",
        "searchable",
        "failed",
        "rejected",
    )
    assert "unknown" not in STATES
    assert is_searchable("unknown") is False
    assert is_searchable("published") is False
    assert is_searchable("accepted_pending") is False
    assert is_searchable("searchable") is True
    receipt = _admit(tmp_path)
    path = observation_journal(tmp_path) / "receipts" / receipt.receipt_id[:2] / f"{receipt.receipt_id}.json"
    forged = receipt.as_dict()
    forged["state"] = "unknown"
    forged["searchable"] = True
    path.write_bytes(json.dumps(forged, sort_keys=True).encode())
    with pytest.raises(AdmissionError, match="^RECEIPT_UNREADABLE$"):
        read(tmp_path, receipt.receipt_id)
    path.write_text(json.dumps({**receipt.as_dict(), "state": "unknown"}, sort_keys=True), encoding="utf-8")
    loaded = read(tmp_path, receipt.receipt_id)
    assert loaded is not None
    assert loaded.state == "unknown"
    assert loaded.searchable is False
    assert is_searchable(loaded.state) is False
    with pytest.raises(AdmissionError, match="^STATE_INVALID$"):
        advance(tmp_path, receipt.receipt_id, "unknown", proof=COMMIT)


def test_advance_is_monotonic_and_requires_proof_ref(tmp_path: Path):
    receipt = _admit(tmp_path)
    with pytest.raises(AdmissionError, match="^STATE_NOT_MONOTONIC$"):
        advance(tmp_path, receipt.receipt_id, "published", proof=COMMIT)
    with pytest.raises(AdmissionError, match="^PROOF_REQUIRED$"):
        advance(tmp_path, receipt.receipt_id, "processing", proof="")
    processing = advance(tmp_path, receipt.receipt_id, "processing", proof="worker-1")
    assert processing.state == "processing"
    assert processing.searchable is False
    with pytest.raises(AdmissionError, match="^PROOF_INVALID$"):
        advance(tmp_path, receipt.receipt_id, "published", proof="not-a-commit")
    published = advance(tmp_path, receipt.receipt_id, "published", proof=COMMIT)
    assert published.state == "published"
    assert published.proof == COMMIT
    assert is_searchable(published.state) is False
    with pytest.raises(AdmissionError, match="^PROOF_INVALID$"):
        advance(tmp_path, receipt.receipt_id, "searchable", proof="unknown")
    with pytest.raises(AdmissionError, match="^PROOF_INVALID$"):
        advance(tmp_path, receipt.receipt_id, "searchable", proof="0")
    searchable = advance(tmp_path, receipt.receipt_id, "searchable", proof=GENERATION)
    assert searchable.searchable is True
    assert searchable.proofs["published"] == COMMIT
    assert searchable.proofs["searchable"] == GENERATION
    again = advance(tmp_path, receipt.receipt_id, "searchable", proof=GENERATION)
    assert again == searchable
    with pytest.raises(AdmissionError, match="^STATE_NOT_MONOTONIC$"):
        advance(tmp_path, receipt.receipt_id, "processing", proof="worker-1")
    numeric = _admit(tmp_path, _payload(event_id="event-2"))
    advance(tmp_path, numeric.receipt_id, "processing", proof="worker-1")
    advance(tmp_path, numeric.receipt_id, "published", proof="ab" * 32)
    indexed = advance(tmp_path, numeric.receipt_id, "searchable", proof="17")
    assert indexed.searchable is True
    failed = _admit(tmp_path, _payload(event_id="event-3"))
    rejected = advance(tmp_path, failed.receipt_id, "rejected", proof="EMITTER_POLICY")
    assert rejected.searchable is False
    with pytest.raises(AdmissionError, match="^STATE_NOT_MONOTONIC$"):
        advance(tmp_path, failed.receipt_id, "searchable", proof=GENERATION)
