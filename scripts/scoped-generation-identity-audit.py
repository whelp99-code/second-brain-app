"""Reproduce scope-different generations sharing an identity in isolated stores."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sb.generations import GenerationStore
from sb.remember_page import materialize_remember
from sb.source_access import SourceAccess


def main():
    temporary = Path(tempfile.mkdtemp(prefix="scoped-generation-identity-"))
    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    results = []
    try:
        for label in ("a", "b"):
            root = temporary / label
            store = GenerationStore(root / "state", root / "share", provider_instance_id="provider:fixture", provider_release_sha="a" * 40)
            try:
                def materialize(path):
                    materialize_remember(path, content="동일한 기억 내용", candidate_id="memcand:pos:v1:" + "a" * 64,
                        created_at=now.isoformat(), release_sha="a" * 40,
                        source_access=SourceAccess("principal:owner", (f"project:{label}",), "policy:fixture"))
                generation = store.build(request_id="fixture:scope-identity", parent=None,
                    tombstone_sequence=0, tombstone_set_root="sha256:" + "0" * 64,
                    created_at=now, allowed=lambda _: True, mutate=materialize)
                manifest = json.loads((generation.root / "generation.json").read_text())
                reads = {}
                for project in ("project:a", "project:b"):
                    reads[project] = json.loads(subprocess.check_output([sys.executable,
                        "scripts/scoped-remember-materialization-acceptance.py", "--read", str(generation.root), project],
                        text=True, timeout=30))
                results.append({"classification_project": f"project:{label}", "generation_id": generation.generation_id,
                    "ledger_manifest_digest": manifest["ledger_manifest_digest"], "reads": reads})
            finally:
                store.close()
        assert results[0]["reads"]["project:a"].get("records") == 1
        assert results[0]["reads"]["project:b"].get("denied") == "MEMORY_ACCESS_DENIED"
        assert results[1]["reads"]["project:b"].get("records") == 1
        assert results[1]["reads"]["project:a"].get("denied") == "MEMORY_ACCESS_DENIED"
        print(json.dumps({"fixture": True, "independent_read_processes": 4,
            "different_access_same_generation": results[0]["generation_id"] == results[1]["generation_id"],
            "generations": results}, ensure_ascii=False, indent=2))
    finally:
        for directory, dirs, files in os.walk(temporary):
            Path(directory).chmod(0o700)
            for name in dirs + files:
                path = Path(directory) / name
                if not path.is_symlink():
                    path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
