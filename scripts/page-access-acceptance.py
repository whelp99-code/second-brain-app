"""Actual CLI page provenance across sealed generations; fake LLM content."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from sb.page_metadata import frontmatter_values

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="page-access-acceptance-", dir="/var/tmp"))
source = work / "source"
source.mkdir()
(source / "notes.md").write_text("---\nowner: principal:other\nproject: project:beta\n---\nAlpha fixture memory\n")
config = work / "config.toml"
base = f'''knowledge_registry = "{work / 'registry.sqlite'}"
vault_root = "{work / 'share' / 'vault'}"
share_root = "{work / 'share'}"
state_root = "{work / 'state'}"
request_root = "{work / 'requests'}"
backup_root = "{work / 'backups'}"
export_root = "{work / 'exports'}"
[[sources]]
id = "docs"
adapter = "markdown-vault"
root = "{source}"
[source_access.docs]
owner = "principal:owner"
projects = ["project:alpha"]
policy_revision = "policy:1"
'''
config.write_text(base)
env = {**os.environ, "TMPDIR": "/var/tmp", "SB_CONFIG": str(config)}
# The downstream signed-claim acceptance clock is fixed at this instant. A real
# wall-clock page date eventually makes these records future-dated for that reader.
COMPILE_BOOTSTRAP = '''from datetime import datetime, UTC
import sb.vault as vault
from sb.cli import main
class Clock(datetime):
 @classmethod
 def now(cls, tz=None): return datetime(2026, 9, 9, tzinfo=UTC)
vault.datetime = Clock
raise SystemExit(main())
'''

def ingest():
    return subprocess.run([sys.executable, "-m", "sb.cli", "ingest", "--source", "docs"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False)


def compile_pages():
    result = subprocess.run([sys.executable, "-c", COMPILE_BOOTSTRAP, "compile", "--llm", "fake"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def page_binding():
    vault = work / "share" / "vault"
    names = subprocess.check_output(["git", "-C", str(vault), "ls-tree", "-r", "--name-only", "HEAD", "wiki"], text=True).splitlines()
    assert len(names) == 1, names
    raw = subprocess.check_output(["git", "-C", str(vault), "show", "HEAD:" + names[0]])
    assert frontmatter_values(raw.decode())["updated"] == "2026-09-09"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    db = sqlite3.connect((vault.resolve() / ".sb" / "ledger.db").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        row = db.execute("SELECT requirements_json FROM page_access WHERE page_id=? AND content_digest=?",
            (names[0].removesuffix(".md"), digest)).fetchone()
        assert row is not None
        return digest, json.loads(row[0])
    finally:
        db.close()


first = ingest()
assert first.returncode == 0, first.stdout + first.stderr
compile_pages()
digest1, binding1 = page_binding()
assert binding1["complete"] and len(binding1["source_refs"]) == 1
(source / "notes.md").write_text("Updated Alpha fixture memory with additional detail.\n")
second = ingest()
assert second.returncode == 0, second.stdout + second.stderr
compile_pages()
digest2, binding2 = page_binding()
assert digest1 != digest2
assert binding2["complete"] and len(binding2["source_refs"]) == 2
assert set(binding1["source_refs"]) <= set(binding2["source_refs"])
compile_pages()
assert page_binding() == (digest2, binding2)
report = {"work": str(work), "first_content_digest": digest1, "updated_content_digest": digest2,
    "page_clock": "2026-09-09T00:00:00.000Z",
    "first_source_count": 1, "updated_source_count": 2, "parent_requirements_retained": True,
    "repeat_preserved": True, "committed_bytes_bound": True,
    "scope": "actual isolated CLI ingest/compile/sealed generations with fake LLM; no scoped MCP enforcement"}
(work / "result.json").write_text(json.dumps(report, indent=2) + "\n")
print(work / "result.json")
print(json.dumps(report))
