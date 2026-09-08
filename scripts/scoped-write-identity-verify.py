"""Verify identity emitted by the compiled JARVIS acceptance helper."""

import hashlib
import json
import sys
from pathlib import Path

from sb.scoped_write_identity import scoped_write_identity

result = json.loads(Path(sys.argv[1]).read_text())
wire = result["scopedWriteIdentity"]
identity = scoped_write_identity(wire["identity"])
assert identity.identity_digest == wire["identity_digest"]
assert identity.idempotency_key == wire["idempotency_key"]
assert wire["writes_authorized"] is False
changed = scoped_write_identity({**wire["identity"], "projects": ["project:other"]})
assert changed.idempotency_key != identity.idempotency_key
assert result["execution_attempt_preserves_approval"] is True
assert result["scoped_write_completed"] is False
prepared = result["scopedWritePreparation"]
payload = prepared["payload"]
for field in ("subject", "content"):
    raw = json.dumps(payload[field], ensure_ascii=False, separators=(",", ":")).encode()
    expected = "sha256:" + hashlib.sha256(f"orca-jarvis/memory-{field}/v1\0".encode() + raw).hexdigest()
    assert payload[f"{field}_digest"] == expected
core = {key: value for key, value in prepared.items() if key != "preparation_digest"}
raw = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
assert prepared["preparation_digest"] == "sha256:" + hashlib.sha256(
    b"orca-jarvis/memory-scoped-write-preparation/v1\0" + raw).hexdigest()
assert prepared["binding"] == wire
assert result["replacement_payload_rejected"] is True
print(json.dumps({"cross_language_identity_equal": True, "cross_language_idempotency_equal": True,
                  "different_project_changes_identity": True, "writes_authorized": False,
                  "subject_content_preparation_digests_equal": True, "replacement_payload_rejected": True}))
