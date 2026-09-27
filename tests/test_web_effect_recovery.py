"""Local owner receipts retry the admitted effect, including a lost HTTP result."""
from datetime import datetime
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from sb import owner_effects
from sb.effect_values import JsonObject, is_json_object
from sb.erasure import ErasureEngine, ErasurePlan
from sb.request_store import RequestStore
from tests.test_web import _request, _running
from tests.test_web_lifecycle import PAGE, URL, ready


def payload_for(page: object, content: str) -> JsonObject:
    assert isinstance(page, dict) and is_json_object(page)
    records = page["records"]
    assert isinstance(records, list) and records
    row = records[0]
    assert isinstance(row, dict) and is_json_object(row)
    return {"receipt": page["receipt"], "record_id": row["record_id"], "content": content}


@pytest.mark.parametrize("failure", ["before_apply", "after_activation"])
def test_same_receipt_resumes_and_scrubs_pending_correction(
    tmp_path: Path, monkeypatch: MonkeyPatch, failure: str,
) -> None:
    config, root = ready(tmp_path)
    replacement = "M13RECOVERY corrected appointment."
    failed = False
    apply = ErasureEngine.apply_owner
    save = owner_effects._save

    def fail_apply(engine: ErasureEngine, root: Path, plan: ErasurePlan,
                   now: datetime) -> tuple[str, ...]:
        nonlocal failed
        if failure == "before_apply" and not failed:
            failed = True
            raise RuntimeError("injected before effect")
        return apply(engine, root, plan, now)

    def fail_save(path: Path, effect: owner_effects.OwnerEffect) -> None:
        nonlocal failed
        if failure == "after_activation" and effect.result is not None and not failed:
            failed = True
            raise RuntimeError("injected lost result")
        return save(path, effect)

    monkeypatch.setattr(ErasureEngine, "apply_owner", fail_apply)
    monkeypatch.setattr(owner_effects, "_save", fail_save)
    with _running(config) as base:
        _, page = _request(base + URL)
        payload = payload_for(page, replacement)
        status, _ = _request(base + URL + "/correct", method="POST", payload=payload)
        assert status == 500 and failed
        status, result = _request(base + URL + "/correct", method="POST", payload=payload)
        assert status == 200 and isinstance(result, dict) and is_json_object(result)
        assert result["corrected"] == PAGE
        assert _request(base + URL + "/correct", method="POST", payload=payload) == (200, result)
        assert _request(base + URL)[0] == 200
    assert replacement in (root / (PAGE + ".md")).read_text()
    assert all(replacement not in file.read_text() for file in
               (Path(config.state_root) / "owner-effects").glob("*.json"))
    store = RequestStore(Path(config.request_root))
    try:
        assert store.verified_tombstone_snapshot().sequence == 1
    finally:
        store.close()


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_effect_requires_auth_and_current_page_receipt(
    tmp_path: Path, monkeypatch: MonkeyPatch, operation: str,
) -> None:
    config, _ = ready(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "owner-test-token")
    with _running(config) as base:
        endpoint = base + URL + "/" + operation
        assert _request(endpoint, method="POST", payload={})[0] == 401
        assert _request(endpoint, method="POST", payload={}, token="owner-test-token") == (
            409, {"error": "EFFECT_RECEIPT_REQUIRED"})
        _, page = _request(base + URL, token="owner-test-token")
        payload = payload_for(page, "replacement")
        receipt = payload["receipt"]
        assert isinstance(receipt, dict)
        payload["receipt"] = {**receipt, "page_content_digest": "sha256:" + "0" * 64}
        assert _request(endpoint, method="POST", payload=payload, token="owner-test-token") == (
            409, {"error": "EFFECT_PRIOR_STALE"})
    store = RequestStore(Path(config.request_root))
    try:
        assert store.tombstone_high_water()[0] == 0
    finally:
        store.close()
