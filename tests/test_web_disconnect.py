"""A disconnected response is not retried; unrelated failures still surface."""
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock

import pytest

from sb.web import Handler, build_server
from tests.test_web import ready


@pytest.mark.parametrize('error', [BrokenPipeError, ConnectionResetError])
@pytest.mark.parametrize('at_headers', [False, True])
def test_json_disconnect_does_not_retry_or_escape(tmp_path: Path, error: type[BrokenPipeError] | type[ConnectionResetError], at_headers: bool, monkeypatch: pytest.MonkeyPatch):
    config, _ = ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    try:
        assert isinstance(server.RequestHandlerClass, type)
        handler = object.__new__(server.handler_class)
        send_response = Mock()
        write = Mock(side_effect=error())
        monkeypatch.setattr(handler, 'send_response', send_response)
        monkeypatch.setattr(handler, 'send_header', Mock())
        monkeypatch.setattr(handler, 'end_headers', Mock(side_effect=error() if at_headers else None))
        monkeypatch.setattr(handler, 'wfile', Mock(write=write), raising=False)
        handler.close_connection = False
        handler.json_response(HTTPStatus.OK, {'status': 'ok'})
        assert handler.close_connection
        assert send_response.call_count == 1
        assert write.call_count == (0 if at_headers else 1)
    finally:
        server.server_close()


def test_json_other_io_errors_are_not_silenced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config, _ = ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    try:
        assert isinstance(server.RequestHandlerClass, type)
        handler = object.__new__(server.handler_class)
        monkeypatch.setattr(handler, 'send_response', Mock(side_effect=OSError('unrelated IO failure')))
        with pytest.raises(OSError, match='unrelated IO failure'):
            handler.json_response(HTTPStatus.OK, {})
    finally:
        server.server_close()


def test_real_reset_during_response_keeps_server_healthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import socket
    import struct
    import threading

    from tests.test_web import request

    config, _ = ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    entered, finished = threading.Event(), threading.Event()
    handler_type = server.handler_class
    original = handler_type.get_response
    errors = Mock()
    monkeypatch.setattr(server, 'handle_error', errors)

    def paused_get(self: Handler, root: Path) -> None:
        if self.path != '/health?disconnect':
            return original(self, root)
        entered.set()
        try:
            # Wait for the actual TCP reset before writing the response. No sleep
            # or probabilistic browser-close timing is needed.
            try:
                _ = self.connection.recv(1)
            except ConnectionResetError:
                pass
            original(self, root)
        finally:
            finished.set()

    monkeypatch.setattr(handler_type, '_get', paused_get)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = server.server_address
        assert isinstance(address[0], str) and isinstance(address[1], int)
        with socket.create_connection((address[0], address[1]), timeout=5) as client:
            client.sendall(b'GET /health?disconnect HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert entered.wait(5)
            client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        assert finished.wait(5)
        status, payload = request(f'http://127.0.0.1:{server.server_address[1]}/health')
        assert status == 200 and payload == {'status': 'ok'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert errors.call_count == 0
