"""Actual CLI source classification persistence in isolated sealed generations."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="source-access-acceptance-", dir="/var/tmp"))
source = work / "source"
source.mkdir()
(source / "notes.md").write_text("---\nowner: principal:other\nproject: project:beta\n---\nAlpha fixture memory\n")
config = work / "config.toml"
base = f'''vault_root = "{work / 'share' / 'vault'}"
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

def ingest():
    return subprocess.run([sys.executable, "-m", "sb.cli", "ingest", "--source", "docs"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def rows():
    path = (work / "share" / "vault").resolve() / ".sb" / "ledger.db"
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        assert db.execute("SELECT count(*) FROM source_item").fetchone()[0] == 1
        return db.execute("SELECT source_ref_digest,classification_json,classification_digest FROM source_access").fetchall()
    finally:
        db.close()

first = ingest()
assert first.returncode == 0, first.stderr + first.stdout
bound = rows()
assert len(bound) == 1
assert json.loads(bound[0][1]) == {"schema_version": 1, "owner":"principal:owner", "projects":["project:alpha"], "policy_revision":"policy:1"}
second = ingest()
assert second.returncode == 0, second.stderr + second.stdout
assert rows() == bound
config.write_text(base.replace('project:alpha', 'project:beta').replace('policy:1', 'policy:2'))
denied = ingest()
assert denied.returncode != 0
assert "SOURCE_ACCESS_RECLASSIFICATION_REQUIRED" in denied.stdout + denied.stderr
assert rows() == bound
report = {"work":str(work),"first_exit":first.returncode,"repeat_exit":second.returncode,
    "reclassification_exit":denied.returncode,"source_count":1,"classification_count":1,
    "source_ref_digest":bound[0][0],"classification_digest":bound[0][2],
    "classification_preserved_through_sealed_generations":True,"frontmatter_not_used_as_authority":True,
    "scope":"trusted source classification persistence only; no scoped MCP access grant or enforcement"}
(work / "result.json").write_text(json.dumps(report,indent=2)+'\n')
print(work / "result.json")
print(json.dumps(report))
