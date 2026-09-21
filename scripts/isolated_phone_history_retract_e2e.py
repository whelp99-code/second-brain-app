"""Isolated Phone History service retract E2E. No production vault."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phone-history" / "server"))
sys.path.insert(0, str(ROOT / "phone-history" / "tests"))

from conftest import batch_from, event_dict
from phone_history.config import Settings
from phone_history.errors import NotFoundError
from phone_history.service import PhoneHistoryService

from sb.store.cas import ContentAddressedStore


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ph-w3-e2e-", dir="/var/tmp"))
    vault = tmp / "vault"
    settings = Settings(
        data_dir=tmp / "phone-history-data",
        api_token="test-token-" + "a" * 40,
        master_key=bytes(range(32)),
        host="127.0.0.1",
        port=8787,
        second_brain_vault=vault,
    )
    service = PhoneHistoryService(settings)
    event_id = "phevt:isolated-e2e:001"
    ingested = service.ingest(
        batch_from(event_dict(event_id=event_id)),
        idempotency_key="request-isolated-e2e-0001",
    )
    record = service.repository.get_event(event_id)
    ref = json.loads(record.sink_ref or "{}")
    digest = ref["content_sha256"]
    staged = vault / ref["inbox_path"]
    cas = ContentAddressedStore(vault)
    cas.put(staged.read_bytes())
    db = vault / ".sb" / "search.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE search_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO search_meta(key,value) VALUES ('schema_version','4')")
    conn.execute(
        "CREATE VIRTUAL TABLE docs USING fts5("
        "page_id UNINDEXED, section, text, kind UNINDEXED, updated UNINDEXED, "
        "status UNINDEXED, knowledge_status UNINDEXED, approval_status UNINDEXED, "
        "canonical UNINDEXED, source_ref UNINDEXED, compact UNINDEXED, "
        "normalize_id UNINDEXED, normalize_section UNINDEXED, tokenize='trigram')"
    )
    conn.execute(
        "INSERT INTO docs(page_id,section,text,kind,updated,status,knowledge_status,"
        "approval_status,canonical,source_ref,compact,normalize_id,normalize_section) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "wiki/probe",
            "body",
            f"see {digest}",
            "wiki",
            "",
            "",
            "UNVERIFIED",
            "UNREVIEWED",
            "false",
            digest,
            "",
            "",
            "",
        ),
    )
    conn.commit()
    conn.close()
    deleted = service.delete_event(event_id, reason="owner_requested")
    conn = sqlite3.connect(db)
    search_after = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    conn.close()
    gone = False
    try:
        service.repository.get_event(event_id)
    except NotFoundError:
        gone = True
    evidence = {
        "tmp": str(tmp),
        "ingest_status": ingested.status,
        "upload_id": ref["upload_id"],
        "content_sha256": digest,
        "delete_state": deleted["state"],
        "inbox_exists_after": staged.exists(),
        "cas_exists": cas.exists(digest),
        "cas_tombstoned": cas.is_tombstoned(digest),
        "search_rows_after": search_after,
        "local_event_gone": gone,
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    ok = (
        deleted["state"] == "deleted"
        and staged.exists() is False
        and cas.exists(digest) is False
        and cas.is_tombstoned(digest) is True
        and search_after == 0
        and gone is True
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
