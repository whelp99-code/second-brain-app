from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from sb.company_auto_policy import PolicyAutoReceiptV1, policy_digest
from sb.company_auto_settings import AutoInternalRejected, AutoInternalSettings, SourceContext
from sb.company_freshness_models import FreshnessScope
from sb.company_internal_classifier import CLASSIFIER_VERSION
from sb.company_memory import CandidateRow
from sb.company_memory_authority import company_request_digest
from sb.effect_values import JsonObject, JsonValue, canonical_bytes, format_instant, strict_loads
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess

EffectOperation = Literal["accept", "complete", "mark_processed"]
_RECEIPT_DOMAIN = b"second-brain/company-memory-receipt/v1\0"
_EFFECT_DOMAIN = b"second-brain/company-internal-effect/v1\0"


def install_auto_policy(
    db: sqlite3.Connection,
    settings: AutoInternalSettings,
    workspace_id: str,
    now: datetime,
) -> str:
    digest = policy_digest(settings.policy)
    if digest in settings.revoked_policy_digests:
        raise AutoInternalRejected("POLICY_REVOKED")
    raw = canonical_bytes(model_object(settings.policy)).decode("utf-8")
    row = cast(
        tuple[str, str] | None,
        db.execute(
            """SELECT policy_digest, policy_json FROM company_auto_policies
        WHERE provider_instance_id=? AND workspace_id=? AND policy_version=?""",
            (settings.provider_instance_id, workspace_id, settings.policy.policy_version),
        ).fetchone(),
    )
    if row is not None:
        if row[0] != digest or row[1] != raw:
            raise AutoInternalRejected("POLICY_CONFLICT")
        return digest
    _ = db.execute(
        """INSERT INTO company_auto_policies
        VALUES(?,?,?,?,?,?)""",
        (
            settings.provider_instance_id,
            workspace_id,
            settings.policy.policy_version,
            digest,
            raw,
            format_instant(now),
        ),
    )
    return digest


def human_path_blocks(db: sqlite3.Connection, scope: FreshnessScope, candidate_id: str) -> bool:
    for table in ("company_handoff_outbox", "company_handoff_decisions"):
        if (
            _table(db, table)
            and db.execute(
                f"SELECT 1 FROM {table} WHERE workspace_id=? AND candidate_id=?",
                (scope.workspace_id, candidate_id),
            ).fetchone()
        ):
            return True
    claim = cast(
        tuple[str] | None,
        db.execute(
            """SELECT path FROM company_candidate_execution_claims
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?""",
            (scope.provider_instance_id, scope.workspace_id, candidate_id),
        ).fetchone(),
    )
    return claim is not None and claim[0] == "human"


def insert_assessment(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    *,
    candidate_id: str,
    content_digest: str,
    policy_digest_value: str,
    assessment_digest_value: str,
    classification: str,
    reason_codes: tuple[str, ...],
    payload: JsonObject | None,
    created_at: str,
) -> None:
    existing = cast(
        tuple[str, str] | None,
        db.execute(
            """SELECT assessment_digest, classification FROM company_auto_assessments
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?
        AND content_digest=? AND policy_digest=?""",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                candidate_id,
                content_digest,
                policy_digest_value,
            ),
        ).fetchone(),
    )
    payload_json = None if payload is None else canonical_bytes(payload).decode("utf-8")
    reasons = canonical_bytes(list(reason_codes)).decode("utf-8")
    if existing is not None:
        if existing[0] != assessment_digest_value or existing[1] != classification:
            raise AutoInternalRejected("ASSESSMENT_CONFLICT")
        return
    _ = db.execute(
        """INSERT INTO company_auto_assessments
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            candidate_id,
            content_digest,
            policy_digest_value,
            assessment_digest_value,
            classification,
            reasons,
            payload_json,
            created_at,
            CLASSIFIER_VERSION,
        ),
    )


def claim_auto(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    *,
    candidate_id: str,
    content_digest: str,
    workflow_request_id: str,
    created_at: str,
) -> bool:
    try:
        _ = db.execute(
            """INSERT INTO company_candidate_execution_claims
            VALUES(?,?,?,?, 'auto_internal', ?, ?)""",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                candidate_id,
                content_digest,
                workflow_request_id,
                created_at,
            ),
        )
    except sqlite3.IntegrityError:
        row = cast(
            tuple[str, str, str] | None,
            db.execute(
                """SELECT content_digest, path, workflow_request_id
            FROM company_candidate_execution_claims
            WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?""",
                (scope.provider_instance_id, scope.workspace_id, candidate_id),
            ).fetchone(),
        )
        if row is None or row[0] != content_digest or row[1] != "auto_internal":
            return False
        return row[2] == workflow_request_id
    return True


def save_policy_receipt(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    receipt: PolicyAutoReceiptV1,
    command: JsonObject,
    created_at: str,
) -> str:
    receipt_json = canonical_bytes(model_object(receipt)).decode("utf-8")
    digest = "sha256:" + hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
    existing = cast(
        tuple[str] | None,
        db.execute(
            """SELECT receipt_json FROM company_auto_policy_receipts
        WHERE provider_instance_id=? AND workspace_id=? AND candidate_id=?
        AND content_digest=? AND policy_digest=?""",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                receipt.candidate_id,
                receipt.content_digest,
                receipt.policy_digest,
            ),
        ).fetchone(),
    )
    if existing is not None:
        if existing[0] != receipt_json:
            raise AutoInternalRejected("POLICY_RECEIPT_CONFLICT")
        return digest
    _ = db.execute(
        """INSERT INTO company_auto_policy_receipts
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            receipt.auto_request_id,
            receipt.candidate_id,
            receipt.content_digest,
            receipt.policy_digest,
            receipt.assessment_digest,
            canonical_bytes(command).decode("utf-8"),
            receipt_json,
            digest,
            created_at,
        ),
    )
    return digest


