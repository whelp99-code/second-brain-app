
import ssl
import threading
from contextlib import contextmanager
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

import pytest

from sb.effect_values import canonical_bytes
from sb.scoped_provider_https import create_scoped_provider_https
from sb.scoped_provider_process import ScopedProviderChannelError
from tests.json_fixtures import parse_object
from tests.scoped_https_harness import certificate


@contextmanager
def server(tmp_path: Path, mode: str="valid"):
    cert, key = certificate(tmp_path)
    calls: list[tuple[str, Message[str, str], bytes]] = []
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_POST(self) -> None:
            calls.append((self.path, self.headers, self.rfile.read(int(self.headers["Content-Length"]))))
            body = b'{"kind":"test"}'
            status = 200
            if mode == "denied":
                status = 403
            if mode == "redirect":
                status = 302
            if mode == "oversize":
                body = b"x" * 4097
            if mode == "duplicate":
                body = b'{"kind":"one","kind":"two"}'
            self.send_response(status)
            self.send_header("Content-Type", "text/html" if mode == "html" else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Location", "https://untrusted.example.invalid")
            self.end_headers()
            _ = self.wfile.write(body)
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    http.socket = context.wrap_socket(http.socket, server_side=True)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    config = tmp_path / "credentials.json"
    _ = config.write_bytes(canonical_bytes({"origin": f"https://127.0.0.1:{http.server_port}",
        "cookie_id": "a" * 43, "csrf_token": "b" * 43, "ca_file": str(cert)}))
    config.chmod(0o600)
    try:
        yield config, calls
    finally:
        http.shutdown()
        thread.join()
        http.server_close()


@pytest.mark.parametrize("mode", ["valid", "denied", "redirect", "oversize", "duplicate", "html", "untrusted_ca"])
def test_actual_https_child_is_bounded_and_checks_tls(tmp_path: Path, mode: str):
    with server(tmp_path, mode) as (config, calls):
        if mode == "untrusted_ca":
            value = parse_object(config.read_bytes())
            del value["ca_file"]
            _ = config.write_bytes(canonical_bytes(value))
        verify = create_scoped_provider_https(config)
        if mode in {"oversize", "duplicate", "html", "untrusted_ca"}:
            with pytest.raises(ScopedProviderChannelError):
                _ = verify(b"{}")
        else:
            assert verify(b"{}") == ({"kind": "test"} if mode == "valid" else None)
        assert len(calls) == (0 if mode == "untrusted_ca" else 1)
        if calls:
            path, headers, payload = calls[0]
            assert path == "/api/v1/memory/provider/verify" and payload == b"{}"
            assert headers["Cookie"] == "__Host-jarvis-phone=" + "a" * 43
            assert headers["X-JARVIS-CSRF"] == "b" * 43
            assert headers["Tailscale-User-Login"] is None


@pytest.mark.parametrize("mode", ["readable", "symlink", "http", "injected_header"])
def test_invalid_credentials_never_reach_server(tmp_path: Path, mode: str):
    with server(tmp_path) as (config, calls):
        if mode == "readable":
            config.chmod(0o644)
        elif mode == "symlink":
            link = tmp_path / "credentials-link.json"
            link.symlink_to(config)
            config = link
        else:
            value = parse_object(config.read_bytes())
            if mode == "http":
                origin = value["origin"]
                assert isinstance(origin, str)
                value["origin"] = origin.replace("https:", "http:")
            else:
                cookie = value["cookie_id"]
                assert isinstance(cookie, str)
                value["cookie_id"] = cookie + "\r\nInjected: yes"
            _ = config.write_bytes(canonical_bytes(value))
        with pytest.raises(ScopedProviderChannelError):
            _ = create_scoped_provider_https(config)(b"{}")
        assert calls == []
