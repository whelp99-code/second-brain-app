"""Pinned HTTPS transport for previously committed Life delivery claims."""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from typing import override
from urllib.parse import urlsplit

from sb.life_contracts import LifeInputError
from sb.life_json import decode_json
from sb.life_values import canonical_bytes


@dataclass(frozen=True, slots=True)
class TransportConfig:
    endpoint: str
    token_env: str | None = None
    allow_private: bool = False
    timeout: float = 10


class _PinnedTLS(http.client.HTTPSConnection):
    sock: socket.socket | None

    def __init__(self, host: str, port: int, address: str, timeout: float):
        self.tls_context: ssl.SSLContext = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self.tls_context)
        self.address: str = address
        self.connect_timeout: float = timeout

    @override
    def connect(self) -> None:
        sock = socket.create_connection((self.address, self.port), self.connect_timeout)
        self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)


def send_notification(
    config: TransportConfig, delivery_id: str, notification: dict[str, str]
) -> tuple[str, str | None]:
    """Operator-configured HTTPS webhook. No redirect, DNS rebinding, or body leak.

    An authenticated real transport is opt-in; tests inject a transport or use
    an explicitly configured local fixture. This function does not create jobs.
    """
    parsed = urlsplit(config.endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not 0 < config.timeout <= 30
    ):
        raise LifeInputError("LIFE_DELIVERY_CONFIG_INVALID")
    if config.token_env is not None and (
        not config.token_env.isidentifier() or len(config.token_env) > 128
    ):
        raise LifeInputError("LIFE_DELIVERY_CONFIG_INVALID")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise LifeInputError("LIFE_DELIVERY_UNAVAILABLE") from exc
    if (
        not addresses
        or any(not ipaddress.ip_address(r[4][0]).is_global for r in addresses)
        and not config.allow_private
    ):
        raise LifeInputError("LIFE_DELIVERY_DESTINATION_DENIED")
    payload = canonical_bytes({"idempotency_key": delivery_id, **notification})
    if len(payload) > 8192:
        raise LifeInputError("LIFE_DELIVERY_TOO_LARGE")
    headers = {"Content-Type": "application/json", "Idempotency-Key": delivery_id}
    if config.token_env:
        token = os.environ.get(config.token_env, "")
        if not token or any(c in token for c in "\r\n"):
            raise LifeInputError("LIFE_DELIVERY_CONFIG_INVALID")
        headers["Authorization"] = "Bearer " + token
    connection = _PinnedTLS(
        parsed.hostname, parsed.port or 443, str(addresses[0][4][0]), config.timeout
    )
    try:
        target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        connection.request("POST", target, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read(4097)
        if len(raw) > 4096:
            return "unknown", None
        if 200 <= response.status < 300:
            try:
                result = decode_json(raw or b"{}")
                message_id = result.get("id") if isinstance(result, dict) else None
            except ValueError:
                message_id = None
            return "transport_accepted", str(message_id)[:256] if message_id is not None else None
        if response.status == 401:
            return "rejected_auth", None
        if response.status == 410:
            return "subscription_expired", None
        if response.status == 429:
            retry = response.headers.get("Retry-After")
            if not isinstance(retry, str) or len(retry) > 64 or any(c in retry for c in "\r\n"):
                retry = None
            return "retry_after", retry
        return ("rejected" if 400 <= response.status < 500 else "unknown"), None
    except (OSError, http.client.HTTPException):
        return "unknown", None
    finally:
        connection.close()