def memory_request_digest(
    operation: EffectOperation, candidate_id: str, auto_request_id: str
) -> str:
    match operation:
        case "accept" | "mark_processed":
            return company_request_digest(
                operation,
                {"auto_request_id": auto_request_id, "candidate_id": candidate_id},
            )
        case "complete":
            return (
                "sha256:"
                + hashlib.sha256(
                    b"second-brain/company-internal-complete/v1\0"
                    + canonical_bytes(
                        {"auto_request_id": auto_request_id, "candidate_id": candidate_id}
                    ),
                ).hexdigest()
            )


def cas_candidate(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    candidate_id: str,
    content_digest: str,
    deletion: tuple[int, str],
    operation: Literal["accept", "mark_processed"],
    now: datetime,
) -> JsonObject:
    timestamp = format_instant(now)
    match operation:
        case "accept":
            changed = db.execute(
                """UPDATE company_memory_candidates
                SET state='accepted', accepted_at=?
                WHERE workspace_id=? AND candidate_id=? AND state='candidate'
                AND content_digest=? AND deletion_sequence=? AND deletion_set_root=?
                AND source_system='mail'""",
                (
                    timestamp,
                    scope.workspace_id,
                    candidate_id,
                    content_digest,
                    deletion[0],
                    deletion[1],
                ),
            )
        case "mark_processed":
            changed = db.execute(
                """UPDATE company_memory_candidates
                SET state='processed_complete', processed_at=?
                WHERE workspace_id=? AND candidate_id=? AND state='accepted'
                AND content_digest=? AND deletion_sequence=? AND deletion_set_root=?
                AND source_system='mail'""",
                (
                    timestamp,
                    scope.workspace_id,
                    candidate_id,
                    content_digest,
                    deletion[0],
                    deletion[1],
                ),
            )
    if changed.rowcount != 1:
        current = candidate_state(db, scope.workspace_id, candidate_id)
        expected = "accepted" if operation == "accept" else "processed_complete"
        if current != expected:
            raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    return candidate_result(db, scope.workspace_id, candidate_id, deletion)


def candidate_state(db: sqlite3.Connection, workspace_id: str, candidate_id: str) -> str:
    row = cast(
        tuple[str | int | float | bytes] | None,
        db.execute(
            "SELECT state FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?",
            (workspace_id, candidate_id),
        ).fetchone(),
    )
    if row is None or not isinstance(row[0], str):
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    return row[0]


def insert_memory_receipt(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    request_digest: str,
    operation: str,
    candidate_id: str,
    result: JsonObject,
    created_at: str,
) -> str:
    body: JsonObject = {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "request_digest": request_digest,
        "operation": operation,
        "candidate_id": candidate_id,
        "result": result,
        "created_at": created_at,
    }
    digest = "sha256:" + hashlib.sha256(_RECEIPT_DOMAIN + canonical_bytes(body)).hexdigest()
    receipt_id = "cmreceipt:v1:" + digest.removeprefix("sha256:")
    existing = cast(
        tuple[str, str] | None,
        db.execute(
            """SELECT receipt_id, receipt_digest FROM company_memory_receipts
        WHERE workspace_id=? AND request_digest=?""",
            (workspace_id, request_digest),
        ).fetchone(),
    )
    if existing is not None:
        if existing[0] != receipt_id or existing[1] != digest:
            raise AutoInternalRejected("RECEIPT_CONFLICT")
        return digest
    _ = db.execute(
        "INSERT INTO company_memory_receipts VALUES(?,?,?,?,?,?,?,?)",
        (
            workspace_id,
            request_digest,
            receipt_id,
            digest,
            operation,
            candidate_id,
            canonical_bytes(result).decode("utf-8"),
            created_at,
        ),
    )
    return digest


