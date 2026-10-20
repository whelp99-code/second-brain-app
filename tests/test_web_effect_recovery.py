"""Local owner receipts retry the admitted effect, including a lost HTTP result."""
import fcntl
import os
import socket
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pytest import MonkeyPatch

from sb import owner_effects
from sb.effect_values import JsonObject, JsonValue, is_json_object
from sb.erasure import ErasureEngine, ErasurePlan
from sb.request_store import RequestStore
from tests.test_web import request, running
from tests.test_web_lifecycle import PAGE, URL, ready


def payload_for(page: JsonValue, content: str) -> JsonObject:
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
    save = owner_effects.save

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
    with running(config) as base:
        _, page = request(base + URL)
        payload = payload_for(page, replacement)
        status, _ = request(base + URL + "/correct", method="POST", payload=payload)
        assert status == 500 and failed
        status, result = request(base + URL + "/correct", method="POST", payload=payload)
        assert status == 200 and isinstance(result, dict) and is_json_object(result)
        assert result["corrected"] == PAGE
        assert request(base + URL + "/correct", method="POST", payload=payload) == (200, result)
        assert request(base + URL)[0] == 200
    assert replacement in (root / (PAGE + ".md")).read_text()
    assert all(replacement not in file.read_text() for file in
               (Path(config.state_root) / "owner-effects").glob("*.json"))
    store = RequestStore(Path(config.request_root))
    try:
        assert store.verified_tombstone_snapshot().sequence == 1
    finally:
        store.close()


def test_owner_effect_does_not_wait_for_blocked_get_socket(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    """Real TCP backpressure must not retain the GET's generation reader lock."""
    config, root = ready(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "owner-test-token")
    # Bound both TCP buffers and exceed their capacity without a client reader.
    monkeypatch.setattr("sb.web._latest_briefing", lambda _root: "x" * (4 * 1024 * 1024))
    entered = threading.Event()
    finished = threading.Event()
    sendall = socket.socket.sendall

    def tracked_sendall(sock: socket.socket, data: bytes, flags: int = 0) -> None:
        if not data.startswith(b'{"briefing":'):
            return sendall(sock, data, flags)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        entered.set()
        try:
            sendall(sock, data, flags)
        finally:
            finished.set()

    monkeypatch.setattr(socket.socket, "sendall", tracked_sendall)
    with running(config) as base:
        _, page = request(base + URL, token="owner-test-token")
        replacement = "M13SOCKET corrected appointment."
        payload = payload_for(page, replacement)
        address = urlsplit(base)
        assert address.hostname is not None and address.port is not None
        with socket.socket() as slow:
            slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            slow.settimeout(5)
            slow.connect((address.hostname, address.port))
            slow.sendall(
                b"GET /api/briefing/latest HTTP/1.0\r\nHost: localhost\r\n"
                b"Authorization: Bearer owner-test-token\r\n\r\n",
            )
            try:
                assert entered.wait(5), "GET never reached its real socket write"
                assert not finished.is_set(), "GET did not encounter TCP backpressure"
                descriptor = os.open(Path(config.state_root) / "generation.lock", os.O_RDWR)
                try:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        reader_lock_held = False
                    except BlockingIOError:
                        reader_lock_held = True
                finally:
                    os.close(descriptor)
                # Keep the shared helper's original three-second HTTP timeout.
                try:
                    status, result = request(
                        base + URL + "/correct",
                        method="POST",
                        payload=payload,
                        token="owner-test-token",
                    )
                except TimeoutError as exc:
                    exc.add_note(
                        f"reader_lock_held={reader_lock_held}; "
                        f"GET_socket_write_finished={finished.is_set()}",
                    )
                    raise
                assert status == 200 and isinstance(result, dict)
                assert result["corrected"] == PAGE and result["tombstone_sequence"] == 1
                assert not reader_lock_held
                assert not finished.is_set(), "writer only completed after GET drained"
                assert request(
                    base + URL + "/correct",
                    method="POST",
                    payload=payload,
                    token="owner-test-token",
                ) == (200, result)
            finally:
                slow.shutdown(socket.SHUT_RDWR)
                slow.close()
                assert finished.wait(5), "blocked GET did not terminate on disconnect"
        assert replacement in (root / (PAGE + ".md")).read_text()


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_effect_requires_auth_and_current_page_receipt(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    operation: str,
) -> None:
    config, _ = ready(tmp_path)
    monkeypatch.setenv("SB_WEB_TOKEN", "owner-test-token")
    with running(config) as base:
        endpoint = base + URL + "/" + operation
        assert request(endpoint, method="POST", payload={})[0] == 401
        assert request(endpoint, method="POST", payload={}, token="owner-test-token") == (
            409, {"error": "EFFECT_RECEIPT_REQUIRED"})
        _, page = request(base + URL, token="owner-test-token")
        payload = payload_for(page, "replacement")
        receipt = payload["receipt"]
        assert isinstance(receipt, dict)
        payload["receipt"] = {**receipt, "page_content_digest": "sha256:" + "0" * 64}
        assert request(endpoint, method="POST", payload=payload, token="owner-test-token") == (
            409, {"error": "EFFECT_PRIOR_STALE"})
    store = RequestStore(Path(config.request_root))
    try:
        assert store.tombstone_high_water()[0] == 0
    finally:
        store.close()
