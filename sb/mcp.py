"""Bounded stdio MCP server: K5 tools plus isolated pending-request writes."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast, override

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import TypeAdapter

from sb.config import load_config
from sb.delegations import DelegationRejected, verify_read_fence
from sb.effect_values import JsonValue, digest, is_json_object, strict_loads
from sb.effect_write_models import (
    MemoryEffectWriteAcceptedV2,
    MemoryEffectWriteErrorV2,
    MemoryEffectWriteRequestV2,
)
from sb.generations import GenerationManifestV1
from sb.inbox import RememberRejected, write_inbox
from sb.mcp_write_models import (
    MemoryWriteRequest,
)
from sb.page_ids import git_rel
from sb.request_store import RequestStore
from sb.search import SearchIndex, committed_text, git_run
from sb.targets import (
    GenerationIdentityV1,
    MemoryTargetSelectorV1,
    resolve_memory_target,
)
from sb.vault import PathEscapeError
from sb.write_request_values import WriteRequestRejected
from sb.write_requests import accept_memory_write_request

__all__ = ("RememberRejected", "write_inbox")

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
) -> MCPServer:
    """Build the stdio MCP server over one pinned vault and stable request root."""
    config = load_config()
    root = Path(config.vault_root if vault_root is None else vault_root)
    requests = Path(
        config.request_root
        if request_root is None and vault_root is None
        else (root / ".sb" / "requests" if request_root is None else request_root)
    )
    server = MCPServer("second-brain")
    public_keys: dict[str, Ed25519PublicKey] | None = None
    configured_keys = config.jarvis_public_keys
    if configured_keys:
        try:
            public_keys = {
                key_id: Ed25519PublicKey.from_public_bytes(
                    base64.urlsafe_b64decode(encoded + "==")
                )
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
                key_id: Ed25519PublicKey.from_public_bytes(
                    base64.urlsafe_b64decode(encoded + "==")
                )
                for key_id, encoded in configured_external_keys.items()
            }
        except ValueError:
            external_public_keys = None

    def generation_identity() -> GenerationIdentityV1:
        manifest_path = root / "generation.json"
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
                pass
        head = (git_run(root, "rev-parse", "HEAD") or "0" * 40).strip()
        tree = (git_run(root, "rev-parse", "HEAD^{tree}") or "0" * 40).strip()
        manifest_digest = digest("generation", {"head": head, "tree": tree})
        return GenerationIdentityV1(
            config.provider_instance_id,
            "sbgen:v1:" + manifest_digest[7:],
            manifest_digest,
            head,
            tree,
        )

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
    ) -> None:
        sequence, set_root = high_water()
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

    def bind_read(payload: Mapping[str, object]) -> dict[str, object]:
        if not (root / "generation.json").is_file():
            return dict(payload)
        generation = generation_identity()
        sequence, set_root = high_water()
        return {
            **payload,
            "provider_instance_id": generation.provider_instance_id,
            "generation_id": generation.generation_id,
            "generation_manifest_digest": generation.generation_manifest_digest,
            "vault_head": generation.vault_head,
            "vault_tree": generation.vault_tree,
            "tombstone_sequence": sequence,
            "tombstone_set_root": set_root,
        }

    @server.tool(name="sb_search")
    def sb_search(
        query: str,
        limit: int = 10,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """Search the compiled wiki, daily briefs, and conflict pages for `query`.

        Use this to answer questions about what the user has recorded before.
        Returns ranked sections with a snippet and the `page_id` to pass to
        `sb_read_page`.
        """
        require_read_fence(read_fence, "memory_read", "read")
        hits = SearchIndex(vault_root=root).search(query, limit)
        return bind_read({"results": [hit.as_dict() for hit in hits]})

    @server.tool(name="sb_read_page")
    def sb_read_page(
        id: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """Read one committed page whole, with its citation frontmatter.

        `id` is a `page_id` from `sb_search`, `sb_recent_changes`, or
        `sb_open_conflicts` (`daily/2026-08-26`, `conflicts/<slug>`, or a bare
        wiki id). Read the page before quoting it; snippets are truncated.
        """
        require_read_fence(read_fence, "memory_read", "read")
        try:
            page = read_page(root, id)
        except (PathEscapeError, PageNotFoundError) as exc:
            raise ToolError(str(exc)) from exc
        return bind_read(page.as_dict())

    @server.tool(name="sb_recent_changes")
    def sb_recent_changes(
        days: int = 7,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """List pages added, modified, or deleted in the last `days` days.

        Use this for "what changed" or "what have I been working on" questions,
        or to find the newest page before reading it.
        """
        require_read_fence(read_fence, "memory_read", "read")
        return bind_read({"changes": [row.as_dict() for row in recent_changes(root, days)]})

    @server.tool(name="sb_open_conflicts")
    def sb_open_conflicts(
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """List unresolved contradictions between recorded sources.

        Each row names the conflicted `page_id`. Check this before stating a
        fact from the wiki as settled.
        """
        require_read_fence(read_fence, "memory_read", "read")
        return bind_read({"conflicts": [row.as_dict() for row in open_conflicts(root)]})

    @server.tool(name="sb_remember")
    def sb_remember(content: str, title: str | None = None) -> dict[str, str]:
        """Record `content` as a note for the second brain to absorb.

        This is the only write. Use it whenever the user says to remember,
        note, or record something, including personal details. The note lands
        in the vault inbox and is picked up by the next ingest run; it does not
        appear in search immediately.
        """
        try:
            rel = write_inbox(root, content, title)
        except RememberRejected as exc:
            raise ToolError(str(exc)) from exc
        return {"inbox_path": rel.as_posix()}

    @server.tool(name="sb_generation_status")
    def sb_generation_status(read_fence: dict[str, JsonValue] | None = None) -> dict[str, object]:
        """Return the active generation and permanent tombstone high-water without content."""
        require_read_fence(read_fence, "memory_status", "status")
        generation = generation_identity()
        sequence, set_root = high_water()
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
            "pointer_health": "healthy",
            "journal_health": "healthy",
            "features": ["memory_effect_write_v2"],
        }

    @server.tool(name="sb_request_status")
    def sb_request_status(
        request_id: str,
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """Return metadata-only global request status and a proof only after proved."""
        require_read_fence(read_fence, "memory_status", "status")
        store = RequestStore(requests)
        try:
            status = store.get(request_id)
        finally:
            store.close()
        if status is None:
            return {"schema_version": 1, "request_id": request_id, "state": "not_found"}
        result: dict[str, object] = {
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
        return result

    @server.tool(name="sb_resolve_memory_target")
    def sb_resolve_memory_target(
        page_id: str,
        exact_record: str,
        source_identity_full: str,
        sensitivity: str = "personal",
        source_owner_class: str = "provider_owned",
        source_owner_id: str = "provider",
        read_fence: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        """Resolve one exact committed citation record under a pinned generation."""
        require_read_fence(read_fence, "memory_resolve", "resolve")
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
                root,
                generation_identity(),
                selector,
                owner_digest_key=b"second-brain-owner-fixture",
                subject_digest_key=b"second-brain-subject-fixture",
                now=datetime.now(UTC),
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return target.as_dict()

    @server.tool(name="sb_write_request")
    def sb_write_request(
        request: MemoryWriteRequest,
    ) -> dict[str, object]:
        """Accept the exact closed V1/V2 request union into the stable queue."""
        raw = request.model_dump(mode="json")
        try:
            result = accept_memory_write_request(
                root,
                requests,
                raw,
                datetime.now(UTC),
                public_keys=public_keys,
                provider_instance_id=config.provider_instance_id,
                revoked_delegations=config.revoked_delegation_ids,
                external_public_keys=external_public_keys,
            )
        except WriteRequestRejected as exc:
            if isinstance(request, MemoryEffectWriteRequestV2):
                request_id: str | None = request.request_id
            else:
                raw_id = raw.get("request_id")
                request_id = raw_id if isinstance(raw_id, str) and raw_id.startswith("memeff:req:v2:") else None
            if raw.get("schema_version") == 2:
                error = MemoryEffectWriteErrorV2(
                    schema_version=2,
                    kind="error",
                    code=exc.code,
                    retryable=False,
                    request_id=request_id,
                ).model_dump(mode="json")
            else:
                error = {"schema_version": 1, "kind": "error", "code": exc.code, "retryable": False}
            raise ToolError(json.dumps(error, sort_keys=True, separators=(",", ":"))) from exc
        if isinstance(result, MemoryEffectWriteAcceptedV2):
            return cast(dict[str, object], result.model_dump(mode="json"))
        return cast(dict[str, object], asdict(result))

    _ = (
        sb_search,
        sb_read_page,
        sb_recent_changes,
        sb_open_conflicts,
        sb_remember,
        sb_generation_status,
        sb_request_status,
        sb_resolve_memory_target,
        sb_write_request,
    )
    return server


def main() -> None:
    """Run the K5 MCP server on stdio."""
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
