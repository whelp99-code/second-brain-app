"""Real local TLS transport; provider responses are isolated synthetic fixtures."""

from __future__ import annotations

import ipaddress
import json
import logging
import ssl
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol, TypedDict, override

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from sb.effect_values import JsonObject
from sb.life_contracts import LifeInputError
from sb.life_delivery import TransportConfig, send_notification
from tests.json_fixtures import parse_object


class NotificationCall(TypedDict):
    path: str
    body: JsonObject
    key: str | None
    auth: str | None


class LogArgument(Protocol):
    @override
    def __str__(self) -> str: ...


@contextmanager
def tls_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int = 202
) -> Generator[tuple[str, list[NotificationCall]], None, None]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SB2 isolated transport fixture")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "fixture-cert.pem"
    key_path = tmp_path / "fixture-key.pem"
    _ = cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _ = key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    calls: list[NotificationCall] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            calls.append(
                {
                    "path": self.path,
                    "body": parse_object(self.rfile.read(length)),
                    "key": self.headers.get("Idempotency-Key"),
                    "auth": self.headers.get("Authorization"),
                }
            )
            body = json.dumps({"id": "fixture-message"}).encode()
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "https://forbidden.invalid/")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _ = self.wfile.write(body)

        @override
        def log_message(self, format: str, *args: LogArgument) -> None:
            logging.getLogger(__name__).debug(format, *args)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    client_context = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr("sb.life_delivery.ssl.create_default_context", lambda: client_context)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}/notify?channel=fixture", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


def test_real_tls_sends_only_minimal_notification_and_preserves_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SB_NOTIFICATION_FIXTURE_TOKEN", "fixture-no-real-secret")
    with tls_fixture(tmp_path, monkeypatch) as (endpoint, calls):
        result = send_notification(
            TransportConfig(endpoint, "SB_NOTIFICATION_FIXTURE_TOKEN", True),
            "delivery:" + "a" * 64,
            {"title": "브리핑 준비됨", "body": "앱에서 확인하세요"},
        )
    assert result == ("transport_accepted", "fixture-message")
    assert len(calls) == 1 and calls[0]["path"] == "/notify?channel=fixture"
    assert calls[0]["body"] == {
        "idempotency_key": "delivery:" + "a" * 64,
        "title": "브리핑 준비됨",
        "body": "앱에서 확인하세요",
    }
    assert calls[0]["auth"] == "Bearer fixture-no-real-secret"


@pytest.mark.parametrize("status", [302, 500, 503])
def test_ambiguous_provider_or_redirect_is_unknown_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    with tls_fixture(tmp_path, monkeypatch, status) as (endpoint, calls):
        result = send_notification(
            TransportConfig(endpoint, allow_private=True),
            "delivery:" + "b" * 64,
            {"title": "ready", "body": "open app"},
        )
    assert result == ("unknown", None)
    assert len(calls) == 1


def test_private_destination_requires_explicit_operator_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with tls_fixture(tmp_path, monkeypatch) as (endpoint, calls):
        with pytest.raises(LifeInputError, match="DESTINATION_DENIED"):
            _ = send_notification(
                TransportConfig(endpoint),
                "delivery:" + "c" * 64,
                {"title": "ready", "body": "open app"},
            )
        assert calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost/notify",
        "https://user:pass@example.invalid/",
        "https://example.invalid/#fragment",
        "file:///tmp/data",
    ],
)
def test_invalid_transport_config_is_denied_without_network(endpoint: str) -> None:
    with pytest.raises(LifeInputError, match="CONFIG_INVALID"):
        _ = send_notification(
            TransportConfig(endpoint),
            "delivery:" + "d" * 64,
            {"title": "ready", "body": "open app"},
        )
