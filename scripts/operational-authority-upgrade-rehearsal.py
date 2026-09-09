"""Rehearse JARVIS migrations on a private online backup; never migrate the source.

Outputs counts and preservation verdicts only, not operational row contents.
Temporary database copies are removed on success and failure.
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path


def readonly(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only=ON")
    return connection


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def inventory(path, prior=None):
    result = {}
    with closing(readonly(path)) as connection:
        connection.execute("BEGIN")
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        for table in (tables if prior is None else prior):
            if table not in tables:
                result[table] = {"missing": True}
                continue
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})")]
            selected = columns if prior is None else prior[table]["columns"]
            if not set(selected).issubset(columns):
                result[table] = {"missing_columns": True}
                continue
            digests = []
            for row in connection.execute(f"SELECT {','.join(map(quote, selected))} FROM {quote(table)}"):
                encoded = json.dumps(list(row), ensure_ascii=True, separators=(",", ":"),
                                     default=lambda blob: {"blob_hex": blob.hex()}).encode()
                digests.append(hashlib.sha256(encoded).digest())
            result[table] = {"columns": selected, "rows": len(digests),
                             "digest": hashlib.sha256(b"".join(sorted(digests))).hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, type=Path)
    parser.add_argument("--jarvis-build", required=True, type=Path)
    parser.add_argument("--migrations", required=True, type=Path)
    parser.add_argument("--previous-build", type=Path, help="Readiness-only check using the prior installed build")
    parser.add_argument("--previous-migrations", type=Path)
    args = parser.parse_args()
    source = args.source_db.resolve(strict=True)
    build = args.jarvis_build.resolve(strict=True)
    migrations = args.migrations.resolve(strict=True)
    if not source.is_file() or not (build / "src/db.js").is_file():
        raise ValueError("source database and isolated build required")
    with tempfile.TemporaryDirectory(prefix="authority-upgrade-rehearsal-") as directory:
        target = Path(directory) / "authority.sqlite"
        # The destination cannot alias the operational source: it is newly allocated
        # under a private TemporaryDirectory. Source is opened read-only by SQLite.
        deadline = time.monotonic() + 60

        def progress(_status, _remaining, _total):
            if time.monotonic() > deadline:
                raise TimeoutError("online backup deadline exceeded")

        with closing(readonly(source)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=256, progress=progress)
        target.chmod(0o600)
        before = inventory(target)
        with closing(readonly(target)) as connection:
            old_journal = connection.execute("SELECT id,checksum,applied_at FROM schema_migrations ORDER BY id").fetchall()
            old_vector = [row[0] for row in old_journal]
            initial_fk = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        program = """
import {pathToFileURL} from 'node:url';
const {AuthorityDb}=await import(pathToFileURL(process.argv[1]+'/src/db.js').href);
const db=new AuthorityDb(process.argv[2],process.argv[3],{fileMustExist:true});
try {
  await db.migrate(); await db.assertMigrationsReady();
  const first=db.db.prepare('SELECT total_changes() AS n').get().n;
  await db.migrate(); await db.assertMigrationsReady();
  const replay=db.db.prepare('SELECT total_changes() AS n').get().n-first;
  console.log(JSON.stringify({ok:true,replay_changes:replay,
    vector:db.db.prepare('SELECT id FROM schema_migrations ORDER BY id').all().map(row=>row.id),
    foreign_key_errors:db.db.prepare('PRAGMA foreign_key_check').all().length,
    integrity:db.db.prepare('PRAGMA integrity_check').all().map(row=>row.integrity_check)}));
} catch(error) {
  console.log(JSON.stringify({ok:false,error_code:typeof error.code==='string'?error.code:'UNCLASSIFIED_MIGRATION_ERROR'}));
} finally {db.close();}
"""
        child = subprocess.run(["node", "--input-type=module", "-e", program,
                                str(build), str(target), str(migrations)],
                               capture_output=True, text=True, timeout=60)
        if child.returncode != 0:
            raise RuntimeError("migration child failed; private diagnostics withheld")
        upgrade = json.loads(child.stdout)
        if not upgrade["ok"]:
            current_files = {path.name for path in migrations.glob("*.sql")}
            preserved = inventory(target) == before
            print(json.dumps({"source_open_mode": "read_only", "upgrade": upgrade,
                              "unrecognized_original_migrations": [name for name in old_vector if name not in current_files],
                              "migration_count_before": len(old_vector), "copy_rows_unchanged_on_rejection": preserved,
                              "operational_activation": False}))
            return 1
        after = inventory(target, before)
        with closing(readonly(target)) as connection:
            new_journal = dict((row[0], row[1:]) for row in connection.execute(
                "SELECT id,checksum,applied_at FROM schema_migrations"))
        journal_preserved = all(new_journal.get(row[0]) == row[1:] for row in old_journal)
        # schema_migrations intentionally gains rows. Every other original table
        # must preserve the multiset of its old columns, including duplicate rows.
        preserved = [name for name in before if name != "schema_migrations" and before[name] == after[name]]
        changed = [name for name in before if name != "schema_migrations" and before[name] != after[name]]
        previous_check = None
        if args.previous_build is not None:
            previous = args.previous_build.resolve(strict=True)
            check = """
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
const base=pathToFileURL(process.argv[1]+'/src/migration-store.js');
const {MigrationStore}=await import(base.href);
const Database=createRequire(base)('better-sqlite3');
const db=new Database(process.argv[2],{readonly:true,fileMustExist:true});
try {
  const store=new MigrationStore(db,process.argv[3],(code)=>Object.assign(new Error(code),{code}));
  try { await store.assertReady(); console.log(JSON.stringify({accepted_upgraded_database:true})); }
  catch(error) { console.log(JSON.stringify({accepted_upgraded_database:false,error_code:error.code??'UNKNOWN'})); }
} finally {db.close();}
"""
            checked = subprocess.run(["node", "--input-type=module", "-e", check, str(previous), str(target),
                                      str(args.previous_migrations.resolve(strict=True) if args.previous_migrations
                                          else previous / "migrations")],
                                     capture_output=True, text=True, timeout=30)
            if checked.returncode != 0:
                raise RuntimeError("previous readiness check failed; private diagnostics withheld")
            previous_check = json.loads(checked.stdout)
            # Readiness probes may not alter the upgraded data, even on the copy.
            if inventory(target, before) != after:
                raise RuntimeError("previous readiness probe changed data")
        observed_counts = {name: before[name]["rows"] for name in
                           ("memory_candidates", "memory_outbox", "control_command_requests", "memory_correction_requests")
                           if name in before}
        report = {"source_open_mode": "read_only", "operational_activation": False,
                  "previous_readiness_check": previous_check, "observed_original_counts": observed_counts,
                  "original_migration_entries_preserved": journal_preserved,
                  "migration_count_before": len(old_vector), "migration_count_after": len(upgrade["vector"]),
                  "added_migrations": [name for name in upgrade["vector"] if name not in old_vector],
                  "original_tables_preserved": len(preserved), "changed_original_tables": changed,
                  "nonempty_original_tables": sum(value["rows"] > 0 for name, value in before.items()
                                                    if name != "schema_migrations"),
                  "initial_foreign_key_errors": initial_fk, "upgrade": upgrade}
        print(json.dumps(report, indent=2))
        return int(not journal_preserved or bool(changed) or (previous_check is not None
                   and previous_check["accepted_upgraded_database"]) or initial_fk != 0 or upgrade["foreign_key_errors"] != 0
                   or upgrade["integrity"] != ["ok"] or upgrade["replay_changes"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
