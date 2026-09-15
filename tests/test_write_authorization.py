"""`sb_generation_status` answers whether the caller may write, without writing.

JARVIS must not perform a write to learn whether it is allowed to. Until the
provider said so on a read surface, its readiness report could only record
`write_unauthorized` - never distinguishing "this provider refuses my key" from
"nobody ever asked". `write_authorization` is that answer, derived from the same
`[jarvis_public_keys]` map and the same durable revocation store that
`sb_write_request` itself verifies against, so it cannot drift from the
decision it predicts.

It is additive and invisible to a provider with no JARVIS key surface, which is
what keeps the frozen schema-4 contract - and the digest JARVIS pins - byte
identical.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import ClassVar, Final

import anyio
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict
from pytest import MonkeyPatch

from sb.contracts import PageSpec, SourceCite
from sb.mcp import build_server
from sb.mcp_contract import JsonObject, JsonValue, build_contract
from sb.store.cas import ContentAddressedStore
from sb.vault import init_vault

CONTRACT: Final = Path("contracts/second-brain-mcp-v1.json")
# The schema-4 contract digest, pinned on both sides: `_TASK32_CONTRACT_DIGEST`
# here and `SECOND_BRAIN_FROZEN_DIGEST` / `PROFILES.schema4.digest` in JARVIS.
# This change must not move it.
TASK32_DIGEST: Final = "ae2e4b4f41ade29e8781e47e60dad6ddb17ed8cea516b82ccd16454acd5dc3e0"


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")
    structured_content: JsonObject | None = None
    is_error: bool = False


class _HashLedger:
    def last_compiled_hash(self, page_id: str) -> str | None:
        del page_id
        return None


def _mapping(value: JsonValue) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise AssertionError("expected JSON object")


def _public_key() -> str:
    raw = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _call(server: MCPServer, name: str, arguments: Mapping[str, JsonValue]) -> _Envelope:
    async def go() -> CallToolResult:
        async with Client(server, mode="legacy", cache=None) as client:
            return await client.call_tool(name, dict(arguments))

    return _Envelope.model_validate_json(anyio.run(go).model_dump_json())


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[Path]:
    """A seeded vault whose provider config this test rewrites per case."""
    base = tmp_path / "install"
    shutil.rmtree(base, ignore_errors=True)
    root = base / "vault"
    vault = init_vault(root)
    digest = ContentAddressedStore(root).put(b"ExampleAlpha")
    cite = SourceCite(digest[:8], "synthetic:ExampleAlpha", digest)
    _ = vault.write_pages(
        (
            PageSpec(
                "wiki/example-alpha", "ExampleAlpha",
                f"# Intro\nExampleAlpha.[^{digest[:8]}]", [cite], "active",
                derivation_key="compile:internal-example-alpha",
            ),
        ),
        "write-authorization", _HashLedger(),
    )
    monkeypatch.setenv("SB_CONFIG", str(base / "config.toml"))
    yield base


def _status(base: Path, body: str) -> JsonObject:
    state = base / "state"
    state.mkdir(parents=True, exist_ok=True)
    _ = (base / "config.toml").write_text(
        f'vault_root = "{base / "vault"}"\nstate_root = "{state}"\n{body}',
        encoding="utf-8",
    )
    server = build_server(base / "vault", task30=True, contract_schema=4)
    envelope = _call(server, "sb_generation_status", {})
    assert envelope.is_error is False
    assert envelope.structured_content is not None
    return envelope.structured_content


def test_keyless_provider_omits_the_field_and_keeps_the_frozen_contract(
    installation: Path,
) -> None:
    """A provider with no JARVIS key surface has nothing to report, and says nothing.

    This is the case the frozen schema-4 contract was exported from, so the
    digest JARVIS pins must be unaffected by this change.
    """
    status = _status(installation, "")
    assert "write_authorization" not in status
    fixture = _mapping(_mapping(_mapping(build_contract()["tools"])["sb_generation_status"])["happy"])
    assert set(status) == set(_mapping(fixture["raw_response"]))
    assert hashlib.sha256(CONTRACT.read_bytes()).hexdigest() == TASK32_DIGEST


def test_configured_and_unrevoked_key_is_authorized(installation: Path) -> None:
    status = _status(
        installation,
        f'jarvis_signing_key_id = "jarvis:test:alpha"\njarvis_public_key = "{_public_key()}"\n',
    )
    assert status["write_authorization"] == "authorized"


def test_revoked_key_is_unauthorized(installation: Path) -> None:
    status = _status(
        installation,
        f'jarvis_signing_key_id = "jarvis:test:alpha"\n'
        f'jarvis_public_key = "{_public_key()}"\n'
        f'revoked_jarvis_signing_key_ids = ["jarvis:test:alpha"]\n',
    )
    assert status["write_authorization"] == "unauthorized"


def test_caller_outside_the_authorized_map_is_unauthorized(installation: Path) -> None:
    """A key surface exists, but this provider does not name this caller's key."""
    status = _status(
        installation,
        f'[jarvis_public_keys]\n"jarvis:test:somebody-else" = "{_public_key()}"\n',
    )
    assert status["write_authorization"] == "unauthorized"


def test_unusable_key_material_disables_write_authorization(installation: Path) -> None:
    """Keys are declared but cannot be loaded, so no caller can be authorized."""
    status = _status(
        installation,
        'jarvis_signing_key_id = "jarvis:test:alpha"\njarvis_public_key = "not-a-key"\n',
    )
    assert status["write_authorization"] == "disabled"


def test_revocation_survives_removal_from_the_config(installation: Path) -> None:
    """The durable store, not the config, decides - as `sb_write_request` sees it."""
    revoked = _status(
        installation,
        f'jarvis_signing_key_id = "jarvis:test:alpha"\n'
        f'jarvis_public_key = "{_public_key()}"\n'
        f'revoked_jarvis_signing_key_ids = ["jarvis:test:alpha"]\n',
    )
    assert revoked["write_authorization"] == "unauthorized"
    restored = _status(
        installation,
        f'jarvis_signing_key_id = "jarvis:test:alpha"\njarvis_public_key = "{_public_key()}"\n',
    )
    assert restored["write_authorization"] == "unauthorized"
