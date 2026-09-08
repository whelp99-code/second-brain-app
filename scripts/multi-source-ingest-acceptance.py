"""Actual CLI multi-root selection, resume, targeted update and duplicate rejection."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="multi-source-ingest-", dir="/var/tmp"))
config = work / "config.toml"
base = f'vault_root = "{work}/share/vault"\nshare_root = "{work}/share"\nstate_root = "{work}/state"\n'
for name in ("a", "b", "c"):
    folder = work / name
    folder.mkdir()
    (folder / "note.md").write_text(f"Memory {name} initial.")
    base += f'[[sources]]\nid = "{name}"\nadapter = "markdown-vault"\nroot = "{folder}"\n'
    base += f'[source_access.{name}]\nowner = "principal:owner"\nprojects = ["project:{name}"]\npolicy_revision = "1"\n'
config.write_text(base)

def ingest(source):
    return subprocess.run([sys.executable, "-m", "sb.cli", "ingest", "--source", source],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, "SB_CONFIG": str(config), "TMPDIR": "/var/tmp"},
        text=True, capture_output=True, check=False, timeout=60)


def snapshot():
    root = (work / "share" / "vault").resolve()
    db = sqlite3.connect((root / ".sb" / "ledger.db").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return {"sources": db.execute("SELECT source_id,source_uri,content_hash FROM source_item ORDER BY source_id,content_hash").fetchall(),
            "cursors": dict(db.execute("SELECT source_id,position FROM cursor").fetchall()),
            "classifications": db.execute("SELECT count(*) FROM source_access").fetchone()[0]}
    finally:
        db.close()

first = ingest("markdown-vault")
assert first.returncode == 0, first.stdout + first.stderr
before = snapshot()
assert {row[0] for row in before["sources"]} == {"a", "b", "c"}
assert before["classifications"] == 3 and set(before["cursors"]) == {"a", "b", "c"}
assert ingest("markdown-vault").returncode == 0
assert snapshot() == before
(work / "b" / "note.md").write_text("Memory b revised.")
assert ingest("b").returncode == 0
after = snapshot()
assert len(after["sources"]) == 4 and after["classifications"] == 4
assert after["cursors"]["a"] == before["cursors"]["a"]
assert after["cursors"]["c"] == before["cursors"]["c"]
assert after["cursors"]["b"] != before["cursors"]["b"]
unknown = ingest("missing-source")
assert unknown.returncode != 0 and "SOURCE_NOT_FOUND: missing-source" in unknown.stdout + unknown.stderr
assert snapshot() == after
config.write_text(base + f'[[sources]]\nid = "a"\nadapter = "markdown-vault"\nroot = "{work}/c"\n')
denied = ingest("markdown-vault")
assert denied.returncode != 0 and "SOURCE_ID_DUPLICATE" in denied.stdout + denied.stderr
assert snapshot() == after
report = {"work": str(work), "initial_sources": 3, "initial_classifications": 3, "repeat_equal": True,
    "targeted_update_source_versions": 4, "other_cursors_unchanged": True, "duplicate_id_denied": True,
    "unknown_source_denied_without_partial_ingest": True,
    "scope": "actual isolated CLI sealed ingest; no operational sources or new connector types"}
(work / "result.json").write_text(json.dumps(report, indent=2) + "\n")
print(work / "result.json")
print(json.dumps(report))
