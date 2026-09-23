"""T02: installed CLI and HTTP process identities, including a negative control."""
import http.client
import json
import os
import selectors
import subprocess
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from pydantic import TypeAdapter

from sb.runtime_identity import IdentityReport


class McpServerInfo(TypedDict):
    name: str
    description: str


class McpResult(TypedDict):
    protocolVersion: str
    serverInfo: McpServerInfo


class McpInitialize(TypedDict):
    jsonrpc: str
    id: int
    result: McpResult


class McpIdentity(TypedDict):
    source_commit: str | None
    wheel_sha: str | None
    contract_profile_digest: str
    process_entrypoint: str


class ReadyPayload(TypedDict):
    status: str
    reasons: list[str]
    identity: IdentityReport


class Artifacts(Protocol):
    wheel: Path
    wheel_sha256: str
    source_commit: str
    fixture_root: Path
    interpreter: Path
    installed_sb: Path


class IdentityFailure(RuntimeError):
    """An installed surface broke its artifact identity contract."""


def run(artifacts: Artifacts, scenario: Literal["happy", "failure"]) -> list[str]:
    """Observe installed CLI, MCP, and HTTP processes through their actual surfaces."""
    fixture = artifacts.fixture_root / "T02"
    fixture.mkdir(parents=True, exist_ok=True)
    wheel = fixture / artifacts.wheel.name
    if not wheel.exists():
        wheel.symlink_to(artifacts.wheel)
    manifest = fixture / "release-manifest.json"
    _ = manifest.write_text(json.dumps({"source_commit": artifacts.source_commit,
        "wheel_sha256": artifacts.wheel_sha256, "contract_profile": "task32-schema4",
        "contract_profile_digest": "0" * 64 if scenario == "failure" else None,
        "working_tree_modified": False}))
    config = fixture / "config.toml"
    _ = config.write_text(f'vault_root = "{fixture / "vault"}"\nbackup_root = "{fixture / "backup"}"\nprovider_instance_id = "fixture-provider"\n')
    env = {**os.environ, "SB_CONFIG": str(config), "SB_RELEASE_MANIFEST": str(manifest)}
    cli = subprocess.run([str(artifacts.installed_sb), "identity"], env=env,
        cwd=fixture, capture_output=True, text=True, timeout=20, check=False)
    identity = TypeAdapter(IdentityReport).validate_json(cli.stdout)
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "life-memory-acceptance", "version": "1"}}}
    mcp = subprocess.run([str(artifacts.interpreter), "-m", "sb.mcp"],
        input=json.dumps(request) + "\n", env=env, cwd=fixture,
        capture_output=True, text=True, timeout=20, check=False)
    if mcp.returncode != 0:
        raise IdentityFailure("MCP_INITIALIZE_FAILED")
    response = TypeAdapter(McpInitialize).validate_json(mcp.stdout.splitlines()[0])
    # Retain the protocol response, omitting untrusted optional server metadata.
    server_info = response["result"]["serverInfo"]
    mcp_identity = TypeAdapter(McpIdentity).validate_json(server_info["description"])
    _ = (fixture / f"mcp-initialize-{scenario}.json").write_text(json.dumps({
        "jsonrpc": response["jsonrpc"], "id": response["id"],
        "result": {"protocolVersion": response["result"]["protocolVersion"],
                   "serverInfo": {"name": server_info["name"],
                                  "description": server_info["description"]}},
        "redacted_fields": "other server metadata omitted",
    }, indent=2) + "\n")
    for key in ("source_commit", "wheel_sha", "contract_profile_digest"):
        if identity[key] != mcp_identity[key]:
            raise IdentityFailure("MCP_ARTIFACT_IDENTITY_MISMATCH")
    if mcp_identity["process_entrypoint"] == identity["process_entrypoint"]:
        raise IdentityFailure("MCP_PROCESS_ENTRYPOINT_NOT_DISTINCT")
    if scenario == "failure":
        if cli.returncode == 0 or "CONTRACT_PROFILE_DIGEST_MISMATCH" not in identity["reasons"]:
            raise IdentityFailure("CONTRACT_PROFILE_DIGEST_MISMATCH missing from CLI")
    elif cli.returncode != 0 or identity["status"] != "ok":
        raise IdentityFailure(f"installed identity degraded: {identity['reasons']}")
    # The ready event is printed after the socket binds to port 0; no timing polls.
    script = ("from sb.web import build_server; "
              "server=build_server(host='127.0.0.1',port=0); "
              "print(server.server_address[1],flush=True); server.serve_forever()")
    process = subprocess.Popen([str(artifacts.interpreter), "-c", script], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=fixture)
    try:
        with selectors.DefaultSelector() as selector:
            if process.stdout is None:
                raise IdentityFailure("HTTP_READY_EVENT_MISSING")
            _ = selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=15):
                raise IdentityFailure("HTTP_READY_EVENT_MISSING")
            port = int(os.read(process.stdout.fileno(), 64).strip())
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request("GET", "/ready")
            response = connection.getresponse()
            ready_body = response.read()
            report = TypeAdapter(ReadyPayload).validate_json(ready_body)
            _ = (fixture / f"http-ready-{scenario}.json").write_text(
                json.dumps(report, indent=2) + "\n")
        finally:
            connection.close()
        observed = report["identity"]
        shared = ("source_commit", "wheel_sha", "installed_metadata", "contract_profile",
                  "contract_profile_digest", "configured_provider_identity", "active_generation")
        if any(identity[key] != observed[key] for key in shared):
            raise IdentityFailure("CLI_HTTP_IDENTITY_MISMATCH")
        if scenario == "failure":
            if report["status"] != "degraded" or "CONTRACT_PROFILE_DIGEST_MISMATCH" not in report["reasons"]:
                raise IdentityFailure("CONTRACT_PROFILE_DIGEST_MISMATCH missing from HTTP")
            raise IdentityFailure("CONTRACT_PROFILE_DIGEST_MISMATCH")
        if observed["status"] != "ok" or identity["process_entrypoint"] == observed["process_entrypoint"]:
            raise IdentityFailure("PROCESS_ENTRYPOINT_NOT_DISTINCT")
        return ["installed CLI, HTTP, and MCP share verified artifact identities",
                "process entrypoints stay distinct", "installed MCP protocol digest matches CLI and HTTP"]
    finally:
        process.terminate()
        try:
            _ = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ = process.kill()
            _ = process.wait(timeout=10)
        _ = (fixture / "server-pid.json").write_text(json.dumps({"pid": process.pid,
            "stopped": process.poll() is not None}) + "\n")
