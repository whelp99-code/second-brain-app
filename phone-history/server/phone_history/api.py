"""Minimal authenticated HTTP API for Phone History."""

from __future__ import annotations

import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, cast, override
from urllib.parse import parse_qs, unquote, urlsplit

from phone_history import __version__
from phone_history.config import Settings
from phone_history.errors import (
    AuthenticationError,
    PhoneHistoryError,
    RequestTooLargeError,
    ValidationError,
)
from phone_history.models import parse_batch
from phone_history.service import PhoneHistoryService
from phone_history.transport import open_transport_payload

_JSON_CONTENT_TYPE: Final = "application/json"
_ID_RE: Final = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_REQUEST_ID_RE: Final = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


@dataclass(frozen=True, slots=True)
class APIContext:
    service: PhoneHistoryService
    token: str
    max_request_bytes: int


class PhoneHistoryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _handler(context: APIContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"PhoneHistory/{__version__}"
        protocol_version = "HTTP/1.1"

        @override
        def log_message(self, format: str, *args: object) -> None:
            # The default logger includes the complete request path. Query strings
            # may contain identifiers, so production logging is delegated to the
            # reverse proxy with an explicit redaction policy.
            del format, args

        def do_GET(self) -> None:
            self._dispatch(self._get)

        def do_POST(self) -> None:
            self._dispatch(self._post)

        def do_DELETE(self) -> None:
            self._dispatch(self._delete)

        def do_OPTIONS(self) -> None:
            self._json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": {"code": "METHOD_NOT_ALLOWED", "message": "not allowed"}},
            )

        def _dispatch(self, action: object) -> None:
            try:
                cast("callable[[], None]", action)()
            except PhoneHistoryError as exc:
                self._json(
                    HTTPStatus(exc.status),
                    {"error": {"code": exc.code, "message": str(exc)}},
                )
            except (OSError, ValueError, json.JSONDecodeError):
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "request could not be completed",
                        }
                    },
                )
            except Exception:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "request could not be completed",
                        }
                    },
                )

        def _get(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/healthz":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "version": __version__,
                        "device_closure": "NOT_RUN",
                    },
                )
                return
            self._require_auth()
            values = parse_qs(parsed.query, keep_blank_values=True)
            if parsed.path == "/v1/capabilities":
                self._json(HTTPStatus.OK, context.service.capabilities())
                return
            if parsed.path == "/v1/sync/status":
                self._json(HTTPStatus.OK, context.service.status())
                return
            if parsed.path == "/v1/timeline":
                device_id = _optional_query(values, "device_id")
                if device_id is not None:
                    _safe_id(device_id, "device_id")
                raw_date = _optional_query(values, "date")
                if raw_date is not None:
                    try:
                        _ = date.fromisoformat(raw_date)
                    except ValueError as exc:
                        raise ValidationError("date must use YYYY-MM-DD") from exc
                limit = _query_int(values, "limit", 100, maximum=500)
                self._json(
                    HTTPStatus.OK,
                    {
                        "events": list(
                            context.service.timeline(
                                device_id=device_id,
                                date=raw_date,
                                limit=limit,
                            )
                        )
                    },
                )
                return
            if parsed.path == "/v1/episodes":
                limit = _query_int(values, "limit", 100, maximum=500)
                self._json(
                    HTTPStatus.OK,
                    {"episodes": list(context.service.episodes(limit=limit))},
                )
                return
            if parsed.path == "/v1/candidates":
                state = _optional_query(values, "state")
                limit = _query_int(values, "limit", 100, maximum=500)
                self._json(
                    HTTPStatus.OK,
                    {"candidates": list(context.service.candidates(state=state, limit=limit))},
                )
                return
            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "NOT_FOUND", "message": "not found"}},
            )

        def _post(self) -> None:
            parsed = urlsplit(self.path)
            self._require_auth()
            if parsed.path in {"/v1/events:batch", "/v1/events:encrypted"}:
                payload = self._body()
                if parsed.path == "/v1/events:encrypted":
                    payload = open_transport_payload(payload, context.token)
                batch = parse_batch(payload)
                key = self.headers.get("Idempotency-Key", "")
                result = context.service.ingest(batch, idempotency_key=key)
                self._json(HTTPStatus(result.status), result.payload)
                return
            if parsed.path == "/v1/maintenance":
                payload = self._body()
                if payload:
                    raise ValidationError("maintenance request must be an empty object")
                self._json(HTTPStatus.OK, context.service.maintenance())
                return
            prefix = "/v1/candidates/"
            suffix = "/decision"
            if parsed.path.startswith(prefix) and parsed.path.endswith(suffix):
                candidate_id = unquote(parsed.path[len(prefix) : -len(suffix)]).strip("/")
                _safe_id(candidate_id, "candidate_id")
                payload = self._body()
                if set(payload) != {"decision"} or not isinstance(payload["decision"], str):
                    raise ValidationError("decision request is invalid")
                result = context.service.decide_candidate(candidate_id, payload["decision"])
                self._json(HTTPStatus.OK, result)
                return
            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "NOT_FOUND", "message": "not found"}},
            )

        def _delete(self) -> None:
            parsed = urlsplit(self.path)
            self._require_auth()
            prefix = "/v1/events/"
            if parsed.path.startswith(prefix):
                event_id = unquote(parsed.path.removeprefix(prefix)).strip("/")
                _safe_id(event_id, "event_id")
                values = parse_qs(parsed.query, keep_blank_values=True)
                reason = _optional_query(values, "reason") or "owner_requested"
                if len(reason) > 120:
                    raise ValidationError("reason is too long")
                result = context.service.delete_event(event_id, reason=reason)
                self._json(HTTPStatus.OK, result)
                return
            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": {"code": "NOT_FOUND", "message": "not found"}},
            )

        def _require_auth(self) -> None:
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {context.token}"
            if not hmac.compare_digest(supplied, expected):
                raise AuthenticationError("unauthorized")

        def _body(self) -> dict[str, object]:
            if self.headers.get("Transfer-Encoding"):
                raise ValidationError("Transfer-Encoding is not supported")
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != _JSON_CONTENT_TYPE:
                raise ValidationError("Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValidationError("Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValidationError("Content-Length is invalid") from exc
            if length < 0:
                raise ValidationError("Content-Length is invalid")
            if length > context.max_request_bytes:
                raise RequestTooLargeError("request body is too large")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValidationError("request body is incomplete")
            try:
                loaded = json.loads(raw or b"{}")
            except json.JSONDecodeError as exc:
                raise ValidationError("request body is not valid JSON") from exc
            if not isinstance(loaded, dict):
                raise ValidationError("request body must be a JSON object")
            return cast(dict[str, object], loaded)

        def _json(self, status: HTTPStatus, payload: object) -> None:
            request_id = self.headers.get("X-Request-ID", "")
            if _REQUEST_ID_RE.fullmatch(request_id) is None:
                request_id = uuid.uuid4().hex
            body = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", request_id)
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def build_server(
    settings: Settings,
    service: PhoneHistoryService | None = None,
) -> PhoneHistoryHTTPServer:
    chosen = PhoneHistoryService(settings) if service is None else service
    context = APIContext(
        service=chosen,
        token=settings.api_token,
        max_request_bytes=settings.max_request_bytes,
    )
    return PhoneHistoryHTTPServer((settings.host, settings.port), _handler(context))


def _query_int(
    values: dict[str, list[str]],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    raw = values.get(key, [str(default)])[0]
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{key} must be an integer") from exc
    if not 1 <= parsed <= maximum:
        raise ValidationError(f"{key} must be between 1 and {maximum}")
    return parsed


def _optional_query(values: dict[str, list[str]], key: str) -> str | None:
    value = values.get(key, [""])[0].strip()
    return value or None


def _safe_id(value: str, field: str) -> str:
    if _ID_RE.fullmatch(value) is None:
        raise ValidationError(f"{field} is invalid")
    return value
