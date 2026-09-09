"""Generation-independent journal metadata under current signed read authority."""
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sb.access_claims import (
    AccessContext,
    access_claim_binding,
    access_request_digest,
    verify_access_claim,
)
from sb.config import Config
from sb.effect_values import JsonValue
from sb.request_store import RequestStore
from sb.scoped_read_policy import current_scoped_policy, scoped_policy
from sb.scoped_request_status import read_scoped_request_status
from sb.source_access import SourceAccess

PROFILE = "scoped-request-status-v1"


def build_scoped_status_server(config: Config) -> MCPServer:
    initial = scoped_policy(config)
    server = MCPServer("second-brain")

    def request_status(request: dict[str, JsonValue], read_fence: dict[str, JsonValue],
        access_claim: dict[str, JsonValue],
    ) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Read the original request journal; never evidence of current artifact availability."""
        try:
            started = datetime.now(UTC)
            policy = current_scoped_policy(config, initial)
            # Validate the signed request before opening a journal. The current
            # high-water is checked again against the actual journal below.
            sequence, root = read_fence.get("tombstone_sequence"), read_fence.get("tombstone_set_root")
            if type(sequence) is not int or not isinstance(root, str):
                raise ValueError("MEMORY_SCOPED_STATUS_DENIED")
            context = AccessContext(config.provider_instance_id, *policy.identity,
                "memory_status", access_request_digest("sb_request_status", {"request": request}), sequence, root)
            _ = verify_access_claim(access_claim, read_fence, policy.public_keys(), context, started)
            if not (Path(config.request_root) / "journal.db").is_file():
                raise ValueError("MEMORY_SCOPED_STATUS_DENIED")
            store = RequestStore(Path(config.request_root), maintenance_only=True)
            try:
                current = store.tombstone_high_water()
                if current != (sequence, root):
                    raise ValueError("MEMORY_SCOPED_STATUS_DENIED")

                def resolve(at: datetime) -> SourceAccess:
                    if (at < started or current_scoped_policy(config, initial) != policy
                        or store.tombstone_high_water() != current):
                        raise ValueError("MEMORY_SCOPED_STATUS_DENIED")
                    return verify_access_claim(access_claim, read_fence, policy.public_keys(), context, at)

                status = read_scoped_request_status(store, request,
                    expected_provider=config.provider_instance_id, clock=lambda: datetime.now(UTC),
                    resolve_scope=resolve, include_acceptance=True)
                _ = resolve(datetime.now(UTC))
                return {"profile": PROFILE, "request_digest": context.request_digest,
                    "access_claim_digest": access_claim_binding(access_claim),
                    "provider_instance_id": config.provider_instance_id,
                    "tombstone_sequence": sequence, "tombstone_set_root": root,
                    "request_status": status}
            finally:
                store.close()
        except (ValueError, TypeError, OSError):
            raise ToolError("MEMORY_SCOPED_STATUS_DENIED") from None

    _ = server.tool(name="sb_request_status")(request_status)
    return server