def effect_manifest(
    *,
    record_id: str,
    record_kind: str,
    entity_key: str,
    payload: JsonObject,
    source_event_id: str,
    candidate_id: str,
    content_digest: str,
    deletion: tuple[int, str],
    source_context: SourceContext,
) -> JsonObject:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "record_kind": record_kind,
        "entity_key": entity_key,
        "payload_digest": "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
        "source_event_id": source_event_id,
        "source_candidate_id": candidate_id,
        "source_slot": "primary",
        "content_digest": content_digest,
        "deletion_sequence": deletion[0],
        "deletion_set_root": deletion[1],
        "source_context": model_object(source_context),
    }


def effect_digest(manifest: JsonObject) -> str:
    return "sha256:" + hashlib.sha256(_EFFECT_DOMAIN + canonical_bytes(manifest)).hexdigest()


def record_id_for(scope: FreshnessScope, source_event_id: str, record_kind: str) -> str:
    raw = hashlib.sha256(
        canonical_bytes(
            {
                "event": source_event_id,
                "kind": record_kind,
                "provider": scope.provider_instance_id,
                "slot": "primary",
                "workspace": scope.workspace_id,
            },
        ),
    ).hexdigest()
    return "internal:v1:" + raw


def insert_effect(
    db: sqlite3.Connection,
    scope: FreshnessScope,
    *,
    operation_id: str,
    auto_request_id: str,
    candidate_id: str,
    record_kind: str,
    entity_key: str,
    payload: JsonObject,
    source_event_id: str,
    content_digest: str,
    deletion: tuple[int, str],
    created_at: str,
    forbidden_digests: tuple[str, ...],
    source_context: SourceContext,
) -> str:
    record_id = record_id_for(scope, source_event_id, record_kind)
    manifest = effect_manifest(
        record_id=record_id,
        record_kind=record_kind,
        entity_key=entity_key,
        payload=payload,
        source_event_id=source_event_id,
        candidate_id=candidate_id,
        content_digest=content_digest,
        deletion=deletion,
        source_context=source_context,
    )
    digest = effect_digest(manifest)
    if digest in forbidden_digests or digest == content_digest:
        raise AutoInternalRejected("EFFECT_DIGEST_COLLISION")
    existing = cast(
        tuple[str, str] | None,
        db.execute(
            """SELECT effect_digest, manifest_json FROM company_internal_effects
        WHERE provider_instance_id=? AND workspace_id=? AND auto_request_id=?""",
            (scope.provider_instance_id, scope.workspace_id, auto_request_id),
        ).fetchone(),
    )
    manifest_json = canonical_bytes(manifest).decode("utf-8")
    if existing is not None:
        if existing[0] != digest or existing[1] != manifest_json:
            raise AutoInternalRejected("EFFECT_CONFLICT")
        return digest
    conflict = cast(
        tuple[str] | None,
        db.execute(
            """SELECT payload_json FROM company_internal_records
        WHERE provider_instance_id=? AND workspace_id=? AND entity_key=?
        AND record_kind=?""",
            (scope.provider_instance_id, scope.workspace_id, entity_key, record_kind),
        ).fetchone(),
    )
    payload_json = canonical_bytes(payload).decode("utf-8")
    if conflict is not None and conflict[0] != payload_json:
        raise AutoInternalRejected("INTERNAL_RECORD_CONFLICT")
    _ = db.execute(
        "INSERT INTO company_internal_effects VALUES(?,?,?,?,?,?,?,?)",
        (
            scope.provider_instance_id,
            scope.workspace_id,
            operation_id,
            auto_request_id,
            candidate_id,
            digest,
            manifest_json,
            created_at,
        ),
    )
    if conflict is None:
        _ = db.execute(
            "INSERT INTO company_internal_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                scope.provider_instance_id,
                scope.workspace_id,
                record_id,
                record_kind,
                entity_key,
                payload_json,
                source_event_id,
                candidate_id,
                content_digest,
                operation_id,
                "primary",
                created_at,
            ),
        )
    return digest


