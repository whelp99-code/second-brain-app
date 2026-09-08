"""Local staging/sealing/read acceptance; no MCP write or policy grant.

Run from SB root: PYTHONPATH=. uv run python scripts/...py <JARVIS preparation JSON>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sb.generations import GenerationStore
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.remember_page import materialize_remember
from sb.scoped_write_preparation import decode_scoped_write_preparation
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1


def read(root: Path, project: str) -> dict:
    manifest = json.loads((root / "generation.json").read_text())
    identity = GenerationIdentityV1(*(str(manifest[name]) for name in (
        "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
    name = next((root / "wiki").glob("*.md")).stem
    page = classified_page(root, name, identity)
    try:
        require_scope(page, SourceAccess("principal:owner", (project,), "policy:fixture"))
    except MemoryAccessError as error:
        return {"denied": str(error)}
    return {"records": len(page.records), "source_refs": list(page.source_refs),
            "page_digest": page.content_digest}


def main() -> None:
    if sys.argv[1] == "--read":
        print(json.dumps(read(Path(sys.argv[2]), sys.argv[3])))
        return
    raw = json.loads(Path(sys.argv[1]).read_text())
    value = raw.get("preparation", raw)
    now = datetime.fromisoformat(value["binding"]["expires_at"]).astimezone(UTC) - timedelta(milliseconds=1)
    prepared = decode_scoped_write_preparation(value, now=now)
    temporary = Path(tempfile.mkdtemp(prefix="scoped-materialization-"))
    store = GenerationStore(temporary / "state", temporary / "share",
        provider_instance_id="provider:fixture", provider_release_sha="a" * 40)
    try:
        def apply(root: Path) -> None:
            materialize_remember(root, content=prepared.content,
                candidate_id=json.loads(prepared.identity.canonical)["candidate_id"],
                created_at=now.isoformat(), release_sha="a" * 40,
                sensitivity=prepared.sensitivity, source_access=prepared.source_access)
        generation = store.build(request_id="fixture:scoped-materialization", parent=None,
            tombstone_sequence=0, tombstone_set_root="sha256:" + "0" * 64,
            created_at=now, allowed=lambda _path: True, mutate=apply)
        store.activate(generation, None, now)
        result = []
        for project in ("project:shared-memory", "project:shared-memory", "project:other"):
            output = subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
                "--read", str(generation.root), project], text=True)
            result.append(json.loads(output))
        assert result[0] == result[1] and result[0]["records"] == 4
        assert result[2] == {"denied": "MEMORY_ACCESS_DENIED"}
        print(json.dumps({"fixture": True, "independent_read_processes": 3,
            "read_results": result, "source_bytes": len(prepared.content.encode()),
            "mcp_write_completed": False}, indent=2))
    finally:
        store.close()
        # Only this script's fresh temporary generation tree is made removable.
        for root, dirs, files in os.walk(temporary):
            os.chmod(root, 0o700)
            for name in dirs:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o700)
            for name in files:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o600)
        shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
