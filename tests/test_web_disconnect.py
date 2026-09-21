"""A disconnected response is not retried; unrelated failures still surface."""
from http import HTTPStatus
from unittest.mock import Mock

import pytest

from sb.web import build_server
from tests.test_web import _ready


@pytest.mark.parametrize('error', [BrokenPipeError, ConnectionResetError])
@pytest.mark.parametrize('at_headers', [False, True])
def test_json_disconnect_does_not_retry_or_escape(tmp_path, error, at_headers):
    config, _ = _ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    try:
        assert isinstance(server.RequestHandlerClass, type)
        handler = object.__new__(server.RequestHandlerClass)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=error() if at_headers else None)
        handler.wfile = Mock()
        handler.wfile.write.side_effect = error()
        handler.close_connection = False
        handler._json(HTTPStatus.OK, {'status': 'ok'})
        assert handler.close_connection
        assert handler.send_response.call_count == 1
        assert handler.wfile.write.call_count == (0 if at_headers else 1)
    finally:
        server.server_close()


def test_json_other_io_errors_are_not_silenced(tmp_path):
    config, _ = _ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    try:
        assert isinstance(server.RequestHandlerClass, type)
        handler = object.__new__(server.RequestHandlerClass)
        handler.send_response = Mock(side_effect=OSError('unrelated IO failure'))
        with pytest.raises(OSError, match='unrelated IO failure'):
            handler._json(HTTPStatus.OK, {})
    finally:
        server.server_close()


def test_real_reset_during_response_keeps_server_healthy(tmp_path, monkeypatch):
    import socket
    import struct
    import threading

    from tests.test_web import _request

    config, _ = _ready(tmp_path)
    server = build_server(config, '127.0.0.1', 0)
    entered, finished = threading.Event(), threading.Event()
    handler_type = server.RequestHandlerClass
    original = handler_type._get
    errors = Mock()
    monkeypatch.setattr(server, 'handle_error', errors)

    def paused_get(self, root):
        if self.path != '/health?disconnect':
            return original(self, root)
        entered.set()
        try:
            # Wait for the actual TCP reset before writing the response. No sleep
            # or probabilistic browser-close timing is needed.
            try:
                self.connection.recv(1)
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
        status, payload = _request(f'http://127.0.0.1:{server.server_address[1]}/health')
        assert status == 200 and payload == {'status': 'ok'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
    assert errors.call_count == 0
