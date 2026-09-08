"""Opt-in native MCP/CLI correction, deletion, and restore of sealed semantic records."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import StdioServerParameters
from mcp.client import Client
from pydantic import TypeAdapter
from pytest import MonkeyPatch

from sb.config import load_config
from sb.delegations import create_read_fence
from sb.effect_values import JsonObject, JsonValue, format_instant, is_json_object
from sb.effect_write_requests import accept_effect_request
from sb.effect_write_values import model_object
from sb.ops import restore_backup
from sb.pipeline import audit_citations
from sb.runtime_backup import backup_runtime
from sb.search import SearchIndex
from tests.task30_effect_factory import effect_request
from tests.test_mcp_sealed_vectors import runtime_fixture

BOOTSTRAP = """import os,sys
if os.environ.get('SB_ACCEPTANCE_REAL_EMBEDDING') != '1':
    from sb import embeddings
    from tests.test_sealed_vectors import SemanticEncoder
    embeddings.resolve_encoder=SemanticEncoder
mode=sys.argv.pop(1)
if mode=='mcp':
    from sb.mcp import main
else:
    from sb.cli import main
raise SystemExit(main())
"""


def product_hash(repository: Path) -> str:
    return hashlib.sha256(b"".join(str(p.relative_to(repository)).encode() + b"\0" + p.read_bytes() + b"\0"
                                  for p in sorted((repository / "sb").rglob("*.py")))).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--real-model", action="store_true")
    real_model = cast(bool, parser.parse_args().real_model)
    base = Path(tempfile.mkdtemp(prefix="sb-sealed-vector-"))
    repository = Path(__file__).resolve().parents[1]
    source_hash = product_hash(repository)
    print(f"Evidence directory: {base}", flush=True)
    report: dict[str, object] = {"state": "running", "workspace": str(base), "source_tree_sha256": source_hash}
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    def b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    with MonkeyPatch.context() as patch:
        _, service, initial = runtime_fixture(base, patch, real_encoder=real_model)
        config_path = base / "config.toml"
        keys = {"provider_signing_key_id": "provider:key", "provider_private_key": b64(key.private_bytes_raw()),
                "jarvis_signing_key_id": "jarvis:fixture", "jarvis_public_key": b64(key.public_key().public_bytes_raw())}
        _ = config_path.write_text("\n".join(name + " = " + json.dumps(value) for name, value in keys.items())
                                   + "\n" + config_path.read_text())
        config = load_config(config_path)
        env = dict(os.environ, SB_CONFIG=str(config_path), PYTHONPATH=str(repository), TMPDIR=str(base),
                   SB_MCP_CONTRACT_PROFILE="remember-schema5", SB_ACCEPTANCE_REAL_EMBEDDING="1" if real_model else "0")
        params = StdioServerParameters(command=sys.executable, args=["-c", BOOTSTRAP, "mcp"], env=env)
        commands: list[dict[str, object]] = []

        def cli(label: str, *args: str) -> None:
            done = subprocess.run([sys.executable, "-c", BOOTSTRAP, "cli", *args],
                                  env=env, capture_output=True, text=True, check=False, timeout=120)
            _ = (base / f"{label}.stdout").write_text(done.stdout)
            _ = (base / f"{label}.stderr").write_text(done.stderr)
            assert done.returncode == 0, done.stderr + done.stdout
            commands.append({"label": label, "exit": done.returncode, "result": json.loads(done.stdout)})
            if args == ("apply-requests", "--once"):
                assert json.loads(done.stdout)["state"] == "proved", done.stdout

        def apply(operation: Literal["correct", "forget"], text: str, lane: str) -> None:
            now = datetime.now(UTC)
            request = effect_request(service.store.active(), operation, text, now,
                                    service.requests.tombstone_high_water(), key, lane,
                                    correction_content="다음 만남은 수요일")
            _ = accept_effect_request(Path(config.request_root), request, now,
                                      public_keys={"jarvis:fixture": key.public_key()},
                                      provider_instance_id=config.provider_instance_id)
            cli(operation, "apply-requests", "--once")

        async def observe(client: Client, label: str) -> JsonObject:
            sequence, root = service.requests.tombstone_high_water()
            now = datetime.now(UTC)
            fence = create_read_fence(provider_instance_id=config.provider_instance_id, purpose="memory_read",
                operation="read", sequence=sequence, set_root=root, issued_at=format_instant(now),
                not_before=format_instant(now), expires_at=format_instant(now + timedelta(minutes=2)),
                nonce=label, signing_key_id="jarvis:fixture", private_key=key)
            result = await client.call_tool("sb_search", {"query": "일정", "limit": 10,
                                                         "read_fence": model_object(fence)})
            value = TypeAdapter[JsonValue](JsonValue).validate_python(cast(object, result.structured_content))
            assert not result.is_error and is_json_object(value), result
            _ = (base / f"{label}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            return value

        async def exercise() -> None:
            async with Client(params, mode="legacy", cache=None) as first, Client(params, mode="legacy", cache=None) as second:
                before = await observe(first, "agent-a-initial")
                assert before == await observe(second, "agent-b-initial")
                assert "회의는 월요일" in json.dumps(before, ensure_ascii=False)
                assert before["generation_id"] == initial.generation_id
                apply("correct", "회의는 월요일", "1")
                corrected = await observe(second, "agent-b-corrected")
                assert "회의는 월요일" not in json.dumps(corrected, ensure_ascii=False)
                assert "다음 만남은 수요일" in json.dumps(corrected, ensure_ascii=False)
                assert audit_citations(service.store.active().root) == ()
                archive = base / "corrected.tar.gz"
                _ = backup_runtime(config, archive)
                restored = base / "restored-corrected"
                _ = restore_backup(archive, restored)
                recalled = SearchIndex(restored, hybrid=True, registry_path=Path(config.knowledge_registry)).search(
                    "일정", 1, scope="reference")
                assert recalled and recalled[0].snippet == "다음 만남은 수요일"
                apply("forget", "다음 만남은 수요일", "2")
                deleted = await observe(first, "agent-a-deleted")
                assert "회의는 월요일" not in json.dumps(deleted, ensure_ascii=False)
                assert "다음 만남은 수요일" not in json.dumps(deleted, ensure_ascii=False)
                assert "비용은 만원" in json.dumps(deleted, ensure_ascii=False)
                assert audit_citations(service.store.active().root) == ()
                _ = backup_runtime(config, base / "deleted.tar.gz")
                _ = restore_backup(base / "deleted.tar.gz", base / "restored-deleted")
                remaining = SearchIndex(base / "restored-deleted", hybrid=True,
                                        registry_path=Path(config.knowledge_registry)).search("일정", 10, scope="reference")
                assert [hit.snippet for hit in remaining] == ["비용은 만원"]
                report.update({"initial": before, "corrected": corrected, "deleted": deleted,
                               "corrected_restore": True, "deleted_restore": True})
        try:
            anyio.run(exercise)
            cli("cli-search", "search", "일정", "--json", "--scope", "reference")
            assert product_hash(repository) == source_hash
            report.update({"state": "passed", "commands": commands, "real_model": real_model,
                           "limitations": ["real model lifecycle fixture; not full Korean quality" if real_model
                                            else "deterministic encoder; not Korean model quality",
                                           "two native MCP processes; queries observe stable mutation boundaries",
                                           "isolated fixture; no operational activation"]})
        except BaseException:
            report.update({"state": "failed", "commands": commands})
            raise
        finally:
            service.close()
            _ = (base / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
