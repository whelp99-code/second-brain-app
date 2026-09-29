from __future__ import annotations

import base64
import hashlib
import json
import socket
import subprocess
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from phone_history.config import Settings, accepted_second_brain_base_url
from phone_history.errors import ConfigurationError
from phone_history.service import PhoneHistoryService
from phone_history.sink import HttpSecondBrainSink, SinkError
from phone_history.transport import TransportFailure

from tests.conftest import batch_from, event_dict


class _State:
    def __init__(self) -> None:
        self.mode = "ok"
        self.drop_once = False
        self.retract_deleted = True
        self.uploads: dict[str, dict[str, object]] = {}
        self.declared: list[str] = []
        self.authorization: str | None = None


class _Server(ThreadingHTTPServer):
    def __init__(self, state: _State) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.state = state


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        server = self.server
        assert isinstance(server, _Server)
        state = server.state
        state.authorization = self.headers.get("Authorization")
        if state.mode == "unauthorized":
            self._json(401, {"error": "unauthorized"})
            return
        if state.mode == "missing":
            self._json(404, {"error": "not found"})
            return
        if self.path == "/api/uploads":
            body = json.loads(raw)
            encoded = base64.b64decode(body["content_base64"])
            digest = hashlib.sha256(encoded).hexdigest()
            assert body["content_sha256"] == digest
            state.declared.append(body["content_sha256"])
            upload_id = hashlib.sha256(
                f"{body['device_id']}\0{body['relative_path']}\0{digest}".encode()
            ).hexdigest()
            receipt = {
                "upload_id": upload_id,
                "state": "already-queued" if upload_id in state.uploads else "queued",
                "inbox_path": f"inbox/uploads/phone-history-server/{upload_id[:2]}/{upload_id}.md",
                "content_sha256": digest,
                "bytes": len(encoded),
                "filename": body["filename"],
                "relative_path": body["relative_path"],
                "device_id": body["device_id"],
            }
            state.uploads[upload_id] = receipt
            if state.drop_once:
                state.drop_once = False
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            self._json(201, receipt)
            return
        if self.path == "/api/uploads/retract":
            body = json.loads(raw)
            upload_id = body["upload_id"]
            self._json(
                200,
                {
                    "deleted": state.retract_deleted,
                    "indexed": False,
                    "restored": False,
                    "receipt_id": hashlib.sha256(f"retract\0{upload_id}".encode()).hexdigest(),
                    "checked_at": "2026-01-01T00:00:00Z",
                    "upload_id": upload_id,
                },
            )
            return
        self._json(404, {"error": "not found"})

    def _json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        _ = self.wfile.write(encoded)


