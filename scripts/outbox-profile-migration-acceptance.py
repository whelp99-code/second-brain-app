"""Upgrade a real queued legacy outbox fixture without touching operational DBs."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    build = Path(sys.argv[1]).resolve()
    jarvis = Path(sys.argv[2]).resolve()
    state = None
    with tempfile.TemporaryDirectory(prefix="outbox-profile-migration-") as directory:
        snapshot = Path(directory)
        for name in ("src", "tests"):
            shutil.copytree(build / name, snapshot / name)
        (snapshot / "package.json").write_text('{"type":"module"}')
        (snapshot / "node_modules").symlink_to(jarvis / "node_modules", target_is_directory=True)
        migrations = snapshot / "migrations"
        migrations.mkdir()
        for path in (jarvis / "migrations").glob("*.sql"):
            if path.name < "077_":
                shutil.copy2(path, migrations / path.name)
        create = '''
const {outboxFixture,claimAction}=await import(process.argv[1]+'/tests/fixtures/memory-outbox-fixture.js');
const f=await outboxFixture();f.service.enqueue(claimAction(f));
const row=f.database.authority.db.prepare('SELECT * FROM memory_outbox').get();
const counts=f.database.authority.db.prepare('SELECT count(*) AS n FROM schema_migrations').get();
console.log(JSON.stringify({root:f.database.root,anchorsRoot:f.database.anchorsRoot,path:f.database.path,row,counts}));
f.database.authority.close();
'''
        try:
            state = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", create, str(snapshot)],
                cwd=jarvis, text=True, timeout=60))
            assert "request_profile" not in state["row"]
            shutil.copy2(jarvis / "migrations/077_memory_outbox_request_profile.sql", migrations)
            migrate = '''
import {readFileSync} from 'node:fs';
const state=JSON.parse(readFileSync(0,'utf8'));
const {AuthorityDb}=await import(process.argv[1]+'/src/db.js');
const db=new AuthorityDb(state.path,process.argv[1]+'/migrations');
try{await db.migrate();const row=db.db.prepare('SELECT * FROM memory_outbox').get();
console.log(JSON.stringify({row,counts:db.db.prepare('SELECT count(*) AS n FROM schema_migrations').get(),
fk:db.db.prepare('PRAGMA foreign_key_check').all(),integrity:db.db.prepare('PRAGMA quick_check').get()}));}
finally{db.close();}
'''
            after = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", migrate, str(snapshot)],
                cwd=jarvis, text=True, input=json.dumps(state), timeout=60))
            assert after["row"] == {**state["row"], "request_profile": "legacy"}
            assert after["counts"]["n"] == state["counts"]["n"] + 1
            assert after["fk"] == [] and after["integrity"] == {"quick_check": "ok"}
            print(json.dumps({"fixture_database": True, "processes": 2, "queued_rows_preserved": 1,
                "original_columns_unchanged": True, "request_profile": "legacy",
                "migration_count_before": state["counts"]["n"], "migration_count_after": after["counts"]["n"],
                "foreign_key_errors": 0, "quick_check": "ok"}, indent=2))
        finally:
            if state is not None:
                shutil.rmtree(state["root"])
                shutil.rmtree(state["anchorsRoot"])


if __name__ == "__main__":
    main()
