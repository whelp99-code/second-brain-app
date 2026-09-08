"""Actual Node transport -> Python stdio MCP against an isolated provider journal."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization

from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_values import model_object
from tests.test_cancellation_result import intent_for, issue
from tests.test_correction_cancellation import CURRENT
from tests.test_correction_cancellation_executor import prepare
from tests.test_mcp_cancellation_profile import configure

if len(sys.argv) != 2:
    raise SystemExit("usage: python scripts/cancellation-mcp-acceptance.py ISOLATED_JARVIS_BUILD")
build = Path(sys.argv[1]).resolve()
work = Path(tempfile.mkdtemp(prefix="cancellation-mcp-acceptance-", dir="/var/tmp"))
executor, identity, _ = prepare(work)
config = work / "config.toml"
configure(executor, config)
assert "provider_private_key" not in config.read_text()
launcher = work / "second-brain-mcp"
launcher.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom sb.mcp import main\nmain()\n")
launcher.chmod(0o700)
intent = model_object(intent_for(executor, identity))
now = datetime.now(UTC)
seq, root = executor.store.tombstone_high_water()
fence = model_object(create_read_fence(provider_instance_id=executor.config.provider_instance_id,
    purpose="memory_status", operation="status", sequence=seq, set_root=root,
    issued_at=format_instant(now), not_before=format_instant(now),
    expires_at=format_instant(now + timedelta(minutes=5)), nonce="actual-cancellation-mcp",
    signing_key_id="reader", private_key=CURRENT))
public = executor.config.provider_signing_key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def run(state, expected=None):
    payload = {"build": str(build), "launcher": str(launcher), "config": str(config),
        "contract": str(ROOT / "contracts/second-brain-mcp-v4.json"), "intent": intent,
        "fence": fence, "key_id": executor.config.provider_signing_key_id, "public_key": public,
        "expected_state": state, "expected_result": expected}
    before = list(executor.store.db.iterdump())
    observed = subprocess.run(["node", str(ROOT / "scripts/cancellation-mcp-acceptance.mjs")],
        input=json.dumps(payload), text=True, capture_output=True, timeout=60, check=True)
    assert list(executor.store.db.iterdump()) == before
    return json.loads(observed.stdout)


try:
    pending = run("suppression_pending")
    result = issue(executor, identity)
    complete = run("provider_local_suppressed", result)
    report = {"parent_pid": os.getpid(), "pending": pending, "complete": complete,
        "private_key_in_mcp_config": False, "journal_rows_unchanged_by_queries": True,
        "result_digest": result["result_digest"], "contract_digest": (ROOT / "contracts/second-brain-mcp-v4.json.sha256").read_text().strip(),
        "scope": "actual JARVIS Node transport and semantic verifier -> Python stdio MCP; no cursor/operational rollout"}
    (work / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(work / "result.json")
    print(json.dumps(report))
finally:
    executor.close()