def verify_internal_readback(
    database: Path,
    scope: FreshnessScope,
    operation_id: str,
    expected_digest: str,
) -> bool:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        _ = db.execute("PRAGMA query_only=ON")
        effect = cast(
            tuple[str, str, str, str] | None,
            db.execute(
                """SELECT effect_digest, manifest_json, candidate_id, auto_request_id
            FROM company_internal_effects
            WHERE provider_instance_id=? AND workspace_id=? AND operation_id=?""",
                (scope.provider_instance_id, scope.workspace_id, operation_id),
            ).fetchone(),
        )
        if effect is None or effect[0] != expected_digest:
            return False
        try:
            parsed: JsonValue = strict_loads(effect[1], 1_048_576)
        except ValueError:
            return False
        if not isinstance(parsed, dict):
            return False
        record = cast(
            tuple[str, str, str, str | bytes, str, str, str, str] | None,
            db.execute(
                """SELECT record_id, record_kind, entity_key, payload_json, source_event_id,
            source_candidate_id, content_digest, source_slot
            FROM company_internal_records
            WHERE provider_instance_id=? AND workspace_id=? AND effect_operation_id=?""",
                (scope.provider_instance_id, scope.workspace_id, operation_id),
            ).fetchone(),
        )
        if record is None or record[7] != "primary":
            return False
        if not isinstance(record[3], str):
            return False
        payload_digest = "sha256:" + hashlib.sha256(record[3].encode("utf-8")).hexdigest()
        deletion = cast(
            tuple[int, str, str, str] | None,
            db.execute(
                """SELECT deletion_sequence, deletion_set_root, content_digest, source_system
            FROM company_memory_candidates
            WHERE workspace_id=? AND candidate_id=?""",
                (scope.workspace_id, effect[2]),
            ).fetchone(),
        )
        if deletion is None or deletion[3] != "mail":
            return False
        return (
            parsed.get("record_id") == record[0]
            and parsed.get("record_kind") == record[1]
            and parsed.get("entity_key") == record[2]
            and parsed.get("payload_digest") == payload_digest
            and parsed.get("source_event_id") == record[4]
            and parsed.get("source_candidate_id") == record[5]
            and parsed.get("content_digest") == record[6]
            and parsed.get("source_slot") == "primary"
            and parsed.get("deletion_sequence") == deletion[0]
            and parsed.get("deletion_set_root") == deletion[1]
            and record[6] == deletion[2]
            and effect_digest(parsed) == expected_digest
        )


def candidate_result(
    db: sqlite3.Connection,
    workspace_id: str,
    candidate_id: str,
    deletion: tuple[int, str],
) -> JsonObject:
    row = cast(
        CandidateRow | None,
        db.execute(
            """SELECT workspace_id, candidate_id, source_system, source_locator, source_event_id,
        content, content_digest, parser_version, locator_json, owner, projects_json,
        policy_revision, deletion_sequence, deletion_set_root, state, accepted_at,
        rejected_at, processed_at
        FROM company_memory_candidates WHERE workspace_id=? AND candidate_id=?""",
            (workspace_id, candidate_id),
        ).fetchone(),
    )
    if row is None or (row[12], row[13]) != deletion:
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    projects = _string_list(row[10])
    access = SourceAccess(str(row[9]), tuple(projects), str(row[11]))
    return {
        "workspace_id": str(row[0]),
        "candidate_id": str(row[1]),
        "source_system": str(row[2]),
        "source_locator": str(row[3]),
        "source_event_id": str(row[4]),
        "content": str(row[5]),
        "content_digest": str(row[6]),
        "parser_version": str(row[7]),
        "locator": _locator(row[8]),
        "access": {
            "owner": access.owner,
            "projects": list(access.projects),
            "policy_revision": access.policy_revision,
        },
        "deletion_sequence": row[12],
        "deletion_set_root": str(row[13]),
        "state": str(row[14]),
        "accepted_at": row[15],
        "rejected_at": row[16],
        "processed_at": row[17],
    }


def _table(db: sqlite3.Connection, name: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def _string_list(raw: str) -> list[str]:
    parsed = strict_loads(raw, 1_048_576)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    return [item for item in parsed if isinstance(item, str)]


def _locator(raw: str) -> JsonObject:
    parsed = strict_loads(raw, 1_048_576)
    if not isinstance(parsed, dict):
        raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
    located: JsonObject = {}
    for key, value in parsed.items():
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise AutoInternalRejected("CANDIDATE_CAS_DENIED")
        located[key] = value
    return located
