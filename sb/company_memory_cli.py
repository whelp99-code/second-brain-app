"""Installed company-memory CLI; deliberately separate from the personal runtime."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from contextlib import closing, nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from sb.company_approver_binding import CompanyHandoffPolicy, binding_digest
from sb.company_freshness import (
    Checkpoint,
    CompanyFreshnessProvider,
    FreshnessScope,
    ReadFreshnessRequest,
    provider_from_config,
    require_freshness,
)
from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyKeyScope,
    CompanyMemoryAuthorityV1,
    canonical_workspace_id,
    verify_company_authority,
)
from sb.company_memory_cli_config import CompanyCliConfigV1
from sb.company_memory_cli_config import company_database_path as _database_path
from sb.company_memory_cli_config import company_trusted_keys as _trusted_keys
from sb.company_memory_cli_config import load_company_config as _load_config
from sb.company_memory_handoff import (
    enroll_policy,
    prepare_handoff,
    require_enrollment,
)
from sb.company_memory_reader import list_mail_candidates
from sb.company_memory_registration import register_original, registration_lock
from sb.company_memory_sources import resolve_company_source
from sb.company_processor_execution import execute_processor_transition
from sb.company_processor_finish import resume_pending_finish
from sb.company_processor_progress import (
    local_checkpoint,
    save_checkpoint,
)
from sb.company_transition_receipt import read_transition_receipt
from sb.effect_values import (
    CanonicalValueError,
    JsonObject,
    JsonValue,
    canonical_bytes,
    strict_loads,
)
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess

_MAX_CONFIG = 65_536
_MAX_REQUEST = 1_048_576


def _object(value: JsonValue, code: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CompanyMemoryError(code)
    return value


def _validate_arguments(
    operation: str,
    arguments: JsonObject,
    keys_only: bool,
    processor: bool = False,
) -> None:
    if processor:
        if operation == "read_transition_receipt":
            expected = {
                "candidate_id",
                "handoff_id",
                "operation",
                "transition_request_digest",
                "command_digest",
                "content_digest",
                "approval_policy_version",
                "approval_binding_digest",
            }
            if set(arguments) != expected:
                raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
            return
        if operation not in {"accept", "reject", "mark_processed"}:
            raise CompanyAuthorityRejected("COMPANY_PROCESSOR_OPERATION_DENIED")
        expected = {"candidate_id", "handoff_id"}
        if operation != "mark_processed":
            expected.add("approval")
        if (
            set(arguments) != expected
            or not isinstance(arguments["candidate_id"], str)
            or not isinstance(arguments["handoff_id"], str)
        ):
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        return
    if operation == "enroll_handoff":
        if arguments:
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        return
    if operation in {"list_candidates", "handoff"}:
        if (
            set(arguments) != {"limit", "offset"}
            or type(arguments["limit"]) is not int
            or type(arguments["offset"]) is not int
            or not 1 <= arguments["limit"] <= 1000
            or not 0 <= arguments["offset"] <= 2**63 - 1
        ):
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        return
    expected = {"candidate_id"}
    if operation == "receive":
        expected |= {
            "source_system",
            "source_locator",
            "source_event_id",
            "content_digest" if keys_only else "content",
            "parser_version",
            "locator",
        }
    if set(arguments) != expected:
        raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
    if not isinstance(arguments.get("candidate_id"), str):
        raise CompanyMemoryError("COMPANY_REQUEST_INVALID")


def _request(
    raw: bytes,
    keys_only: bool,
    processor: bool = False,
) -> tuple[CompanyMemoryAuthorityV1, JsonObject, JsonObject]:
    envelope = _object(strict_loads(raw, _MAX_REQUEST), "COMPANY_REQUEST_INVALID")
    if set(envelope) != {"authority", "arguments"}:
        raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
    authority_value = _object(envelope["authority"], "COMPANY_REQUEST_INVALID")
    arguments = _object(envelope["arguments"], "COMPANY_REQUEST_INVALID")
    try:
        authority = CompanyMemoryAuthorityV1.model_validate(authority_value)
    except ValidationError as exc:
        raise CompanyAuthorityRejected("COMPANY_AUTHORITY_REQUIRED") from exc
    _validate_arguments(authority.operation, arguments, keys_only, processor)
    return authority, authority_value, arguments


def run(
    config_path: Path,
    raw_request: bytes,
    *,
    now: datetime | None = None,
    register_source: bool = False,
    candidates_only: bool = False,
    handoff_only: bool = False,
    enroll_handoff: bool = False,
    process_only: bool = False,
    receipt_only: bool = False,
    freshness_provider: CompanyFreshnessProvider | None = None,
    observed_checkpoint: Checkpoint | None = None,
) -> JsonObject:
    """Serialize registrations before reading trusted config; legacy calls stay read-only."""
    with registration_lock(config_path) if register_source else nullcontext():
        return _run(
            config_path,
            raw_request,
            now=now,
            register_source=register_source,
            candidates_only=candidates_only,
            handoff_only=handoff_only,
            enroll_handoff=enroll_handoff,
            process_only=process_only,
            receipt_only=receipt_only,
            freshness_provider=freshness_provider,
            observed_checkpoint=observed_checkpoint,
        )


def _run(
    config_path: Path,
    raw_request: bytes,
    *,
    now: datetime | None,
    register_source: bool,
    candidates_only: bool,
    handoff_only: bool,
    enroll_handoff: bool,
    process_only: bool,
    receipt_only: bool,
    freshness_provider: CompanyFreshnessProvider | None,
    observed_checkpoint: Checkpoint | None,
) -> JsonObject:
    if (
        sum(
            (
                register_source,
                candidates_only,
                handoff_only,
                enroll_handoff,
                process_only,
                receipt_only,
            )
        )
        > 1
    ):
        raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
    if handoff_only or enroll_handoff or process_only or receipt_only:
        info = config_path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
        ):
            raise CompanyMemoryError("COMPANY_HANDOFF_CONFIG_PRIVATE_REQUIRED")
    config: CompanyCliConfigV1 = _load_config(config_path)
    database = _database_path(config)
    _ = canonical_workspace_id(config.workspace_id)
    scope = SourceAccess(config.principal_id, tuple(config.projects), config.policy_revision)
    context = CompanyAuthorityContext(
        config.provider_instance_id,
        config.workspace_id,
        config.principal_id,
        config.agent_id,
        config.session_id,
        scope.projects,
        config.policy_revision,
        config.deletion_sequence,
        config.deletion_set_root,
    )
    policy = config.handoff_policy
    owner_keys: dict[str, Ed25519PublicKey] = {}
    processor_keys: dict[str, Ed25519PublicKey] = {}
    if handoff_only or enroll_handoff or process_only or receipt_only:
        if policy is None or policy.processor_principal_id == config.principal_id:
            raise CompanyMemoryError("COMPANY_HANDOFF_POLICY_REQUIRED")
        owner_keys = _trusted_keys(policy.owner_approval_keys)
        processor_keys = _trusted_keys(policy.processor_keys)
        legacy_keys = _trusted_keys(config.trusted_keys)
        groups = [
            {key.public_bytes_raw() for key in group.values()}
            for group in (owner_keys, processor_keys, legacy_keys)
        ]
        id_groups = [set(group) for group in (owner_keys, processor_keys, legacy_keys)]
        if any(
            groups[i] & groups[j] or id_groups[i] & id_groups[j]
            for i, j in ((0, 1), (0, 2), (1, 2))
        ):
            raise CompanyMemoryError("COMPANY_HANDOFF_KEYS_NOT_SEPARATE")
        _ = binding_digest(context, policy)
    content = ""
    if register_source:
        envelope = _object(strict_loads(raw_request, _MAX_REQUEST), "COMPANY_REQUEST_INVALID")
        if set(envelope) != {"authority", "arguments", "content"}:
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        payload = envelope["content"]
        if not isinstance(payload, str):
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        content = payload
        raw_request = canonical_bytes(
            {
                "authority": envelope["authority"],
                "arguments": envelope["arguments"],
            }
        )
    authority, authority_value, arguments = _request(
        raw_request,
        register_source or config.source_profile is not None,
        process_only or receipt_only,
    )
    instant = now or datetime.now(UTC)
    provider = freshness_provider or provider_from_config(config.freshness_provider)
    if process_only or receipt_only:
        assert policy is not None
        _ = verify_company_authority(
            authority_value,
            arguments,
            processor_keys,
            replace(context, principal=policy.processor_principal_id),
            instant,
            key_scopes={
                key: CompanyKeyScope(
                    operations=["read_transition_receipt"]
                    if receipt_only
                    else [
                        "accept",
                        "reject",
                        "mark_processed",
                    ],
                    source_systems=["mail"],
                )
                for key in processor_keys
            },
        )
        if receipt_only:
            if authority.operation != "read_transition_receipt":
                raise CompanyAuthorityRejected("COMPANY_PROCESSOR_OPERATION_DENIED")
            return read_transition_receipt(database, context, policy, authority, arguments)
        match authority.operation:
            case "accept" | "reject" | "mark_processed" as operation:
                pass
            case _:
                raise CompanyAuthorityRejected("COMPANY_PROCESSOR_OPERATION_DENIED")
        resume_pending_finish(database, context, policy, provider)
        observed_checkpoint = local_checkpoint(database, context.workspace_id, observed_checkpoint)
        checkpoint = _check_freshness(provider, observed_checkpoint, context, policy, "startup")
        with closing(CompanyMemoryStore(database)) as store:
            receipt = execute_processor_transition(
                store,
                provider,
                context=context,
                policy=policy,
                owner_keys=owner_keys,
                authority=authority,
                operation=operation,
                arguments=arguments,
                checkpoint=checkpoint,
                now=instant,
            )
            resume_pending_finish(database, context, policy, provider)
        # Processor never returns candidate content or the content-bearing legacy receipt.
        return {
            "receipt_id": receipt.receipt_id,
            "receipt_digest": receipt.receipt_digest,
            "operation": receipt.operation,
            "state": receipt.result["state"],
            "handoff_id": arguments["handoff_id"],
        }
    if policy is not None and authority.operation in {"accept", "reject", "mark_processed"}:
        raise CompanyAuthorityRejected("COMPANY_PROCESSOR_REQUIRED")
    verified, current = verify_company_authority(
        authority_value,
        arguments,
        _trusted_keys(config.trusted_keys),
        context,
        instant,
        key_scopes=config.key_scopes,
    )
    if verified != authority:
        raise CompanyAuthorityRejected("COMPANY_AUTHORITY_REQUIRED")
    if handoff_only or enroll_handoff or authority.operation in {"handoff", "enroll_handoff"}:
        expected = "enroll_handoff" if enroll_handoff else "handoff"
        key_scope = config.key_scopes.get(authority.signing_key_id)
        if (
            not (handoff_only or enroll_handoff)
            or authority.operation != expected
            or key_scope is None
            or key_scope.operations != [expected]
            or key_scope.source_systems != ["mail"]
            or policy is None
        ):
            raise CompanyAuthorityRejected("COMPANY_HANDOFF_OPERATION_DENIED")
        resume_pending_finish(database, context, policy, provider)
        observed_checkpoint = local_checkpoint(database, context.workspace_id, observed_checkpoint)
        checkpoint = _check_freshness(provider, observed_checkpoint, context, policy, "startup")
        with closing(CompanyMemoryStore(database)) as store, store.db:
            _ = store.db.execute("BEGIN IMMEDIATE")
            if local_checkpoint(database, context.workspace_id, observed_checkpoint) != checkpoint:
                raise CompanyAuthorityRejected("COMPANY_PROGRESS_UNCERTAIN")
            if enroll_handoff:
                result = enroll_policy(store.db, context, policy, authority_value, instant)
                save_checkpoint(store.db, context.workspace_id, checkpoint)
                return result
            require_enrollment(store.db, context, policy)
            page = list_mail_candidates(database, context, arguments)
            rows = page["candidates"]
            assert isinstance(rows, list)
            handoffs: list[JsonValue] = []
            for row in rows:
                assert isinstance(row, dict) and isinstance(row["candidate_id"], str)
                candidate = store.get(
                    context.workspace_id,
                    row["candidate_id"],
                    scope,
                    (context.deletion_sequence, context.deletion_set_root),
                )
                handoffs.append(prepare_handoff(store.db, candidate, context, policy, instant))
            return {"handoffs": handoffs, "count": page["count"], **arguments}
    if candidates_only and authority.operation != "list_candidates":
        raise CompanyAuthorityRejected("COMPANY_KEY_OPERATION_DENIED")
    if authority.operation == "list_candidates":
        key_scope = config.key_scopes.get(authority.signing_key_id)
        if (
            register_source
            or key_scope is None
            or key_scope.operations != ["list_candidates"]
            or key_scope.source_systems != ["mail"]
        ):
            raise CompanyAuthorityRejected("COMPANY_CANDIDATE_READER_DENIED")
        return list_mail_candidates(database, context, arguments)
    if register_source:
        key_scope = config.key_scopes.get(authority.signing_key_id)
        if (
            authority.operation != "receive"
            or key_scope is None
            or key_scope.operations != ["receive"]
            or key_scope.source_systems != ["mail"]
        ):
            raise CompanyAuthorityRejected("COMPANY_SOURCE_REGISTRATION_DENIED")
        document = model_object(config)
        if "handoff_policy" not in config.model_fields_set:
            del document["handoff_policy"]
        if "freshness_provider" not in config.model_fields_set:
            del document["freshness_provider"]
        return register_original(
            config_path,
            document,
            database,
            config.source_profile,
            arguments,
            content,
            _MAX_CONFIG,
            config.personal_data_roots,
        )
    if authority.operation == "receive" and config.source_profile is not None:
        arguments = {
            **arguments,
            "content": resolve_company_source(
                config.source_profile,
                arguments,
                config.personal_data_roots,
            ),
        }
    store = CompanyMemoryStore(database)
    try:
        receipt = store.execute(
            workspace_id=config.workspace_id,
            request_digest=authority.request_digest,
            operation=authority.operation,
            arguments=arguments,
            current=current,
            deletion=(config.deletion_sequence, config.deletion_set_root),
            now=instant,
        )
        return cast(JsonObject, {"receipt": asdict(receipt)})
    finally:
        store.close()


def _check_freshness(
    provider: CompanyFreshnessProvider,
    checkpoint: Checkpoint | None,
    context: CompanyAuthorityContext,
    policy: CompanyHandoffPolicy,
    challenge: str,
) -> Checkpoint:
    if checkpoint is not None and (
        checkpoint.approval_policy_version != policy.approval_policy_version
        or checkpoint.approval_binding_digest != binding_digest(context, policy)
    ):
        raise CompanyAuthorityRejected("COMPANY_HANDOFF_ENROLLMENT_REQUIRED")
    verified = require_freshness(
        provider,
        ReadFreshnessRequest(
            schema_version=2,
            scope=FreshnessScope(
                provider_instance_id=context.provider,
                workspace_id=context.workspace_id,
            ),
            installation_id=context.provider,
            challenge=f"{challenge}:{uuid4().hex}",
            observed_checkpoint=checkpoint,
        ),
    )
    if (
        verified.approval_policy_version != policy.approval_policy_version
        or verified.approval_binding_digest != binding_digest(context, policy)
    ):
        raise CompanyAuthorityRejected("COMPANY_OPERATIONAL_ROLLBACK")
    return verified


def main(
    argv: list[str] | None = None,
    *,
    freshness_provider: CompanyFreshnessProvider | None = None,
    observed_checkpoint: Checkpoint | None = None,
    now: datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="sb-company")
    _ = parser.add_argument(
        "action",
        nargs="?",
        choices=[
            "register-source",
            "candidates",
            "enroll-handoff",
            "handoff",
            "process",
            "receipt",
        ],
    )
    _ = parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    action = cast(str | None, args.action)
    config_path = cast(Path | None, args.config)
    if config_path is None:
        variable = (
            "SB_COMPANY_PROCESSOR_CONFIG"
            if action in {"process", "receipt"}
            else ("SB_COMPANY_HANDOFF_CONFIG" if action in {"handoff", "enroll-handoff"} else None)
        )
        configured = os.environ.get(variable, "") if variable else ""
        if not configured:
            parser.error(
                "--config is required (or the action-specific config environment variable)"
            )
        config_path = Path(configured)
    previous_umask = os.umask(0o077)
    try:
        result = run(
            config_path,
            sys.stdin.buffer.read(_MAX_REQUEST + 1),
            now=now,
            register_source=action == "register-source",
            candidates_only=action == "candidates",
            handoff_only=action == "handoff",
            enroll_handoff=action == "enroll-handoff",
            process_only=action == "process",
            receipt_only=action == "receipt",
            freshness_provider=freshness_provider,
            observed_checkpoint=observed_checkpoint,
        )
        _ = sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
        return 0
    except (CompanyMemoryError, CompanyAuthorityRejected, CanonicalValueError, ValueError) as exc:
        code = str(exc) or "COMPANY_MEMORY_FAILED"
        _ = sys.stderr.buffer.write(canonical_bytes({"error": code}) + b"\n")
        return 2
    finally:
        _ = os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
