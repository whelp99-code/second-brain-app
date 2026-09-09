"""HTTPS verifier invocation inside the bounded local process channel."""
from __future__ import annotations

import http.client
import os
import re
import ssl
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sb.effect_values import JsonValue, canonical_bytes, strict_loads
from sb.scoped_provider_process import ScopedProviderProcess

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_ROUTE = "/api/v1/memory/provider/verify"


def create_scoped_provider_https(config_path: Path) -> ScopedProviderProcess:
    """Server-owned file contains origin/cookie_id/csrf_token/optional ca_file.

    Credentials are re-read in each child. They are bearer credentials, not a
    cached authorization decision: the gateway checks its live session and policy.
    Never obtain this path from a memory request. No login or renewal is performed.
    """
    if not config_path.is_absolute():
        raise ValueError("SCOPED_PROVIDER_HTTPS_CONFIG_INVALID")
    return ScopedProviderProcess([sys.executable, "-I", "-m", "sb.scoped_provider_https", str(config_path)],
        cwd=Path("/"), env={})


def _config(path: Path) -> dict[str, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 8192):
            raise ValueError("CONFIG_INVALID")
        value = strict_loads(os.read(fd, 8193), 8192)
    finally:
        os.close(fd)
    if not isinstance(value, dict) or set(value) not in (
        {"origin", "cookie_id", "csrf_token"}, {"origin", "cookie_id", "csrf_token", "ca_file"}
    ) or any(not isinstance(v, str) for v in value.values()):
        raise ValueError("CONFIG_INVALID")
    return {k: str(v) for k, v in value.items()}


def _settings(path: Path) -> tuple[dict[str, str], str, int, ssl.SSLContext]:
    config = _config(path)
    origin = config["origin"]
    url = urlsplit(origin)
    if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
            or url.path or url.query or url.fragment or origin != "https://" + url.netloc
            or any(ord(c) < 33 or ord(c) > 126 for c in origin)
            or any(c in origin for c in "\\%")
            or (url.port is not None and not 1 <= url.port <= 65535)
            or not _TOKEN.fullmatch(config["cookie_id"]) or not _TOKEN.fullmatch(config["csrf_token"])):
        raise ValueError("CONFIG_INVALID")
    ca_file = config.get("ca_file")
    if ca_file is not None and not Path(ca_file).is_absolute():
        raise ValueError("CONFIG_INVALID")
    if ca_file is None:
        context = ssl.create_default_context()
    else:
        # Open nonblocking before checking the descriptor so a FIFO cannot stall
        # CLI preflight. Public CA symlinks may resolve to bounded regular files.
        fd = os.open(ca_file, os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 262144:
                raise ValueError("CA_INVALID")
            ca_bytes = os.read(fd, 262145)
            if len(ca_bytes) != info.st_size:
                raise ValueError("CA_INVALID")
        finally:
            os.close(fd)
        context = ssl.create_default_context(cadata=ca_bytes.decode("ascii"))
    return config, url.hostname, url.port or 443, context


def validate_scoped_provider_https_config(path: Path) -> None:
    """Local preflight only; neither sends a request nor asserts a live session."""
    _ = _settings(path)


def _invoke(path: Path, payload: bytes) -> JsonValue:
    if not 0 < len(payload) <= 32768:
        raise ValueError("INPUT_INVALID")
    config, host, port, context = _settings(path)
    origin = config["origin"]
    connection = http.client.HTTPSConnection(host, port, timeout=10, context=context)
    try:
        connection.request("POST", _ROUTE, body=payload, headers={
            "Origin": origin, "Cookie": "__Host-jarvis-phone=" + config["cookie_id"],
            "X-JARVIS-CSRF": config["csrf_token"], "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json", "Connection": "close",
        })
        response = connection.getresponse()
        # Do not follow redirects or parse/log error bodies. In particular, no
        # cookies or owner identity headers are forwarded to another destination.
        if response.status != 200:
            return None
        lengths = response.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or not re.fullmatch(r"[1-9][0-9]{0,3}", lengths[0])
                or int(lengths[0]) > 4096 or response.headers.get_all("Transfer-Encoding")
                or response.headers.get_all("Content-Encoding")
                or response.headers.get_all("Content-Type") != ["application/json; charset=utf-8"]):
            raise ValueError("RESPONSE_INVALID")
        raw = response.read(4097)
        if len(raw) != int(lengths[0]):
            raise ValueError("RESPONSE_INVALID")
        return strict_loads(raw, 4096)
    finally:
        connection.close()


def main() -> None:
    try:
        if len(sys.argv) != 2:
            raise ValueError("CONFIG_INVALID")
        result = _invoke(Path(sys.argv[1]), sys.stdin.buffer.read(32769))
        # _invoke returns a JSON value from strict_loads, or null for HTTP denial.
        _ = sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    except (OSError, ValueError, RuntimeError, http.client.HTTPException):
        _ = sys.stdout.buffer.write(b'{"error":"SCOPED_PROVIDER_HTTPS_FAILED"}\n')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
