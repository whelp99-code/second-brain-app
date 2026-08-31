"""Bounded stdio MCP server with additive Task 29/Task 30 compatibility modes.
# noqa: SIZE_OK -- one tool registration and shared read-pin boundary
"""

from __future__ import annotations

import base64
import itertools
import json
import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal, cast, override

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import TypeAdapter

from sb.config import load_config
from sb.contracts import MemoryWriteResultV1
from sb.delegations import DelegationRejected, verify_read_fence
from sb.effect_values import JsonObject, JsonValue, digest, is_json_object, strict_loads
from sb.effect_write_models import (
    MemoryEffectWriteAcceptedV2,
    MemoryEffectWriteErrorV2,
    MemoryEffectWriteRequestV2,
)
from sb.erasure import ErasureError, ReingressGate
from sb.generations import GenerationManifestV1, GenerationStore
from sb.inbox import RememberRejected, write_inbox
from sb.mcp_write_models import MemoryWriteRequest, MemoryWriteRequestModel
from sb.page_ids import git_rel
from sb.request_store import RequestStore
from sb.search import SearchIndex, committed_text, git_run
from sb.targets import GenerationIdentityV1, MemoryTargetSelectorV1, resolve_memory_target
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
) -> MCPServer:
    """Build a stdio server in legacy V1 or proof-bound Task 30 mode.

    Explicit test roots select Task 30 unless overridden. Runtime activation requires
    configured JARVIS public keys; a keyless genesis provider remains byte-compatible
    with the frozen Task 29 six-tool client.
    """
    config = load_config()
    root = Path(config.vault_root if vault_root is None else vault_root)
    requests = Path(
        config.request_root
        if request_root is None and vault_root is None
        else (root / ".sb" / "requests" if request_root is None else request_root)
    )
    runtime_state_root = Path(config.state_root) if vault_root is None else root / ".sb" / "task30-state"
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

    task30_enabled = (
        (vault_root is not None or public_keys is not None) if task30 is None else task30
    )
    generation_store: GenerationStore | None = None
    if task30_enabled and vault_root is None and root.is_symlink():
        generation_store = GenerationStore(
            Path(config.state_root),
            Path(config.share_root),
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

    @contextmanager
    def pin_generation() -> Generator[tuple[Path, GenerationIdentityV1], None, None]:
        if generation_store is None:
            yield root, legacy_generation_identity(root)
            return
        lease_id = f"mcp:{os.getpid()}:{next(lease_sequence)}"
        with generation_store.pin() as pin:
            journal = RequestStore(requests)
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
        store = RequestStore(requests)
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
        if not (root / "generation.json").is_file() and generation_store is None:
            return dict(payload)
        sequence, set_root = current
        return cast(ToolResult, {
            **payload,
            "provider_instance_id": generation.provider_instance_id,
            "generation_id": generation.generation_id,
            "generation_manifest_digest": generation.generation_manifest_digest,
            "vault_head": generation.vault_head,
            "vault_tree": generation.vault_tree,
            "tombstone_sequence": sequence,
            "tombstone_set_root": set_root,
        })

    def sb_search(
        query: str,
        limit: int = 10,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Search the pinned compiled wiki, daily briefs, and conflict pages."""
        with pin_generation() as (current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_read", "read", current)
            require_active_high_water(generation, current)
            hits = SearchIndex(vault_root=current_root).search(query, limit)
            payload = cast(ToolResult, {"results": [hit.as_dict() for hit in hits]})
            return bind_read(payload, generation, current)

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
            except (PathEscapeError, PageNotFoundError) as exc:
                raise ToolError(str(exc)) from exc
            return bind_read(page.as_dict(), generation, current)

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
            payload = {"conflicts": [row.as_dict() for row in open_conflicts(current_root)]}
            return bind_read(payload, generation, current)

    def sb_remember(content: str, title: str | None = None) -> dict[str, str]:
        """Record content in the legacy inbox for next-run compatibility."""
        if task30_enabled:
            reingress = ReingressGate(runtime_state_root / "reingress.db")
            try:
                reingress.check_content(content.encode("utf-8"))
            except ErasureError as exc:
                raise ToolError(str(exc)) from exc
            finally:
                reingress.close()
        try:
            rel = write_inbox(root, content, title)
        except RememberRejected as exc:
            raise ToolError(str(exc)) from exc
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
            return {
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

    def sb_request_status(
        request_id: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Return metadata-only global request status and a proof only after proved."""
        with pin_generation() as (_current_root, generation):
            current = high_water()
            require_read_fence(read_fence, "memory_status", "status", current)
            store = RequestStore(requests)
            try:
                status = store.get(request_id)
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
            return bind_read(result, generation, current)

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

    def accept_request(raw: JsonObject, is_effect: bool) -> ToolResult:
        def accept() -> MemoryEffectWriteAcceptedV2 | MemoryWriteResultV1:
            return accept_memory_write_request(
                root,
                requests,
                raw,
                datetime.now(UTC),
                public_keys=public_keys,
                provider_instance_id=config.provider_instance_id,
                revoked_delegations=config.revoked_delegation_ids,
                external_public_keys=external_public_keys,
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
                    "schema_version": 1,
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

    def sb_write_request_legacy(
        request: MemoryWriteRequestModel,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Accept unchanged Task 29 V1 bytes into the stable queue."""
        raw = cast(JsonObject, request.model_dump(mode="json"))
        return accept_request(raw, False)

    def legacy_search(
        query: str, limit: int = 10
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        return sb_search(query, limit)

    def legacy_read_page(
        id: str,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        return sb_read_page(id)

    def legacy_recent_changes(
        days: int = 7,
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        return sb_recent_changes(days)

    def legacy_open_conflicts() -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        return sb_open_conflicts()

    _ = server.tool(name="sb_search")(sb_search if task30_enabled else legacy_search)
    _ = server.tool(name="sb_read_page")(sb_read_page if task30_enabled else legacy_read_page)
    _ = server.tool(name="sb_recent_changes")(
        sb_recent_changes if task30_enabled else legacy_recent_changes
    )
    _ = server.tool(name="sb_open_conflicts")(
        sb_open_conflicts if task30_enabled else legacy_open_conflicts
    )
    _ = server.tool(name="sb_remember")(sb_remember)
    _ = server.tool(name="sb_write_request")(
        sb_write_request if task30_enabled else sb_write_request_legacy
    )
    if task30_enabled:
        _ = server.tool(name="sb_generation_status")(sb_generation_status)
        _ = server.tool(name="sb_request_status")(sb_request_status)
        _ = server.tool(name="sb_resolve_memory_target")(sb_resolve_memory_target)
    return server


def main() -> None:
    """Run the MCP server on stdio."""
    anyio.run(build_server().run_stdio_async)


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
