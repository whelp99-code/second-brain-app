"""Verify identity emitted by the compiled JARVIS acceptance helper."""

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
print(json.dumps({"cross_language_identity_equal": True, "cross_language_idempotency_equal": True,
                  "different_project_changes_identity": True, "writes_authorized": False}))
