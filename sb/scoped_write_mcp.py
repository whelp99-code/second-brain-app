"""Explicit scoped write MCP surface using the normal provider authority channel."""
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from sb.config import Config
from sb.effect_values import JsonValue
from sb.scoped_provider_runtime import configured_scoped_provider_authority
from sb.scoped_request_acceptance import accept_scoped_request
from sb.task30_barriers import Task30BarrierSink

PROFILE = "scoped-request-write-v1"


def build_scoped_write_server(config: Config, *, barrier_sink: Task30BarrierSink | None = None) -> MCPServer:
    if config.raw.get("mcp_scoped_read") is not None:
        raise ValueError("SCOPED_WRITE_PROFILE_CONFIG_INVALID")
    authority = configured_scoped_provider_authority(config)
    if authority is None:
        raise ValueError("SCOPED_WRITE_PROFILE_CONFIG_INVALID")
    server = MCPServer("second-brain")
    root, provider = Path(config.request_root), config.provider_instance_id

    def write_request(request: dict[str, JsonValue]) -> Annotated[dict[str, object], "# noqa: OBJECT_OK"]:
        """Accept a currently authorized scoped V4 request; acceptance is not completion."""
        try:
            accepted = accept_scoped_request(root, request, expected_provider=provider,
                clock=lambda: datetime.now(UTC), validate_authority=authority, barrier_sink=barrier_sink)
            return asdict(accepted)
        except (OSError, ValueError, RuntimeError):
            # An interrupted call is not proof of non-acceptance. Recover status
            # with the original request rather than blindly retransmitting.
            raise ToolError("SCOPED_WRITE_REQUEST_UNAVAILABLE") from None

    _ = server.tool(name="sb_write_request")(write_request)
    return server
