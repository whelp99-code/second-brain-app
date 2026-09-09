"""Bounded stdio MCP server with additive Task 29/Task 30 compatibility modes.
# noqa: SIZE_OK -- one tool registration and shared read-pin boundary
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal, TypedDict, cast, override

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import TypeAdapter

from sb.access_claims import (
    AccessContext,
    access_claim_binding,
    access_request_digest,
    verify_access_claim,
)
from sb.cancellation_result import CancellationResultError
from sb.cancellation_status import CancellationStatusError, read_cancellation_status
from sb.cancellation_submission import CancellationSubmissionError, submit_correction_cancellation
from sb.config import Config, load_config
from sb.contracts import MemoryWriteResultV1
from sb.correction_cancellation_models import CorrectionCancellationIntentV1
from sb.delegations import DelegationRejected, verify_read_fence
from sb.effect_values import (
    JsonObject,
    JsonValue,
    digest,
    is_json_object,
    parse_instant,
    strict_loads,
)
from sb.effect_write_models import (
    MemoryEffectWriteAcceptedV2,
    MemoryEffectWriteErrorV2,
    MemoryEffectWriteRequestV2,
)
from sb.effect_write_values import model_object
from sb.erasure import ErasureError, ReingressGate
from sb.export_status import sign_export_status
from sb.exports import ExportPublisher
from sb.generation_reads import generation_read_binding
from sb.generation_runtime import GenerationMutationService
from sb.generations import GenerationManifestV1, GenerationStore
from sb.inbox import RememberRejected, write_inbox
from sb.mcp_remember_models import MemoryRememberWriteRequest
from sb.mcp_write_models import (
    MemoryWriteRequest,
    MemoryWriteRequestModel,
    MemoryWriteResultModel,
)
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.memory_records import (
    MemoryRecordError,
    find_record,
    records_for_page,
    target_for_record,
)
from sb.memory_search import merge_semantic_records
from sb.page_access_projection import page_access_projection
from sb.page_ids import git_rel
from sb.pipeline import RunOutcome, run_all
from sb.provider_lifecycle import ProviderLifecycle
from sb.public_page import public_frontmatter
from sb.remember_contracts import MemoryWriteResultV3
from sb.request_store import RequestStore
from sb.scoped_read_policy import current_scoped_policy, scoped_policy
from sb.scoped_search import search_scoped_records
from sb.search import SearchHitDict, SearchIndex, committed_text, git_run
from sb.search_errors import SearchQueryError
from sb.search_filters import SearchFilters
from sb.search_query import LexicalQuery
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1, MemoryTargetSelectorV1, resolve_memory_target
from sb.task30_barriers import Task30BarrierSink, UnixBarrierSink
from sb.vault import PathEscapeError
from sb.write_request_values import WriteRequestRejected
from sb.write_requests import accept_memory_write_request

__all__ = ("RememberRejected", "write_inbox")

type ToolResult = dict[str, object]
type ToolPayload = Mapping[str, object]

K5_TOOLS: Final = (
    "sb_generation_status",
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_request_status",
    "sb_resolve_memory_target",
    "sb_search",
    "sb_write_request",
)
TASK30_TOOLS: Final = K5_TOOLS
LEGACY_TOOLS: Final = (
    "sb_open_conflicts",
    "sb_read_page",
    "sb_recent_changes",
    "sb_remember",
    "sb_search",
    "sb_write_request",
)
_CHANGES: Final = {"A": "added", "M": "modified", "D": "deleted"}
_CONTRACT_PROFILE_ENV: Final = "SB_MCP_CONTRACT_PROFILE"
_TASK30_PROFILE: Final = "task30-schema3"
_TASK32_PROFILE: Final = "task32-schema4"
_REMEMBER_PROFILE: Final = "remember-schema5"
_CANCELLATION_SUBMIT_PROFILE: Final = "cancellation-submit-schema7"
_CANCELLATION_SUBMIT_CONTRACT_DIGEST: Final = "d137a7a7b0e4a577abef04d6ecb2768630e9912cd24b8f270c320cb45d60165d"
_CANCELLATION_PROFILE: Final = "cancellation-schema6"
_CANCELLATION_CONTRACT_DIGEST: Final = "8be1ca195f60cb73f05c989d3d5f3e62053020988ccd8bb028cd4d8b442063b4"
_REMEMBER_CONTRACT_DIGEST: Final = "78def950055c108a11790ea9d2f6f7729d1084114b09e89fef6a735e04e65d5e"
_TASK32_CONTRACT_DIGEST: Final = "ae2e4b4f41ade29e8781e47e60dad6ddb17ed8cea516b82ccd16454acd5dc3e0"


class ContractProfileError(RuntimeError):
    code: str

    def __init__(self) -> None:
        self.code = "SECOND_BRAIN_CONTRACT_PROFILE_INVALID"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class PageNotFoundError(Exception):
    page_id: str

    @override
    def __str__(self) -> str:
        return f"page not found: {self.page_id}"


@dataclass(frozen=True, slots=True)
class PageRead:
    frontmatter: dict[str, str]
    body: str

    def as_dict(self) -> dict[str, dict[str, str] | str]:
        return {"frontmatter": self.frontmatter, "body": self.body}


@dataclass(frozen=True, slots=True)
class ChangeRow:
    page_id: str
    change: str
    date: str

    def as_dict(self) -> dict[str, str]:
        return {"page_id": self.page_id, "change": self.change, "date": self.date}


@dataclass(frozen=True, slots=True)
class ConflictRow:
    conflict_id: str
    page_id: str
    summary: str

    def as_dict(self) -> dict[str, str]:
        return {
            "conflict_id": self.conflict_id,
            "page_id": self.page_id,
            "summary": self.summary,
        }


class RunOutcomeDict(TypedDict):
    run_id: str
    status: str
    pages: int
    conflicts: int
    errors: int
    exit_code: int
    git_commit: str | None
    already_running: bool
    written: int


def _run_outcome(outcome: RunOutcome) -> RunOutcomeDict:
    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "pages": outcome.pages,
        "conflicts": outcome.conflicts,
        "errors": outcome.errors,
        "exit_code": outcome.exit_code,
        "git_commit": outcome.git_commit,
        "already_running": outcome.already_running,
        "written": outcome.written,
    }


def read_page(root: Path, page_id: str) -> PageRead:
    """Read a committed wiki/daily/conflicts page. Rejects path escape."""
    rel = git_rel(page_id)
    text = committed_text(root, rel)
    if text is None:
        raise PageNotFoundError(page_id=page_id)
    block, body = _split_md(text)
    return PageRead(frontmatter=_frontmatter(block), body=body)


def recent_changes(root: Path, days: int = 7) -> tuple[ChangeRow, ...]:
    """Committed wiki/daily/conflicts name-status rows since `days` ago."""
    raw = git_run(
        root,
        "log",
        f"--since={max(days, 0)} days ago",
        "--name-status",
        "--pretty=format:%ad",
        "--date=short",
    )
    if raw is None or raw == "":
        return ()
    rows: list[ChangeRow] = []
    date = ""
    for line in raw.splitlines():
        if line == "":
            continue
        if "\t" not in line:
            date = line.strip()
            continue
        code, _, path = line.partition("\t")
        change = _CHANGES.get(code.strip())
        if change is None or not path.endswith(".md"):
            continue
        if not path.startswith(("wiki/", "daily/", "conflicts/")):
            continue
        rows.append(ChangeRow(page_id=path[:-3], change=change, date=date))
    return tuple(rows)


def open_conflicts(root: Path) -> tuple[ConflictRow, ...]:
    """List committed `conflicts/*.md` as K5 conflict rows."""
    raw = git_run(root, "ls-tree", "-r", "--name-only", "HEAD", "--", "conflicts")
    if raw is None:
        return ()
    rows: list[ConflictRow] = []
    for rel in raw.splitlines():
        if not rel.endswith(".md") or not rel.startswith("conflicts/"):
            continue
        text = committed_text(root, rel)
        if text is None:
            continue
        block, _body = _split_md(text)
        if _frontmatter(block).get("status") == "resolved":
            continue
        stem = Path(rel).stem
        rows.append(
            ConflictRow(conflict_id=stem, page_id=_conflict_page(stem), summary=_summary(text))
        )
    return tuple(rows)


def build_server(
    vault_root: Path | str | None = None,
    request_root: Path | str | None = None,
    *,
    task30: bool | None = None,
    contract_schema: Literal[3, 4, 5, 6, 7] | None = None,
    barrier_sink: Task30BarrierSink | None = None,
    config: Config | None = None,
) -> MCPServer:
    """Build a stdio server in legacy V1 or proof-bound Task 30 mode.

    Explicit test roots select Task 30 unless overridden. Runtime activation requires
    configured JARVIS public keys; a keyless genesis provider remains byte-compatible
    with the frozen Task 29 six-tool client.
    """
    desktop = config is not None
    config = load_config() if config is None else config
    root = Path(os.path.abspath(config.vault_root if vault_root is None else vault_root))
    requests = Path(
        config.request_root
        if request_root is None and vault_root is None
        else (root.parent / ".requests" if request_root is None else request_root)
    )
    runtime_state_root = Path(config.state_root) if vault_root is None else root.parent / ".task30-state"
    runtime_export_root = Path(config.export_root) if vault_root is None else root.parent / ".exports"
    runtime_config = Config(
        raw={
            **dict(config.raw),
            "vault_root": str(root),
            "request_root": str(requests),
            "state_root": str(runtime_state_root),
            "share_root": str(Path(config.share_root) if vault_root is None else root.parent),
            "export_root": str(runtime_export_root),
            "provider_instance_id": config.provider_instance_id,
            "provider_release_sha": config.provider_release_sha,
        }
    )
    initial_scoped_policy = scoped_policy(config) if config.raw.get("mcp_scoped_read") is not None else None
    server = MCPServer("second-brain")
    public_keys: dict[str, Ed25519PublicKey] | None = None
    configured_keys = config.jarvis_public_keys
    if configured_keys:
        try:
            public_keys = {
                key_id: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(encoded + "=="))
                for key_id, encoded in configured_keys.items()
                if key_id not in config.revoked_jarvis_signing_key_ids
            }
        except ValueError:
            public_keys = None

    provider_private_key: Ed25519PrivateKey | None = None
    if config.provider_private_key is not None:
        try:
            provider_private_key = Ed25519PrivateKey.from_private_bytes(
                base64.urlsafe_b64decode(config.provider_private_key + "==")
            )
        except ValueError:
            provider_private_key = None

    result_public_keys: dict[str, Ed25519PublicKey] = {}
    try:
        result_public_keys = {
            key_id: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(encoded + "=="))
            for key_id, encoded in config.provider_result_public_keys.items()
            if key_id not in config.revoked_provider_result_key_ids
        }
    except ValueError:
        result_public_keys = {}

    external_public_keys: dict[str, Ed25519PublicKey] | None = None
    configured_external_keys = config.external_erasure_public_keys
    if configured_external_keys:
        try:
            external_public_keys = {
                key_id: Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(encoded + "=="))
                for key_id, encoded in configured_external_keys.items()
            }
        except ValueError:
            external_public_keys = None

    if desktop:
        task30_enabled = False
        contract_schema_version = 3
    elif contract_schema is not None:
        task30_enabled = True
        contract_schema_version = contract_schema
    elif task30 is not None:
        task30_enabled = task30
        contract_schema_version = 3
    elif vault_root is not None:
        task30_enabled = True
        contract_schema_version = 3
    else:
        profile = os.environ.get(_CONTRACT_PROFILE_ENV)
        if profile is None:
            task30_enabled = False
            contract_schema_version = 3
        elif profile in {"scoped-record-read-v1", "scoped-record-read-v2", "scoped-record-read-v3"}:
            if initial_scoped_policy is None:
                raise ContractProfileError
            task30_enabled = False
            contract_schema_version = 4
        elif profile == _TASK30_PROFILE:
            task30_enabled = True
            contract_schema_version = 3
        elif profile == _TASK32_PROFILE:
            task30_enabled = True
            contract_schema_version = 4
        elif profile == _REMEMBER_PROFILE:
            task30_enabled = True
            contract_schema_version = 5
        elif profile == _CANCELLATION_SUBMIT_PROFILE:
            task30_enabled = True
            contract_schema_version = 7
        elif profile == _CANCELLATION_PROFILE:
            task30_enabled = True
            contract_schema_version = 6
        else:
            raise ContractProfileError
    generation_store: GenerationStore | None = None
    if root.is_symlink():
        generation_store = GenerationStore(
            Path(runtime_config.state_root),
            Path(runtime_config.share_root),
            provider_instance_id=config.provider_instance_id,
            provider_release_sha=config.provider_release_sha,
        )
    lease_sequence = itertools.count(1)

    def legacy_generation_identity(current_root: Path) -> GenerationIdentityV1:
        manifest_path = current_root / "generation.json"
        if manifest_path.is_file():
            try:
                value = strict_loads(manifest_path.read_bytes(), 65_536)
                if is_json_object(value):
                    manifest = TypeAdapter(GenerationManifestV1).validate_python(value)
                    return GenerationIdentityV1(
                        manifest.provider_instance_id,
                        manifest.generation_id,
                        manifest.generation_digest,
                        manifest.head,
                        manifest.tree,
                    )
            except (OSError, TypeError, ValueError):
                manifest_path = current_root / "__invalid_generation__"
        head = (git_run(current_root, "rev-parse", "HEAD") or "0" * 40).strip()
        tree = (git_run(current_root, "rev-parse", "HEAD^{tree}") or "0" * 40).strip()
        manifest_digest = digest("generation", {"head": head, "tree": tree})
        return GenerationIdentityV1(
            config.provider_instance_id,
            "sbgen:v1:" + manifest_digest[7:],
            manifest_digest,
            head,
            tree,
        )

    def maintain(now: datetime, *, read_only: bool = False) -> None:
        if vault_root is None:
            mutations = GenerationMutationService.from_config(runtime_config, maintenance_only=read_only and initial_scoped_policy is not None)
            try:
                _ = mutations.maintain_if_idle(now) if read_only else mutations.maintain(now)
            finally:
                mutations.close()
            return
        store = RequestStore(requests, maintenance_only=initial_scoped_policy is not None)
        try:
            publisher = ExportPublisher(
                runtime_export_root,
                config.provider_release_sha,
                store.exports,
            )
            _ = ProviderLifecycle(publisher).maintain(now)
        finally:
            store.close()

    @contextmanager
    def pin_generation() -> Generator[tuple[Path, GenerationIdentityV1], None, None]:
        maintain(datetime.now(UTC), read_only=True)
        if generation_store is None:
            yield root, legacy_generation_identity(root)
            return
        lease_id = f"mcp:{os.getpid()}:{next(lease_sequence)}"
        with generation_store.pin() as pin:
            journal = RequestStore(requests, maintenance_only=initial_scoped_policy is not None)
            journal.register_reader(lease_id, pin.generation.generation_id, os.getpid(), datetime.now(UTC))
            try:
                manifest = pin.generation.manifest
                yield pin.generation.root, GenerationIdentityV1(
                    manifest.provider_instance_id,
                    manifest.generation_id,
                    manifest.generation_digest,
                    manifest.head,
                    manifest.tree,
                )
            finally:
                journal.release_reader(lease_id)
                journal.close()

    def high_water() -> tuple[int, str]:
        store = RequestStore(requests, maintenance_only=initial_scoped_policy is not None)
        try:
            return store.tombstone_high_water()
        finally:
            store.close()

    def require_read_fence(
        value: dict[str, JsonValue] | None,
        purpose: Literal["memory_read", "memory_status", "memory_resolve"],
        operation: Literal["read", "status", "resolve"],
        current_high_water: tuple[int, str],
    ) -> None:
        sequence, set_root = current_high_water
        if sequence == 0 and value is None:
            return
        if public_keys is None or value is None:
            raise ToolError("TOMBSTONE_FENCE_REQUIRED")
        try:
            fence = verify_read_fence(
                value,
                public_keys,
                config.provider_instance_id,
                datetime.now(UTC),
                sequence,
                set_root,
            )
        except DelegationRejected as exc:
            raise ToolError(str(exc)) from exc
        if fence.purpose != purpose or fence.operation != operation:
            raise ToolError("TOMBSTONE_FENCE_REQUIRED")

    def require_active_high_water(generation: GenerationIdentityV1, current: tuple[int, str]) -> None:
        if generation_store is None:
            return
        manifest = generation_store.active().manifest
        if (manifest.tombstone_sequence, manifest.tombstone_set_root) != current:
            raise ToolError("TOMBSTONE_SET_STALE")
        if manifest.generation_id != generation.generation_id:
            raise ToolError("GENERATION_SPLIT_BRAIN")

    def bind_read(
        payload: ToolPayload,
        generation: GenerationIdentityV1,
        current: tuple[int, str],
    ) -> ToolResult:
        if generation_store is None and contract_schema_version == 3:
            return dict(payload)
        return cast(ToolResult, {
            **payload,
            **generation_read_binding(generation, current).as_dict(),
        })

    def query_plan(query: str) -> LexicalQuery:
        try:
            return LexicalQuery.parse(query)
        except SearchQueryError as exc:
            raise ToolError(str(exc)) from exc

    def sb_search(
        query: str,
        limit: int = 10,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Search the pinned compiled wiki, daily briefs, and conflict pages."""
        parsed = query_plan(query)
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_read", "read", current)
            require_active_high_water(generation, current)
            if limit <= 0 or not query.strip():
                return bind_read({"results": []}, generation, current)
            index = SearchIndex(vault_root=current_root, hybrid=config.search_hybrid,
                                min_similarity=config.search_min_similarity)
            results: list[ToolResult] = []
            seen_records: set[str] = set()
            seen_pages: set[str] = set()
            with closing(index.iter_lexical_hits(query, scope="reference")) as hits:
                for hit in hits:
                    row: ToolResult = {
                        "page_id": hit.page_id,
                        "section": hit.section,
                        "snippet": hit.snippet,
                        "score": hit.score,
                    }
                    if contract_schema_version >= 4:
                        if hit.page_id in seen_pages:
                            continue
                        seen_pages.add(hit.page_id)
                        records = records_for_page(current_root, hit.page_id, generation)
                        for record in sorted(records, key=lambda record: parsed.record_priority(record.record_text)):
                            if record.record_id in seen_records or not parsed.matches_record(record.record_text):
                                continue
                            seen_records.add(record.record_id)
                            results.append({**row, "snippet": record.record_text[:400],
                                            "record_id": record.record_id, "record_digest": record.record_digest})
                            if len(results) >= limit:
                                break
                    else:
                        results.append(row)
                    if len(results) >= limit:
                        break
            if contract_schema_version >= 4:
                results = merge_semantic_records(
                    results, index.semantic_hits(query, limit, filters=SearchFilters(scope="reference")),
                    current_root, generation, limit)
            return bind_read({"results": results[:limit]}, generation, current)

    def sb_read_page(
        id: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Read one committed page from exactly one pinned generation."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_read", "read", current)
            require_active_high_water(generation, current)
            try:
                page = read_page(current_root, id)
                payload: ToolResult = {"frontmatter": public_frontmatter(page.frontmatter, id), "body": page.body}
                if contract_schema_version >= 4:
                    payload = {**payload, "records": [
                        record.as_dict() for record in records_for_page(current_root, id, generation)
                    ]}
            except (PathEscapeError, PageNotFoundError, MemoryRecordError) as exc:
                raise ToolError(str(exc)) from exc
            return bind_read(payload, generation, current)

    def sb_recent_changes(
        days: int = 7,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """List committed changes from exactly one pinned generation."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_read", "read", current)
            require_active_high_water(generation, current)
            payload = {"changes": [row.as_dict() for row in recent_changes(current_root, days)]}
            return bind_read(payload, generation, current)

    def sb_open_conflicts(
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """List unresolved conflicts from exactly one pinned generation."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_read", "read", current)
            require_active_high_water(generation, current)
            conflicts: list[ToolResult] = []
            for row in open_conflicts(current_root):
                value: ToolResult = {
                    "conflict_id": row.conflict_id,
                    "page_id": row.page_id,
                    "summary": row.summary,
                }
                if contract_schema_version >= 4:
                    records = records_for_page(
                        current_root, f"conflicts/{row.conflict_id}", generation
                    )
                    value = {**value, "records": [record.as_dict() for record in records]}
                conflicts.append(value)
            return bind_read({"conflicts": conflicts}, generation, current)

    def sb_remember(content: str, title: str | None = None) -> dict[str, str]:
        """Record content in the legacy inbox for next-run compatibility."""
        maintain(datetime.now(UTC))
        if not task30_enabled and high_water()[0] != 0:
            raise ToolError("TOMBSTONE_FENCE_REQUIRED")
        if task30_enabled:
            reingress = ReingressGate(runtime_state_root / "reingress.db")
            try:
                reingress.check_content(content.encode("utf-8"))
            except ErasureError as exc:
                raise ToolError(str(exc)) from exc
            finally:
                reingress.close()
        if vault_root is not None and not root.is_symlink() and root.name != "vault":
            try:
                return {"inbox_path": write_inbox(root, content, title).as_posix()}
            except RememberRejected as exc:
                raise ToolError(str(exc)) from exc
        mutations = GenerationMutationService.from_config(runtime_config)
        try:
            rel = mutations.remember(content, title, datetime.now(UTC))
        except RememberRejected as exc:
            raise ToolError(str(exc)) from exc
        finally:
            mutations.close()
        return {"inbox_path": rel.as_posix()}

    def sb_generation_status(
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Return active generation and permanent tombstone high-water without content."""
        with pin_generation() as (_current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_status", "status", current)
            sequence, set_root = current
            pointer_health = "healthy"
            if generation_store is not None:
                manifest = generation_store.active().manifest
                if (manifest.tombstone_sequence, manifest.tombstone_set_root) != current:
                    pointer_health = "tombstone_stale"
            status: ToolResult = {
                "schema_version": 1,
                "provider_instance_id": generation.provider_instance_id,
                "provider_release_sha": config.provider_release_sha,
                "generation_id": generation.generation_id,
                "generation_manifest_digest": generation.generation_manifest_digest,
                "vault_head": generation.vault_head,
                "vault_tree": generation.vault_tree,
                "tombstone_sequence": sequence,
                "tombstone_set_root": set_root,
                "pointer_health": pointer_health,
                "journal_health": "healthy",
                "features": ["memory_effect_write_v2"],
            }
            if contract_schema_version >= 4:
                status.update({
                    "contract_schema_version": contract_schema_version,
                    "contract_digest": _contract_digest(),
                    "features": ["memory_effect_write_v2", "memory_record_identity_v1"]
                    + (["memory_remember_v3"] if contract_schema_version >= 5 else [])
                    + (["memory_cancellation_status_v1"] if contract_schema_version >= 6 else [])
                    + (["memory_cancellation_submit_v1"] if contract_schema_version == 7 else []),
                })
            return status

    def sb_request_status(
        request_id: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Return metadata-only global request status and a proof only after proved."""
        with pin_generation() as (_current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_status", "status", current)
            store = RequestStore(requests, maintenance_only=initial_scoped_policy is not None)
            try:
                status = store.get(request_id)
                observations = store.observations(request_id)
                export_lifecycle = store.exports.get(request_id)
            finally:
                store.close()
            if status is None:
                return bind_read(
                    {"schema_version": 1, "request_id": request_id, "state": "not_found"},
                    generation,
                    current,
                )
            result: ToolResult = {
                "schema_version": 1,
                "request_id": request_id,
                "request_digest": status.identity.request_digest,
                "envelope_digest": status.identity.envelope_digest,
                "idempotency_key": status.identity.idempotency_key,
                "lane_id": status.identity.lane_id,
                "operation": status.identity.operation,
                "state": status.state,
                "phase": status.phase,
                "fence": status.fence,
                "tombstone_sequence": status.identity.tombstone_sequence,
                "tombstone_set_root": status.identity.tombstone_set_root,
                "status_digest": status.status_digest,
            }
            if status.state == "proved" and status.proof_json is not None:
                result["proof"] = json.loads(status.proof_json)
                if observations is not None:
                    result["observations"] = model_object(observations)
            if (
                contract_schema_version >= 4
                and status.identity.operation == "export"
                and export_lifecycle is not None
            ):
                # A concurrent writer can defer physical expiry cleanup. Do not
                # sign stale availability, or invent completed physical disposal.
                if export_lifecycle.state == "available" and parse_instant(export_lifecycle.expires_at) <= datetime.now(UTC):
                    raise ToolError("EXPORT_EXPIRED")
                key_id = config.provider_signing_key_id
                if (
                    key_id is None
                    or provider_private_key is None
                    or status.identity.scope_digest is None
                ):
                    raise ToolError("EFFECT_TARGET_INVALID")
                result["export_status"] = sign_export_status(
                    export_lifecycle,
                    status.identity.scope_digest,
                    key_id,
                    provider_private_key,
                ).as_dict()
            return bind_read(result, generation, current)

    def sb_cancellation_status(
        intent_id: str,
        intent_digest: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Read an exact cancellation result with current status authority and public keys."""
        try:
            return dict(read_cancellation_status(
                requests / "journal.db", intent_id, intent_digest,
                provider_instance_id=config.provider_instance_id, now=datetime.now(UTC),
                read_fence=read_fence, reader_keys=public_keys or {},
                provider_keys=result_public_keys,
                revoked_provider_key_ids=config.revoked_provider_result_key_ids,
            ))
        except (CancellationStatusError, CancellationResultError, DelegationRejected) as exc:
            raise ToolError(str(exc)) from exc

    def sb_submit_cancellation(
        intent: CorrectionCancellationIntentV1,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Accept an authenticated unsent correction cancellation as suppression_pending."""
        try:
            return dict(submit_correction_cancellation(model_object(intent), config=runtime_config,
                load_authority=load_config, clock=lambda: datetime.now(UTC)))
        except (CancellationSubmissionError, ValueError, RuntimeError) as exc:
            # Only bounded machine codes reach the external caller, never paths or raw JSON.
            code = str(exc)
            if not code or len(code) > 96 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for c in code):
                code = "CANCELLATION_SUBMISSION_FAILED"
            raise ToolError(code) from exc
        except (OSError, sqlite3.Error) as exc:
            raise ToolError("CANCELLATION_SUBMISSION_FAILED") from exc

    def _contract_digest() -> str:
        filename = "second-brain-mcp-v3.json.sha256" if contract_schema_version == 5 else "second-brain-mcp-v1.json.sha256"
        expected = _REMEMBER_CONTRACT_DIGEST if contract_schema_version == 5 else _TASK32_CONTRACT_DIGEST
        if contract_schema_version == 6:
            filename, expected = "second-brain-mcp-v4.json.sha256", _CANCELLATION_CONTRACT_DIGEST
        if contract_schema_version == 7:
            filename, expected = "second-brain-mcp-v5.json.sha256", _CANCELLATION_SUBMIT_CONTRACT_DIGEST
        sidecar = Path(__file__).resolve().parent.parent / "contracts" / filename
        try:
            value = sidecar.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return expected
        except OSError as exc:
            raise ToolError("SECOND_BRAIN_CONTRACT_MISMATCH") from exc
        if value != expected:
            raise ToolError("SECOND_BRAIN_CONTRACT_MISMATCH")
        return value

    def sb_resolve_memory_target(
        page_id: str,
        exact_record: str,
        source_identity_full: str,
        sensitivity: str = "personal",
        source_owner_class: str = "provider_owned",
        source_owner_id: str = "provider",
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Resolve one exact citation under one shared generation pin."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_resolve", "resolve", current)
            require_active_high_water(generation, current)
            if sensitivity not in {"public", "personal", "sensitive", "restricted"}:
                raise ToolError("EFFECT_TARGET_INVALID")
            if source_owner_class not in {"provider_owned", "external_read_only"}:
                raise ToolError("EFFECT_TARGET_INVALID")
            selector = MemoryTargetSelectorV1(
                page_id=page_id,
                exact_record=exact_record,
                source_identity_full=source_identity_full,
                sensitivity=cast(
                    Literal["public", "personal", "sensitive", "restricted"], sensitivity
                ),
                source_owner_class=cast(
                    Literal["provider_owned", "external_read_only"], source_owner_class
                ),
                source_owner_id=source_owner_id,
            )
            try:
                target = resolve_memory_target(
                    current_root,
                    generation,
                    selector,
                    owner_digest_key=b"second-brain-owner-fixture",
                    subject_digest_key=b"second-brain-subject-fixture",
                    now=datetime.now(UTC),
                )
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            return cast(ToolResult, target.as_dict())

    def sb_resolve_memory_record(
        record_id: str,
        record_digest: str,
        generation_id: str,
        generation_manifest_digest: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Resolve only a schema-4 record identity under its exact generation pin."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_resolve", "resolve", current)
            require_active_high_water(generation, current)
            if (generation.generation_id != generation_id
                    or generation.generation_manifest_digest != generation_manifest_digest):
                raise ToolError("MEMORY_GENERATION_CHANGED")
            try:
                page_id, record = find_record(
                    current_root, generation, (record_id, record_digest)
                )
                target = target_for_record(
                    current_root, generation, (page_id, record, datetime.now(UTC))
                )
            except MemoryRecordError as exc:
                raise ToolError(str(exc)) from exc
            return cast(ToolResult, target.as_dict())

    def accept_request(raw: JsonObject, is_effect: bool) -> ToolResult:
        maintain(datetime.now(UTC))

        def accept() -> MemoryEffectWriteAcceptedV2 | MemoryWriteResultV1 | MemoryWriteResultV3:
            return accept_memory_write_request(
                root,
                requests,
                raw,
                datetime.now(UTC),
                public_keys=public_keys,
                provider_instance_id=config.provider_instance_id,
                revoked_delegations=config.revoked_delegation_ids,
                external_public_keys=external_public_keys,
                barrier_sink=barrier_sink,
            )

        try:
            if is_effect:
                with pin_generation():
                    result = accept()
            else:
                result = accept()
        except WriteRequestRejected as exc:
            raw_id = raw.get("request_id")
            request_id = (
                raw_id
                if isinstance(raw_id, str) and raw_id.startswith("memeff:req:v2:")
                else None
            )
            if is_effect:
                error = MemoryEffectWriteErrorV2(
                    schema_version=2,
                    kind="error",
                    code=exc.code,
                    retryable=False,
                    request_id=request_id,
                ).model_dump(mode="json")
            else:
                error = {
                    "schema_version": 3 if raw.get("schema_version") == 3 else 1,
                    "kind": "error",
                    "code": exc.code,
                    "retryable": False,
                }
            raise ToolError(json.dumps(error, sort_keys=True, separators=(",", ":"))) from exc
        if isinstance(result, MemoryEffectWriteAcceptedV2):
            return cast(ToolResult, result.model_dump(mode="json"))
        return cast(ToolResult, asdict(result))

    def sb_write_request(
        request: MemoryWriteRequest,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Accept the exact closed V1/V2 request union into the stable queue."""
        raw = cast(JsonObject, request.model_dump(mode="json"))
        return accept_request(raw, isinstance(request, MemoryEffectWriteRequestV2))

    def sb_write_remember_request(
        request: MemoryRememberWriteRequest,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Accept closed V1/V2 requests or explicit plain-text-v1 remember V3."""
        raw = cast(JsonObject, request.model_dump(mode="json"))
        return accept_request(raw, isinstance(request, MemoryEffectWriteRequestV2))

    sb_write_remember_request.__name__ = "sb_write_request"

    def require_legacy_genesis() -> None:
        if high_water()[0] != 0:
            raise ToolError("TOMBSTONE_FENCE_REQUIRED")

    def legacy_search(query: str, limit: int = 10) -> dict[str, list[SearchHitDict]]:
        """Search the compiled wiki, daily briefs, and conflict pages for `query`.

        Use this to answer questions about what the user has recorded before.
        Returns ranked sections with a snippet and the `page_id` to pass to
        `sb_read_page`.
        """
        _ = query_plan(query)
        with pin_generation() as (current_root, _generation):
            require_legacy_genesis()
            hits = SearchIndex(vault_root=current_root, hybrid=config.search_hybrid,
                               min_similarity=config.search_min_similarity).search(query, limit, scope="reference")
            return {"results": [hit.as_dict() for hit in hits]}

    def legacy_read_page(id: str) -> dict[str, dict[str, str] | str]:
        """Read one committed page whole, with its citation frontmatter.

        `id` is a `page_id` from `sb_search`, `sb_recent_changes`, or
        `sb_open_conflicts` (`daily/2026-08-26`, `conflicts/<slug>`, or a bare
        wiki id). Read the page before quoting it; snippets are truncated.
        """
        with pin_generation() as (current_root, _generation):
            require_legacy_genesis()
            try:
                page = read_page(current_root, id)
            except (PathEscapeError, PageNotFoundError) as exc:
                raise ToolError(str(exc)) from exc
            return page.as_dict()

    def legacy_recent_changes(days: int = 7) -> dict[str, list[dict[str, str]]]:
        """List pages added, modified, or deleted in the last `days` days.

        Use this for "what changed" or "what have I been working on" questions,
        or to find the newest page before reading it.
        """
        with pin_generation() as (current_root, _generation):
            require_legacy_genesis()
            return {"changes": [row.as_dict() for row in recent_changes(current_root, days)]}

    def legacy_open_conflicts() -> dict[str, list[dict[str, str]]]:
        """List unresolved contradictions between recorded sources.

        Each row names the conflicted `page_id`. Check this before stating a
        fact from the wiki as settled.
        """
        with pin_generation() as (current_root, _generation):
            require_legacy_genesis()
            return {"conflicts": [row.as_dict() for row in open_conflicts(current_root)]}

    def legacy_remember(content: str, title: str | None = None) -> dict[str, str]:
        """Record `content` as a note for the second brain to absorb.

        This is the only write. Use it whenever the user says to remember,
        note, or record something, including personal details. The note lands
        in the vault inbox and is picked up by the next ingest run; it does not
        appear in search immediately.
        """
        return sb_remember(content, title)

    def legacy_write_request(request: MemoryWriteRequestModel) -> MemoryWriteResultModel:
        """Accept one closed JARVIS memory request into the pending inbox queue."""
        require_legacy_genesis()
        raw = cast(JsonObject, request.model_dump(mode="json"))
        return MemoryWriteResultModel.model_validate(accept_request(raw, False))

    def desktop_search(query: str, limit: int = 10, scope: Literal["active", "candidate", "reference"] = "reference") -> dict[str, list[SearchHitDict]]:
        """Search cited knowledge, distinguishing verified and reference results."""
        _ = query_plan(query)
        with pin_generation() as (current_root, _generation):
            require_legacy_genesis()
            return {"results": [hit.as_dict() for hit in SearchIndex(current_root, hybrid=config.search_hybrid,
                min_similarity=config.search_min_similarity).search(query, limit, scope=scope)]}

    def sb_run() -> RunOutcomeDict:
        """Immediately process explicit capture using the single writer pipeline."""
        return _run_outcome(run_all(runtime_config, runtime_config.configured_source_ids))

    if initial_scoped_policy is not None:
        if generation_store is None or not public_keys:
            raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")

        scoped_v3 = os.environ.get(_CONTRACT_PROFILE_ENV) == "scoped-record-read-v3"
        scoped_v2 = scoped_v3 or os.environ.get(_CONTRACT_PROFILE_ENV) == "scoped-record-read-v2"
        if initial_scoped_policy.identity[2] is None and not scoped_v2:
            raise ValueError("MEMORY_SCOPED_CONFIG_INVALID")

        def scoped_request(method: str, arguments: JsonObject, read_fence: dict[str, JsonValue],
            access_claim: dict[str, JsonValue], reader: Callable[[Path, GenerationIdentityV1, SourceAccess], dict[str, object]],
        ) -> dict[str, object]:
            try:
                with pin_generation() as (current_root, generation):
                    current = high_water()
                    policy = current_scoped_policy(config, initial_scoped_policy)
                    context = AccessContext(config.provider_instance_id, *policy.identity,
                        "memory_status" if method == "sb_generation_status" else "memory_read", access_request_digest(method, arguments), *current)
                    scope = verify_access_claim(access_claim, read_fence, policy.public_keys(), context, datetime.now(UTC))
                    require_active_high_water(generation, current)
                    payload = reader(current_root, generation, scope)
                    if current_scoped_policy(config, initial_scoped_policy) != policy or high_water() != current:
                        raise MemoryAccessError("MEMORY_ACCESS_UNAVAILABLE")
                    require_active_high_water(generation, current)
                    _ = verify_access_claim(access_claim, read_fence, policy.public_keys(), context, datetime.now(UTC))
                    return {"profile": "scoped-record-read-v3" if scoped_v3 else "scoped-record-read-v2" if scoped_v2 else "scoped-record-read-v1", "request_digest": context.request_digest,
                        "access_claim_digest": access_claim_binding(access_claim), **payload,
                        **generation_read_binding(generation, current).as_dict()}
            except (ValueError, OSError, PathEscapeError) as exc:
                raise ToolError("MEMORY_SCOPED_READ_DENIED") from exc

        def scoped_read_page(id: str, read_fence: dict[str, JsonValue], access_claim: dict[str, JsonValue]) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
            """Read classified records under an exact signed request and pinned session scope."""
            def read(current_root: Path, generation: GenerationIdentityV1, scope: SourceAccess) -> dict[str, object]:
                page = classified_page(current_root, id, generation)
                require_scope(page, scope)
                if (page.tombstone_sequence, page.tombstone_set_root) != high_water():
                    raise MemoryAccessError("MEMORY_ACCESS_UNAVAILABLE")
                return {"page_id": page.page_id, "content_digest": page.content_digest,
                        "records": [record.as_dict() for record in page.records],
                        **({"page_access": page_access_projection(page)} if scoped_v3 else {})}
            return scoped_request("sb_read_page", {"id": id}, read_fence, access_claim, read)

        def scoped_search(query: str, read_fence: dict[str, JsonValue], access_claim: dict[str, JsonValue], limit: int = 10) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
            """Search only classified records in the signed project scope; limit 1 to 50."""
            return scoped_request("sb_search", {"query": query, "limit": limit}, read_fence, access_claim,
                lambda root, generation, scope: {"results": search_scoped_records(root, generation, scope, query, limit)})

        def scoped_generation_status(read_fence: dict[str, JsonValue], access_claim: dict[str, JsonValue]) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
            """Return authorized active generation health without page content."""
            return scoped_request("sb_generation_status", {}, read_fence, access_claim,
                lambda root, generation, scope: {"schema_version": 1, "pointer_health": "healthy", "journal_health": "healthy"})

        if scoped_v2:
            _ = server.tool(name="sb_generation_status")(scoped_generation_status)
        _ = server.tool(name="sb_read_page")(scoped_read_page)
        _ = server.tool(name="sb_search")(scoped_search)
        return server

    if desktop:
        _ = server.tool(name="sb_run")(sb_run)
    _ = server.tool(name="sb_search")(desktop_search if desktop else sb_search if task30_enabled else legacy_search)
    _ = server.tool(name="sb_read_page")(sb_read_page if task30_enabled else legacy_read_page)
    _ = server.tool(name="sb_recent_changes")(
        sb_recent_changes if task30_enabled else legacy_recent_changes
    )
    _ = server.tool(name="sb_open_conflicts")(
        sb_open_conflicts if task30_enabled else legacy_open_conflicts
    )
    _ = server.tool(name="sb_remember")(sb_remember if task30_enabled else legacy_remember)
    _ = server.tool(name="sb_write_request")(
        sb_write_remember_request if contract_schema_version >= 5 else sb_write_request if task30_enabled else legacy_write_request
    )
    if task30_enabled:
        _ = server.tool(name="sb_generation_status")(sb_generation_status)
        _ = server.tool(name="sb_request_status")(sb_request_status)
        if contract_schema_version >= 6:
            _ = server.tool(name="sb_cancellation_status")(sb_cancellation_status)
        if contract_schema_version == 7:
            _ = server.tool(name="sb_submit_cancellation")(sb_submit_cancellation)
        resolver = sb_resolve_memory_record if contract_schema_version >= 4 else sb_resolve_memory_target
        _ = server.tool(name="sb_resolve_memory_target")(resolver)
    return server


def main() -> None:
    """Run the MCP server on stdio."""
    parser = argparse.ArgumentParser(prog="python -m sb.mcp")
    _ = parser.add_argument("--test-control-socket")
    arguments = parser.parse_args(sys.argv[1:])
    control_value = vars(arguments).get("test_control_socket")
    control = control_value if isinstance(control_value, str) else None
    sink = None if control is None else UnixBarrierSink(Path(control))
    if sink is not None:
        sink.await_trigger("mcp")
    try:
        anyio.run(build_server(barrier_sink=sink).run_stdio_async)
    finally:
        if sink is not None:
            sink.close()


def _split_md(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return "", text
    return rest[:end], rest[end + 4 :].lstrip("\n")


def _frontmatter(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in block.splitlines():
        if raw == "" or raw[0] in {" ", "\t", "-", "#"}:
            continue
        key, sep, value = raw.partition(":")
        if sep:
            out[key.strip()] = value.strip().strip("'\"")
    return out


def _conflict_page(stem: str) -> str:
    if len(stem) >= 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-":
        return stem[11:]
    return stem


def _summary(text: str) -> str:
    _, body = _split_md(text)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


if __name__ == "__main__":
    main()
