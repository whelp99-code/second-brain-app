"""Isolated vault retract checks. Does not touch production."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from sb.search import SearchIndex
from sb.store.cas import ContentAddressedStore
from sb.uploads import UploadRejected, accept_upload, read_retract_receipt, retract_upload


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sb-w2-isolated-", dir="/var/tmp"))
    root = tmp / "vault"
    payload = b"# isolated retract probe\nunique-token-w2-20260921\n"
    staged = accept_upload(root, "note.md", payload, relative_path="note.md", device_id="probe")
    cas = ContentAddressedStore(root)
    digest = cas.put(payload)
    db = root / ".sb" / "search.db"
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
        ("wiki/probe", "body", f"see {digest}", "wiki", "", "", "UNVERIFIED", "UNREVIEWED", "false", digest, "", "", ""),
    )
    conn.commit()
    before = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    conn.close()
    first = retract_upload(root, staged.upload_id)
    SearchIndex(root).drop_content(digest)
    second = retract_upload(root, staged.upload_id)
    looked = read_retract_receipt(root, first.receipt_id)
    conn = sqlite3.connect(db)
    after = conn.execute("SELECT count(*) FROM docs").fetchone()[0]
    conn.close()
    reupload_blocked = False
    try:
        accept_upload(root, "note.md", payload, relative_path="note.md", device_id="probe")
    except UploadRejected as exc:
        reupload_blocked = str(exc) == "upload identity retracted"
    evidence = {
        "tmp": str(tmp),
        "upload_id": staged.upload_id,
        "receipt_id": first.receipt_id,
        "deleted": first.deleted,
        "idempotent_receipt": second.receipt_id == first.receipt_id,
        "receipt_lookup_upload_id": None if looked is None else looked.upload_id,
        "inbox_exists_after": (root / staged.inbox_path).exists(),
        "cas_exists": cas.exists(digest),
        "cas_tombstoned": cas.is_tombstoned(digest),
        "search_rows_before": before,
        "search_rows_after": after,
        "reupload_blocked": reupload_blocked,
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    failed = not (
        evidence["deleted"]
        and evidence["idempotent_receipt"]
        and evidence["receipt_lookup_upload_id"] == staged.upload_id
        and evidence["inbox_exists_after"] is False
        and evidence["cas_exists"] is False
        and evidence["cas_tombstoned"] is True
        and evidence["search_rows_after"] == 0
        and evidence["reupload_blocked"] is True
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
