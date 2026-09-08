"""Node fixture signatures -> Python verifier -> actual sealed CLI page scope."""
import json
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sb.access_claims import (
    AccessClaimRejected,
    AccessContext,
    access_request_digest,
    require_claimed_page,
)
from sb.delegations import create_read_fence
from sb.effect_write_values import model_object

setup = runpy.run_path(str(Path(__file__).with_name("memory-access-acceptance.py")))
page, work = setup["page"], setup["work"]
now = datetime(2026, 9, 9, tzinfo=UTC)
key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
fence = create_read_fence(provider_instance_id=page.generation.provider_instance_id,
    purpose="memory_read", operation="read", sequence=page.tombstone_sequence, set_root=page.tombstone_set_root,
    issued_at="2026-09-09T00:00:00.000Z", not_before="2026-09-09T00:00:00.000Z",
    expires_at="2026-09-09T00:01:00.000Z", nonce="nonce:fence", signing_key_id="key:test", private_key=key)
request = access_request_digest("sb_read_page", {"id": page.page_id})
body = {"schema_version": 1, "provider_instance_id": page.generation.provider_instance_id,
    "principal_id": "principal:owner", "agent_id": "agent:test", "session_id": "session:test",
    "projects": ["project:alpha"], "policy_revision": "policy:1", "purpose": "memory_read",
    "request_digest": request, "read_fence_digest": fence.fence_digest,
    "issued_at": "2026-09-09T00:00:00.000Z", "expires_at": "2026-09-09T00:00:30.000Z",
    "nonce": "nonce:claim", "signing_key_id": "key:test"}
if len(sys.argv) > 1:
    child = subprocess.run(["node", str(Path(__file__).with_name("access-claim-production-sign.mjs")), sys.argv[1]],
        input=json.dumps({**body, "page_id": page.page_id}), capture_output=True, text=True, check=True, timeout=60)
    bundle = json.loads(child.stdout)
    claim, fence_value = bundle["access_claim"], bundle["read_fence"]
else:
    child = subprocess.run(["node", str(Path(__file__).with_name("access-claim-sign.mjs"))],
        input=json.dumps(body), capture_output=True, text=True, check=True, timeout=30)
    claim, fence_value = json.loads(child.stdout), model_object(fence)
context = AccessContext(page.generation.provider_instance_id, "principal:owner", "agent:test", "session:test",
    "policy:1", "memory_read", request, page.tombstone_sequence, page.tombstone_set_root)
require_claimed_page(page, claim, fence_value, {"key:test": key.public_key()}, context, now)
try:
    require_claimed_page(page, {**claim, "projects": ["project:beta"]}, fence_value,
        {"key:test": key.public_key()}, context, now)
except AccessClaimRejected:
    pass
else:
    raise AssertionError("unsigned scope change accepted")
report = {"work": str(work), "provider": page.generation.provider_instance_id, "page": page.page_id,
    "node_signature_accepted": True, "production_issuer": len(sys.argv) > 1, "tampered_scope_rejected": True,
    "records": len(page.records), "source_requirements": len(page.source_refs),
    "scope": "Node signature and Python verification over isolated CLI data; production_issuer indicates actual issuer code with fixture scope resolver/authority DB, not operational authorization or MCP authentication"}
output = work / "access-claim-result.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(output)
print(json.dumps(report))
