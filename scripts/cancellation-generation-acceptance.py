"""Actual process exit/restart and stdio MCP reads of an isolated cancellation generation.

Run with PYTHONPATH=. TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-generation-acceptance.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp

import anyio
from mcp import StdioServerParameters
from mcp.client import Client

from sb.delegations import create_read_fence
from sb.effect_values import format_instant
from sb.effect_write_values import model_object
from tests.test_correction_cancellation import HISTORICAL
from tests.test_correction_cancellation_executor import OLD, REPLACEMENT, prepare


def main() -> None:
    os.umask(0o077)
    root = Path(mkdtemp(prefix="cancellation-generation-", dir="/var/tmp"))
    repository = Path(__file__).resolve().parents[1]
    executor, intent_id, _original = prepare(root)
    config = executor.config
    base = executor.generations.active()
    sequence, set_root = executor.store.tombstone_high_water()
    executor.close()
    config_path = root / "config.toml"
    lines = [f'{name} = "{value}"' for name, value in {
        "vault_root": config.share_root / "vault", "request_root": config.request_root,
        "state_root": config.state_root, "share_root": config.share_root, "export_root": config.export_root,
        "backup_root": config.backup_root, "provider_instance_id": config.provider_instance_id,
        "provider_release_sha": config.provider_release_sha, "jarvis_signing_key_id": "jarvis:fixture",
        "jarvis_public_key": base64.urlsafe_b64encode(HISTORICAL.public_key().public_bytes_raw()).rstrip(b"=").decode(),
    }.items()]
    config_path.write_text("\n".join(lines) + "\n")
    env = {**os.environ, "TMPDIR": "/var/tmp", "PYTHONPATH": str(repository), "SB_CONFIG": str(config_path),
        "SB_MCP_CONTRACT_PROFILE": "remember-schema5"}
    observations = []

    def fence(status=False):
        now = datetime.now(UTC)
        return model_object(create_read_fence(provider_instance_id=config.provider_instance_id,
            purpose="memory_status" if status else "memory_read", operation="status" if status else "read",
            sequence=sequence, set_root=set_root, issued_at=format_instant(now), not_before=format_instant(now),
            expires_at=format_instant(now + timedelta(minutes=1)), nonce="cancellation-generation-read",
            signing_key_id="jarvis:fixture", private_key=HISTORICAL))

    async def observe(stage):
        pid_path = root / f"{stage}-mcp.pid"
        bootstrap = "import os;from pathlib import Path;Path(os.environ['SB_TEST_PID']).write_text(str(os.getpid()));from sb.mcp import main;main()"
        parameters = StdioServerParameters(command=sys.executable, args=["-c", bootstrap], cwd=repository,
            env={**env, "SB_TEST_PID": str(pid_path)})
        async with Client(parameters, mode="legacy", cache=None, read_timeout_seconds=60) as client:
            status = await client.call_tool("sb_generation_status", {"read_fence": fence(True)})
            assert not status.is_error
            assert status.structured_content is not None
            results = []
            for query in (OLD, REPLACEMENT):
                value = await client.call_tool("sb_search", {"query": query, "read_fence": fence()})
                if stage == "before":
                    assert value.is_error and "TOMBSTONE_SET_STALE" in value.model_dump_json()
                else:
                    assert not value.is_error and value.structured_content is not None
                    assert value.structured_content["results"] == []
                results.append(json.loads(value.model_dump_json()))
            expected = "tombstone_stale" if stage == "before" else "healthy"
            assert status.structured_content["pointer_health"] == expected
            observations.append({"stage": stage, "pid": int(pid_path.read_text()),
                "status": json.loads(status.model_dump_json()), "search": results})

    anyio.run(observe, "before")
    worker = """
import json,os,sys
from pathlib import Path
from sb.request_executor import RequestExecutor
from tests.test_request_executor import _config
from tests.test_correction_cancellation_executor import execute
root=Path(sys.argv[1]); intent_id=sys.argv[2]; interrupt=sys.argv[3]=='crash'
executor=RequestExecutor(_config(root))
def barrier(phase):
 if interrupt and phase=='pointer_rename': os._exit(77)
try:
 result=execute(executor,intent_id,barrier)
 print(json.dumps(dict(pid=os.getpid(),result=result)))
finally:executor.close()
"""
    crash = subprocess.run([sys.executable, "-c", worker, str(root), intent_id, "crash"],
        cwd=repository, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert crash.returncode == 77, crash.stderr
    recovered = subprocess.run([sys.executable, "-c", worker, str(root), intent_id, "recover"],
        cwd=repository, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout)
    assert result["result"]["state"] == "generation_active"
    assert not base.root.exists()
    anyio.run(observe, "after")
    evidence = {"root": str(root), "intent_id": intent_id, "parent_pid": os.getpid(),
        "crash_exit_code": crash.returncode, "recovery": result, "mcp": observations,
        "original_generation_removed": True, "operational_mutations": 0, "signed_completion_receipt": False,
        "jarvis_cursor_settlement": False, "backup_export_native_erasure": False}
    (root / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"root": str(root), "crash_exit_code": crash.returncode, "recovery": result,
        "mcp_before": "tombstone_stale", "mcp_after": "healthy", "old_and_replacement_search_results": 0}))


if __name__ == "__main__":
    main()
