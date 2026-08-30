"""Versioned, idempotent JARVIS-to-Second-Brain write requests.

The module deliberately owns only the request ledger and its durable artifact
boundary. It never executes commands and it never treats memory text as
approval or authority.
"""

from __future__ import annotations

# pyright: reportAny=none, reportUnknownVariableType=none, reportUnknownArgumentType=none, reportUnannotatedClassAttribute=none, reportUnusedCallResult=none
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast

from sb.contracts import PageSpec, SourceCite, TerminalWorkSummaryV1, canonical_json
from sb.security import mask_sensitive
from sb.store.cas import ContentAddressedStore
from sb.vault import Vault, read_page_spec

WriteOperation = Literal["remember", "correct", "forget", "export", "restore"]
REQUEST_SCHEMA: Final = "second-brain-write-request-v1"
REQUEST_DB: Final = "write-requests.db"
MAX_EXPORT_ITEMS: Final = 100
MAX_EXPORT_BYTES: Final = 1024 * 1024


class WriteRequestError(ValueError):
    """Stable client-visible request validation or reconciliation failure."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RequestRecord:
    request_id: str
    idempotency_key: str
    operation: str
    payload_digest: str
    status: str
    artifact_digest: str | None
    page_id: str | None
    result: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RequestReceipt:
    request_id: str
    status: str
    idempotent_replay: bool
    artifact_digest: str | None = None
    page_id: str | None = None
    error_code: str | None = None
    result: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WriteRequestV1:
    """An approval-bound write request accepted from JARVIS.

    ``receipt_digest`` is evidence of approval, not an authority field. The
    provider stores it and never interprets memory content as a receipt.
    """

    operation: WriteOperation
    candidate_id: str
    closeout_id: str
    receipt_digest: str
    purpose: str
    sensitivity: str
    retention: str
    expected_prior_digest: str | None
    idempotency_key: str
    summary: TerminalWorkSummaryV1 | None = None
    request_id: str | None = None
    schema: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise WriteRequestError("unsupported_schema", self.schema)
        if self.operation not in {"remember", "correct", "forget", "export", "restore"}:
            raise WriteRequestError("invalid_operation", self.operation)
        for name in ("candidate_id", "closeout_id", "purpose", "sensitivity", "retention", "idempotency_key"):
            value = getattr(self, name)
            if not value.strip():
                raise WriteRequestError("missing_field", name)
            if len(value) > 512 or any(ord(char) < 32 for char in value):
                raise WriteRequestError("invalid_field", name)
        if not _is_digest(self.receipt_digest):
            raise WriteRequestError("invalid_receipt_digest", "receipt_digest must be sha256:<64 hex>")
        if self.expected_prior_digest is not None and not _is_digest(self.expected_prior_digest):
            raise WriteRequestError("invalid_prior_digest", "expected_prior_digest must be sha256:<64 hex>")
        if self.operation in {"remember", "correct"} and self.summary is None:
            raise WriteRequestError("missing_summary", f"{self.operation} requires summary")
        if self.summary is not None:
            if self.summary.memory_candidate_id != self.candidate_id:
                raise WriteRequestError("candidate_mismatch", "summary candidate does not match request")
            if self.summary.jarvis_receipt_digest != self.receipt_digest:
                raise WriteRequestError("receipt_mismatch", "summary receipt does not match request")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> WriteRequestV1:
        raw_summary = value.get("summary")
        summary = None
        if isinstance(raw_summary, Mapping):
            summary = TerminalWorkSummaryV1.from_mapping(raw_summary)
        operation = value.get("operation")
        if not isinstance(operation, str):
            raise WriteRequestError("missing_field", "operation")
        receipt = value.get("receipt_digest", value.get("jarvis_receipt_digest"))
        if not isinstance(receipt, str):
            raise WriteRequestError("missing_field", "receipt_digest")
        return cls(
            operation=cast(WriteOperation, operation),
            candidate_id=_text(value, "candidate_id"),
            closeout_id=_text(value, "closeout_id"),
            receipt_digest=receipt,
            purpose=_text(value, "purpose"),
            sensitivity=_text(value, "sensitivity"),
            retention=_text(value, "retention"),
            expected_prior_digest=_optional_text(value.get("expected_prior_digest")),
            idempotency_key=_text(value, "idempotency_key"),
            summary=summary,
            request_id=_optional_text(value.get("request_id")),
        )

    def as_dict(self, *, include_schema: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "operation": self.operation,
            "candidate_id": self.candidate_id,
            "closeout_id": self.closeout_id,
            "receipt_digest": self.receipt_digest,
            "purpose": self.purpose,
            "sensitivity": self.sensitivity,
            "retention": self.retention,
            "expected_prior_digest": self.expected_prior_digest,
            "idempotency_key": self.idempotency_key,
            "summary": None if self.summary is None else self.summary.as_dict(),
        }
        if include_schema:
            payload["schema"] = self.schema
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        return payload

    @property
    def jarvis_receipt_digest(self) -> str:
        return self.receipt_digest

    def to_dict(self) -> dict[str, object]:
        return self.as_dict()

    @property
    def payload_digest(self) -> str:
        return digest_json(self.as_dict(include_schema=True))


MemoryWriteRequestV1 = WriteRequestV1
WriteRequest = WriteRequestV1

@dataclass(frozen=True, slots=True)
class HealthResponse:
    status: Literal["ok", "degraded", "error"]
    contract: str
    version: str
    capabilities: tuple[str, ...]
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"kind": "health", **asdict(self), "capabilities": list(self.capabilities)}


@dataclass(frozen=True, slots=True)
class NoDataResponse:
    reason: str = "no_data"

    def as_dict(self) -> dict[str, str]:
        return {"kind": "no_data", "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ErrorResponse:
    code: str
    message: str
    retryable: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"kind": "error", **asdict(self)}


MCP_TOOL_NAMES: Final = (
    "sb_search",
    "sb_read_page",
    "sb_recent_changes",
    "sb_open_conflicts",
    "sb_remember",
    "sb_run",
)
MCP_PROVIDER_TOOL_NAMES: Final = (
    "sb_provider_health",
    "sb_write_request",
    "sb_request_status",
    "sb_reconcile_write",
    "sb_restore_request",
    "sb_observe_artifact",
    "sb_export_history",
)
MCP_CONTRACT: Final[dict[str, object]] = {
    "schema": "second-brain-mcp-v1",
    "tools": {
        name: {"success": "typed", "no_data": "typed", "error": "typed"} for name in MCP_TOOL_NAMES
    },
    "provider_tools": {
        name: {"success": "typed", "no_data": "typed", "error": "typed"}
        for name in MCP_PROVIDER_TOOL_NAMES
    },
}


def canonical_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def digest_json(value: object) -> str:
    return f"sha256:{canonical_digest(value)}"


def _is_digest(value: str) -> bool:
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    try:
        int(value[7:], 16)
    except ValueError:
        return False
    return True


def _text(value: Mapping[str, object], name: str) -> str:
    raw = value.get(name)
    if not isinstance(raw, str):
        raise WriteRequestError("missing_field", name)
    return raw


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


class _PageLedger:
    def __init__(self, root: Path) -> None:
        self.root = root

    def last_compiled_hash(self, page_id: str) -> str | None:
        page = read_page_spec(self.root, page_id)
        if page is None:
            return None
        path = self.root / "wiki" / f"{page_id}.md"
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class RequestInbox:
    """SQLite inbox with unique idempotency and append-only request history."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.db_path = self.root / ".sb" / REQUEST_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    operation TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_digest TEXT,
                    page_id TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS request_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_digest TEXT,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES requests(request_id)
                );
                CREATE INDEX IF NOT EXISTS request_history_request_idx ON request_history(request_id, id);
                """
            )

    def submit(self, request: WriteRequestV1) -> RequestReceipt:
        payload_digest = request.payload_digest
        now = datetime.now(UTC).isoformat()
        request_id = request.request_id or f"wr_{payload_digest[7:31]}"
        payload = json.dumps(request.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM requests WHERE idempotency_key = ?", (request.idempotency_key,)
            ).fetchone()
            if row is not None:
                if row["payload_digest"] != payload_digest:
                    raise WriteRequestError("idempotency_collision", request.idempotency_key)
                return _receipt(row, replay=True)
            try:
                conn.execute(
                    "INSERT INTO requests(request_id,idempotency_key,operation,payload_digest,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        request_id,
                        request.idempotency_key,
                        request.operation,
                        payload_digest,
                        payload,
                        "accepted",
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WriteRequestError("idempotency_collision", request_id) from exc
            conn.execute(
                "INSERT INTO request_history(request_id,status,created_at) VALUES(?,?,?)",
                (request_id, "accepted", now),
            )
            row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
            assert row is not None
            return _receipt(row, replay=False)

    def get(self, request_id: str) -> RequestRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        return None if row is None else _record(row)

    def list(self, *, status: str | None = None, limit: int = 100) -> tuple[RequestRecord, ...]:
        safe_limit = max(1, min(limit, 1000))
        query = "SELECT * FROM requests"
        args: tuple[object, ...] = ()
        if status:
            query += " WHERE status = ?"
            args = (status,)
        query += " ORDER BY created_at, request_id LIMIT ?"
        args += (safe_limit,)
        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return tuple(_record(row) for row in rows)

    def process(self, request_id: str) -> RequestReceipt:
        record = self.get(request_id)
        if record is None:
            raise WriteRequestError("not_found", request_id)
        if record.status in {"applied", "forgotten", "exported", "restored", "settled"}:
            return RequestReceipt(
                record.request_id,
                record.status,
                True,
                record.artifact_digest,
                record.page_id,
                record.error_code,
                record.result,
            )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        assert row is not None
        request = WriteRequestV1.from_mapping(cast(dict[str, object], json.loads(row["payload_json"])))
        try:
            result = self._apply(request)
        except WriteRequestError as exc:
            self._set_status(request_id, "error", error_code=exc.code, result={"message": str(exc)})
            raise
        status = str(result.get("status", "applied"))
        artifact_value = result.get("artifact_digest")
        page_value = result.get("page_id")
        artifact_digest = artifact_value if isinstance(artifact_value, str) else None
        page_id = page_value if isinstance(page_value, str) else None
        self._set_status(
            request_id,
            status,
            artifact_digest=artifact_digest,
            page_id=page_id,
            result=result,
        )
        return RequestReceipt(request_id, status, False, artifact_digest, page_id, result=result)

    def history(self, request_id: str, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        """Return bounded append-only status history for one request."""
        safe_limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, artifact_digest, detail_json, created_at "
                + "FROM request_history WHERE request_id = ? ORDER BY id LIMIT ?",
                (request_id, safe_limit),
            ).fetchall()
        return tuple(
            {
                "status": row["status"],
                "artifact_digest": row["artifact_digest"],
                "detail": cast(dict[str, object], json.loads(row["detail_json"])),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def reconcile(self, request_id: str, *, observed_digest: str | None = None) -> RequestReceipt:
        record = self.get(request_id)
        if record is None:
            raise WriteRequestError("not_found", request_id)
        if observed_digest is not None and not _is_digest(observed_digest):
            raise WriteRequestError("invalid_artifact_digest", observed_digest)
        if record.status == "accepted":
            return self.process(request_id)
        if record.artifact_digest and observed_digest and record.artifact_digest != observed_digest:
            self._set_status(request_id, "reconciling", result={"observed_digest": observed_digest})
            return RequestReceipt(request_id, "reconciling", False, record.artifact_digest, record.page_id, result={"observed_digest": observed_digest})
        return RequestReceipt(record.request_id, record.status, True, record.artifact_digest, record.page_id, record.error_code, record.result)

    def observe_artifact(self, request_id: str, *, digest: str, page_id: str | None = None) -> RequestReceipt:
        if not _is_digest(digest):
            raise WriteRequestError("invalid_artifact_digest", digest)
        record = self.get(request_id)
        if record is None:
            raise WriteRequestError("not_found", request_id)
        artifact = page_id or record.page_id
        if artifact is None:
            raw_path = record.result.get("artifact_path")
            if not isinstance(raw_path, str):
                raise WriteRequestError("artifact_not_found", request_id)
            relative = Path(raw_path)
        else:
            if artifact.startswith(("/", "\\")) or ".." in Path(artifact).parts:
                raise WriteRequestError("invalid_artifact_path", artifact)
            relative = Path("wiki") / f"{artifact}.md"
        if relative.is_absolute() or ".." in relative.parts:
            raise WriteRequestError("invalid_artifact_path", str(relative))
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise WriteRequestError("artifact_not_found", str(relative))
        observed = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if observed != digest or (record.artifact_digest is not None and observed != record.artifact_digest):
            self._set_status(request_id, "reconciling", result={"observed_digest": observed})
            return RequestReceipt(
                request_id,
                "reconciling",
                False,
                record.artifact_digest,
                record.page_id,
                result={"observed_digest": observed},
            )
        status = "settled"
        self._set_status(
            request_id,
            status,
            artifact_digest=observed,
            page_id=page_id or record.page_id,
            result={"observed": True},
        )
        return RequestReceipt(
            request_id, status, False, observed, page_id or record.page_id, result={"observed": True}
        )
    def restore(self, request_id: str) -> RequestReceipt:
        record = self.get(request_id)
        if record is None:
            raise WriteRequestError("not_found", request_id)
        if record.status != "forgotten":
            raise WriteRequestError("invalid_transition", "only forgotten requests can be restored")
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        assert row is not None
        request = WriteRequestV1.from_mapping(cast(dict[str, object], json.loads(row["payload_json"])))
        raw_summary = record.result.get("restore_summary")
        if request.summary is None and isinstance(raw_summary, dict):
            request = WriteRequestV1(
                operation="restore",
                candidate_id=request.candidate_id,
                closeout_id=request.closeout_id,
                receipt_digest=request.receipt_digest,
                purpose=request.purpose,
                sensitivity=request.sensitivity,
                retention=request.retention,
                expected_prior_digest=record.artifact_digest,
                idempotency_key=f"{request.idempotency_key}:restore",
                summary=TerminalWorkSummaryV1.from_mapping(raw_summary),
            )
        elif request.summary is None:
            raise WriteRequestError("restore_unavailable", "original summary was not retained")
        else:
            request = WriteRequestV1(
                operation="restore",
                candidate_id=request.candidate_id,
                closeout_id=request.closeout_id,
                receipt_digest=request.receipt_digest,
                purpose=request.purpose,
                sensitivity=request.sensitivity,
                retention=request.retention,
                expected_prior_digest=record.artifact_digest,
                idempotency_key=f"{request.idempotency_key}:restore",
                summary=request.summary,
            )
        result = self._apply(request)
        self._set_status(request_id, "restored", result=result, artifact_digest=cast(str | None, result.get("artifact_digest")), page_id=cast(str | None, result.get("page_id")))
        return RequestReceipt(request_id, "restored", False, cast(str | None, result.get("artifact_digest")), cast(str | None, result.get("page_id")), result=result)

    def export(self, *, include_forgotten: bool = False, limit: int = MAX_EXPORT_ITEMS) -> dict[str, object]:
        safe_limit = max(1, min(limit, MAX_EXPORT_ITEMS))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT request_id, status, payload_json, artifact_digest, page_id, result_json "
                + "FROM requests ORDER BY created_at, request_id LIMIT ?",
                (safe_limit,),
            ).fetchall()
            history_rows = conn.execute(
                "SELECT request_id, status, artifact_digest, detail_json "
                + "FROM request_history ORDER BY id LIMIT ?",
                (safe_limit * 4,),
            ).fetchall()
        records: list[dict[str, object]] = []
        allowed_ids: set[str] = set()
        for row in rows:
            if not include_forgotten and row["status"] == "forgotten":
                continue
            request_payload = cast(dict[str, object], json.loads(row["payload_json"]))
            records.append(
                {
                    "request_id": row["request_id"],
                    "status": row["status"],
                    "artifact_digest": row["artifact_digest"],
                    "page_id": row["page_id"],
                    "request": request_payload,
                    "result": cast(dict[str, object], json.loads(row["result_json"])),
                }
            )
            allowed_ids.add(str(row["request_id"]))
        history = [
            {
                "request_id": row["request_id"],
                "status": row["status"],
                "artifact_digest": row["artifact_digest"],
                "detail": cast(dict[str, object], json.loads(row["detail_json"])),
            }
            for row in history_rows
            if str(row["request_id"]) in allowed_ids
        ]
        payload: dict[str, object] = {
            "schema": "second-brain-write-history-export-v1",
            "records": records,
            "history": history,
        }
        encoded = canonical_json(payload)
        if len(encoded) > MAX_EXPORT_BYTES:
            raise WriteRequestError("export_too_large", str(MAX_EXPORT_BYTES))
        payload["digest"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        return payload

    def _set_status(
        self,
        request_id: str,
        status: str,
        *,
        artifact_digest: str | None = None,
        page_id: str | None = None,
        result: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        detail = result or {}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE requests SET status=?, artifact_digest=COALESCE(?,artifact_digest), page_id=COALESCE(?,page_id), result_json=?, error_code=?, updated_at=? WHERE request_id=?",
                (status, artifact_digest, page_id, json.dumps(detail, sort_keys=True), error_code, now, request_id),
            )
            conn.execute(
                "INSERT INTO request_history(request_id,status,artifact_digest,detail_json,created_at) VALUES(?,?,?,?,?)",
                (request_id, status, artifact_digest, json.dumps(detail, sort_keys=True), now),
            )

    def _apply(self, request: WriteRequestV1) -> dict[str, object]:
        if request.operation == "export":
            payload = self.export()
            export_dir = self.root / ".sb" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            raw = canonical_json(payload)
            path = export_dir / f"{request.idempotency_key.replace('/', '_')[:80]}.json"
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=export_dir)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
            records = payload["records"]
            count = len(records) if isinstance(records, list) else 0
            return {"status": "exported", "artifact_digest": digest, "artifact_path": str(path.relative_to(self.root)), "items": count}
        if request.operation in {"remember", "correct", "restore"}:
            if request.summary is None:
                raise WriteRequestError("missing_summary", f"{request.operation} requires summary")
            page_id = _page_id(request.candidate_id)
            existing_path = self.root / "wiki" / f"{page_id}.md"
            current_digest = (
                f"sha256:{hashlib.sha256(existing_path.read_bytes()).hexdigest()}"
                if existing_path.is_file()
                else None
            )
            if request.expected_prior_digest is not None and current_digest != request.expected_prior_digest:
                raise WriteRequestError(
                    "prior_digest_mismatch",
                    f"expected {request.expected_prior_digest}, observed {current_digest or 'missing'}",
                )
            page = _summary_page(request, page_id, self.root)
            status = "applied" if request.operation in {"remember", "correct"} else "restored"
            restore_summary: dict[str, object] | None = None
        elif request.operation == "forget":
            page_id = _page_id(request.candidate_id)
            existing_path = self.root / "wiki" / f"{page_id}.md"
            current_digest = f"sha256:{hashlib.sha256(existing_path.read_bytes()).hexdigest()}" if existing_path.is_file() else None
            if request.expected_prior_digest is not None and current_digest != request.expected_prior_digest:
                raise WriteRequestError(
                    "prior_digest_mismatch",
                    f"expected {request.expected_prior_digest}, observed {current_digest or 'missing'}",
                )
            restore_summary = _existing_summary(self.root, page_id)
            page = _forget_page(request, page_id, self.root)
            status = "forgotten"
        else:
            raise WriteRequestError("invalid_operation", request.operation)
        result = Vault(self.root).write_pages(
            [page],
            f"request-{request.idempotency_key}",
            _PageLedger(self.root),
            compiled_by=("sb/write-request", "v1"),
        )
        del result
        artifact = hashlib.sha256(existing_path.read_bytes()).hexdigest()
        output: dict[str, object] = {
            "status": status,
            "artifact_digest": f"sha256:{artifact}",
            "page_id": page_id,
        }
        if restore_summary is not None:
            output["restore_summary"] = restore_summary
        return output


def _record(row: sqlite3.Row) -> RequestRecord:
    return RequestRecord(
        request_id=str(row["request_id"]), idempotency_key=str(row["idempotency_key"]), operation=str(row["operation"]),
        payload_digest=str(row["payload_digest"]), status=str(row["status"]), artifact_digest=row["artifact_digest"],
        page_id=row["page_id"], result=cast(dict[str, object], json.loads(row["result_json"])), error_code=row["error_code"],
    )


def _receipt(row: sqlite3.Row, *, replay: bool) -> RequestReceipt:
    return RequestReceipt(str(row["request_id"]), str(row["status"]), replay, row["artifact_digest"], row["page_id"], row["error_code"], cast(dict[str, object], json.loads(row["result_json"])))


def _page_id(candidate_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in candidate_id).strip("-")
    return f"terminal-work/{safe[:80] or 'unknown'}"


def _summary_page(request: WriteRequestV1, page_id: str, root: Path) -> PageSpec:
    assert request.summary is not None
    summary = _redact_summary(request.summary)
    content = summary.render_markdown()
    # Keep the complete canonical summary in the write-once CAS and cite that
    # blob; the JARVIS receipt remains provenance metadata.
    raw = canonical_json(summary.as_dict())
    digest = ContentAddressedStore(root).put(raw)
    sid = digest[:8]
    cite = SourceCite(sid=sid, origin=f"jarvis:closeout/{summary.jarvis_closeout_id}", hash=digest)
    correction = (
        f"\n\n## Correction\n- Supersedes prior artifact: `{request.expected_prior_digest}`"
        if request.operation == "correct" and request.expected_prior_digest
        else ""
    )
    body = f"{content}{correction}\n\n[^{sid}]"
    return PageSpec(page_id, f"Terminal work {summary.project_id}", body, [cite], "active")

def _redact_summary(summary: TerminalWorkSummaryV1) -> TerminalWorkSummaryV1:
    redact = mask_sensitive
    return replace(
        summary,
        purpose=redact(summary.purpose),
        work_performed=tuple(redact(item) for item in summary.work_performed),
        verified_results=tuple(redact(item) for item in summary.verified_results),
        failures=tuple(
            {key: redact(value) for key, value in item.items()} for item in summary.failures
        ),
        artifacts=tuple(redact(item) for item in summary.artifacts),
        commits=tuple(redact(item) for item in summary.commits),
        issues=tuple(redact(item) for item in summary.issues),
        improvements=tuple(redact(item) for item in summary.improvements),
        next_actions=tuple(redact(item) for item in summary.next_actions),
        source_refs=tuple(redact(item) for item in summary.source_refs),
    )


def _existing_summary(root: Path, page_id: str) -> dict[str, object] | None:
    page = read_page_spec(root, page_id)
    if page is None or not page.sources:
        return None
    try:
        raw = ContentAddressedStore(root).get(page.sources[0].hash)
        value = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _forget_page(request: WriteRequestV1, page_id: str, root: Path) -> PageSpec:
    raw = f"forgotten:{request.candidate_id}:{request.closeout_id}".encode()
    digest = ContentAddressedStore(root).put(raw)
    sid = digest[:8]
    body = f"# Forgotten memory\n\nThis memory was forgotten by approved request `{request.closeout_id}`.\n\n[^{sid}]"
    cite = SourceCite(sid=sid, origin=f"jarvis:forget/{request.closeout_id}", hash=digest)
    return PageSpec(page_id, f"Forgotten terminal work {request.candidate_id}", body, [cite], "forgotten")

def provider_status(root: Path | str) -> dict[str, object]:
    """Return non-mutating provider health fields for status and doctor."""
    path = Path(root) / ".sb" / REQUEST_DB
    base: dict[str, object] = {
        "contract": "second-brain-provider-v1",
        "schema": REQUEST_SCHEMA,
        "available": path.is_file(),
        "capabilities": [
            "approved_write_requests",
            "idempotency",
            "reconciliation",
            "tombstones",
            "bounded_export",
        ],
        "pending": 0,
        "reconciling": 0,
    }
    if not path.is_file():
        return base
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM requests GROUP BY status"
            ).fetchall()
        counts = {str(status): int(count) for status, count in rows}
        base["pending"] = counts.get("accepted", 0)
        base["reconciling"] = counts.get("reconciling", 0)
        base["requests"] = sum(counts.values())
        base["status"] = "ok"
    except sqlite3.Error:
        base["status"] = "error"
    return base