@pytest.fixture
def upload_server():
    state = _State()
    server = _Server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _base(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def test_http_sink_posts_upload_with_declared_sha256_and_keeps_sink_ref_compatible(
    settings: Settings,
    upload_server: tuple[ThreadingHTTPServer, _State],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, state = upload_server
    monkeypatch.setenv("SB_WEB_TOKEN", "server-token-value")
    sink = HttpSecondBrainSink(_base(server))
    service = PhoneHistoryService(replace(settings, second_brain_base_url=_base(server)), sink=sink)
    event_id = "phevt:http-sink:001"
    response = service.ingest(
        batch_from(event_dict(event_id=event_id, body="declared hash body")),
        idempotency_key="http-sink-0001",
    )
    assert response.payload["events"][0]["sink_state"] == "exported"
    assert state.authorization == "Bearer server-token-value"
    assert state.declared and len(state.declared[0]) == 64
    record = service.repository.get_event(event_id)
    ref = json.loads(record.sink_ref or "{}")
    assert set(ref) == {"content_sha256", "inbox_path", "upload_id"}
    assert ref["content_sha256"] == state.declared[0]
    assert ref["upload_id"] in state.uploads
    again = sink.export(record)
    assert again == record.sink_ref
    assert len(state.uploads) == 1


def test_vault_path_only_config_is_migration_error_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PHONE_HISTORY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PHONE_HISTORY_API_TOKEN", "test-token-" + "a" * 40)
    monkeypatch.setenv(
        "PHONE_HISTORY_MASTER_KEY_B64",
        base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
    )
    monkeypatch.setenv("PHONE_HISTORY_SECOND_BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.delenv("PHONE_HISTORY_SECOND_BRAIN_BASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="do not fall back"):
        _ = Settings.from_environment()
    monkeypatch.setenv("PHONE_HISTORY_SECOND_BRAIN_BASE_URL", "http://127.0.0.1:9")
    with pytest.raises(ConfigurationError, match="do not fall back"):
        _ = Settings.from_environment()


def test_401_404_timeout_response_loss_keep_local_pending_same_receipt(
    settings: Settings,
    upload_server: tuple[ThreadingHTTPServer, _State],
) -> None:
    server, state = upload_server
    base = _base(server)
    event_id = "phevt:http-loss:001"
    batch = batch_from(event_dict(event_id=event_id, body="loss body"))

    state.mode = "unauthorized"
    service = PhoneHistoryService(
        replace(settings, second_brain_base_url=base),
        sink=HttpSecondBrainSink(base),
    )
    denied = service.ingest(batch, idempotency_key="http-loss-401")
    assert denied.payload["events"][0]["sink_state"] == "pending"
    assert service.repository.get_event(event_id).sink_ref is None

    state.mode = "missing"
    missing = service.retry_pending()
    assert missing == {"exported": 0, "pending": 1}
    assert service.repository.get_event(event_id).sink_state == "pending"

    state.mode = "ok"

    def _timeout(*_args: object) -> tuple[int, bytes]:
        raise TransportFailure("timeout")

    timed = PhoneHistoryService(
        settings,
        repository=service.repository,
        sink=HttpSecondBrainSink(base, exchange=_timeout),
    )
    assert timed.retry_pending() == {"exported": 0, "pending": 1}

    state.drop_once = True
    lost = PhoneHistoryService(
        settings,
        repository=service.repository,
        sink=HttpSecondBrainSink(base),
    )
    assert lost.retry_pending() == {"exported": 0, "pending": 1}
    assert service.repository.get_event(event_id).sink_ref is None
    stored = next(iter(state.uploads.values()))
    recovered = lost.retry_pending()
    assert recovered == {"exported": 1, "pending": 0}
    ref = json.loads(service.repository.get_event(event_id).sink_ref or "{}")
    assert ref["upload_id"] == stored["upload_id"]
    assert ref["content_sha256"] == stored["content_sha256"]


def test_retract_requires_receipt_deleted_true(
    settings: Settings,
    upload_server: tuple[ThreadingHTTPServer, _State],
) -> None:
    server, state = upload_server
    base = _base(server)
    sink = HttpSecondBrainSink(base)
    service = PhoneHistoryService(replace(settings, second_brain_base_url=base), sink=sink)
    event_id = "phevt:http-retract:001"
    _ = service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="http-retract-0001",
    )
    state.retract_deleted = False
    result = service.delete_event(event_id, reason="owner_requested")
    assert result["state"] == "pending"
    assert result["second_brain_retract"] == "retract_receipt_pending"
    assert service.repository.get_event(event_id).sink_state == "pending"
    with pytest.raises(SinkError, match="retract_receipt_pending"):
        upload_id = json.loads(service.repository.get_event(event_id).sink_ref or "{}")["upload_id"]
        sink.retract(upload_id)
    state.retract_deleted = True
    deleted = service.delete_event(event_id, reason="owner_requested")
    assert deleted["state"] == "deleted"


def test_no_sb_runtime_import_in_sink_module() -> None:
    sink_path = Path(__file__).resolve().parents[1] / "server" / "phone_history" / "sink.py"
    result = subprocess.run(
        ["rg", "-n", r"sb\.(uploads|search|vault)", str(sink_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""


def test_only_loopback_http_or_https_endpoints_accepted(settings: Settings) -> None:
    assert accepted_second_brain_base_url("https://brain.example/sb") == "https://brain.example/sb"
    assert accepted_second_brain_base_url("http://127.0.0.1:8765/") == "http://127.0.0.1:8765"
    for rejected in (
        "http://localhost:8765",
        "http://10.1.2.3:8765",
        "http://0.0.0.0:8765",
        "http://[::1]:8765",
        "ftp://127.0.0.1:8765",
        "https://user:secret@brain.example",
        "http://127.0.0.1:8765?token=1",
    ):
        with pytest.raises(ConfigurationError):
            _ = accepted_second_brain_base_url(rejected)
        with pytest.raises(ConfigurationError):
            _ = replace(settings, second_brain_base_url=rejected)
    sink = HttpSecondBrainSink("http://127.0.0.1:9")
    assert sink.base_url == "http://127.0.0.1:9"
    with pytest.raises(ConfigurationError):
        _ = HttpSecondBrainSink("http://example.com")
