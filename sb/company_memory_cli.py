"""Installed company-memory CLI; deliberately separate from the personal runtime."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError

from sb.company_memory import CompanyMemoryError, CompanyMemoryStore
from sb.company_memory_authority import (
    CompanyAuthorityContext,
    CompanyAuthorityRejected,
    CompanyKeyScope,
    CompanyMemoryAuthorityV1,
    canonical_workspace_id,
    verify_company_authority,
)
from sb.company_memory_reader import list_mail_candidates
from sb.company_memory_registration import register_original, registration_lock
from sb.company_memory_sources import CompanySourceProfile, resolve_company_source
from sb.effect_values import (
    CanonicalValueError,
    JsonObject,
    JsonValue,
    canonical_bytes,
    strict_loads,
)
from sb.effect_write_models import ClosedModel
from sb.effect_write_values import model_object
from sb.source_access import SourceAccess

_MAX_CONFIG = 65_536
_MAX_REQUEST = 1_048_576


class CompanyCliConfigV1(ClosedModel):
    schema_version: Literal[1]
    company_database: str
    personal_data_roots: list[str]
    provider_instance_id: str
    workspace_id: str
    principal_id: str
    agent_id: str
    session_id: str
    projects: list[str]
    policy_revision: str
    deletion_sequence: int
    deletion_set_root: str
    trusted_keys: dict[str, str]
    source_profile: CompanySourceProfile | None = None
    key_scopes: dict[str, CompanyKeyScope] = Field(default_factory=dict)


def _object(value: JsonValue, code: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CompanyMemoryError(code)
    return value


def _load_config(path: Path) -> CompanyCliConfigV1:
    try:
        config = CompanyCliConfigV1.model_validate(
            _object(strict_loads(path.read_bytes(), _MAX_CONFIG), "COMPANY_CONFIG_INVALID")
        )
        if not config.key_scopes.keys() <= config.trusted_keys.keys():
            raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
        return config
    except (OSError, ValueError, ValidationError, CanonicalValueError) as exc:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID") from exc


def _database_path(config: CompanyCliConfigV1) -> Path:
    database = Path(config.company_database)
    roots = [Path(value) for value in config.personal_data_roots]
    if not database.is_absolute() or not roots or any(not root.is_absolute() for root in roots):
        raise CompanyMemoryError("COMPANY_DATABASE_ISOLATION_REQUIRED")
    resolved_database = database.resolve(strict=False)
    if database.is_symlink() or any(
        resolved_database == root.resolve(strict=False)
        or resolved_database.is_relative_to(root.resolve(strict=False))
        for root in roots
    ):
        raise CompanyMemoryError("COMPANY_DATABASE_ISOLATION_REQUIRED")
    if not resolved_database.parent.is_dir():
        raise CompanyMemoryError("COMPANY_DATABASE_PARENT_REQUIRED")
    return resolved_database


def _trusted_keys(values: dict[str, str]) -> dict[str, Ed25519PublicKey]:
    result: dict[str, Ed25519PublicKey] = {}
    try:
        for key_id, encoded in values.items():
            if not key_id or len(encoded) != 43 or "=" in encoded:
                raise ValueError("invalid key")
            raw = base64.urlsafe_b64decode(encoded + "=")
            if len(raw) != 32:
                raise ValueError("invalid key")
            result[key_id] = Ed25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError) as exc:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID") from exc
    if not result:
        raise CompanyMemoryError("COMPANY_CONFIG_INVALID")
    return result


def _validate_arguments(operation: str, arguments: JsonObject, keys_only: bool) -> None:
    if operation == "list_candidates":
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
    _validate_arguments(authority.operation, arguments, keys_only)
    return authority, authority_value, arguments


def run(
    config_path: Path,
    raw_request: bytes,
    *,
    now: datetime | None = None,
    register_source: bool = False,
    candidates_only: bool = False,
) -> JsonObject:
    """Serialize registrations before reading trusted config; legacy calls stay read-only."""
    with registration_lock(config_path) if register_source else nullcontext():
        return _run(
            config_path, raw_request, now=now, register_source=register_source,
            candidates_only=candidates_only,
        )


def _run(
    config_path: Path,
    raw_request: bytes,
    *,
    now: datetime | None,
    register_source: bool,
    candidates_only: bool,
) -> JsonObject:
    config = _load_config(config_path)
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
    content = ""
    if register_source:
        envelope = _object(strict_loads(raw_request, _MAX_REQUEST), "COMPANY_REQUEST_INVALID")
        if set(envelope) != {"authority", "arguments", "content"}:
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        payload = envelope["content"]
        if not isinstance(payload, str):
            raise CompanyMemoryError("COMPANY_REQUEST_INVALID")
        content = payload
        raw_request = canonical_bytes({
            "authority": envelope["authority"], "arguments": envelope["arguments"],
        })
    authority, authority_value, arguments = _request(
        raw_request, register_source or config.source_profile is not None,
    )
    instant = now or datetime.now(UTC)
    verified, current = verify_company_authority(
        authority_value, arguments, _trusted_keys(config.trusted_keys), context, instant,
        key_scopes=config.key_scopes,
    )
    if verified != authority:
        raise CompanyAuthorityRejected("COMPANY_AUTHORITY_REQUIRED")
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
        return register_original(
            config_path, model_object(config), database, config.source_profile,
            arguments, content, _MAX_CONFIG, config.personal_data_roots,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sb-company")
    _ = parser.add_argument("action", nargs="?", choices=["register-source", "candidates"])
    _ = parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    config_path = cast(Path, args.config)
    previous_umask = os.umask(0o077)
    try:
        result = run(
            config_path, sys.stdin.buffer.read(_MAX_REQUEST + 1),
            register_source=args.action == "register-source",
            candidates_only=args.action == "candidates",
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
