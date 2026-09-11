"""Read-only release inspection and isolated W1/W2/W6 defect characterization.

Run from the app root with TMPDIR=/var/tmp PYTHONPATH=. uv run python
scripts/w0-w9-review-probe.py. This is a review probe, not an acceptance gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread

from sb import revoked_keys
from sb.config import Config
from sb.scoped_read_policy import scoped_policy
from sb.search_query import LexicalQuery
from tests.test_access_claims import KEY
from tests.vault_test_support import (
    CAS_SID,
    CitedPageFixture,
    MemoryLedger,
    cited_page,
    ready,
)


def probe() -> dict:
    result = {"source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(),
        "scope": "isolated characterization; no operational writes"}
    with TemporaryDirectory(prefix="sb-w0w9-review-", dir="/var/tmp") as directory:
        root = Path(directory)
        vault = ready(root / "vault")

        def page(body):
            return cited_page(CitedPageFixture(
                page_id="daily/2026-09-11", body_md=f"{body}[^{CAS_SID}]"))

        vault.write_pages([page("Generated original")], "seed", MemoryLedger())
        dest = root / "vault/daily/2026-09-11.md"
        dest.write_text(dest.read_text() + "\nUSER_EDIT_KEEP_THIS\n")
        outcome = vault.write_pages([page("Regenerated correction")], "correct", MemoryLedger())
        result["marker_missing_human_edit"] = {
            "preserved": "USER_EDIT_KEEP_THIS" in dest.read_text(),
            "proposals": outcome.proposals, "pages": outcome.pages,
        }

        state = root / "concurrent"
        start = Barrier(2)
        errors: list[str] = []

        def write(key_id: str) -> None:
            start.wait()
            revoked_keys.record_revoked_key_ids(state, [key_id])

        threads = [Thread(target=write, args=("key:a",)), Thread(target=write, args=("key:b",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        result["concurrent_revocations"] = {
            "persisted": sorted(revoked_keys.load_revoked_key_ids(state)),
            "expected": ["key:a", "key:b"],
            "errors": errors,
        }

        encoded = base64.urlsafe_b64encode(KEY.public_key().public_bytes_raw()).rstrip(b"=").decode()
        raw = {"state_root": str(root / "policy-state"),
               "vault_root": str(root / "policy-vault"), "share_root": str(root / "policy-share"),
               "request_root": str(root / "policy-requests"), "provider_instance_id": "provider:review",
               "jarvis_public_keys": {"key:test": encoded},
               "mcp_scoped_read": {"principal": "principal:owner", "agent": "agent:test",
                                   "session": "session:test", "policy_revision": "policy:1"}}
        scoped_policy(Config(raw=raw))
        try:
            scoped_policy(Config(raw={**raw, "revoked_jarvis_signing_key_ids": ["key:test"]}))
        except ValueError:
            pass
        try:
            scoped_policy(Config(raw=raw))
            rejected = False
        except ValueError:
            rejected = True
        path = revoked_keys.revoked_key_path(root / "policy-state")
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved.name)
        try:
            scoped_policy(Config(raw=raw))
            symlink_closed = False
            keys_after_symlink: list[str] = ["unexpected"]
        except ValueError:
            symlink_closed = True
            keys_after_symlink = []
        result["revocation_symlink"] = {
            "regular_file_rejects_old_key": rejected,
            "fail_closed": symlink_closed,
            "keys_after_symlink": keys_after_symlink,
            "limit": "policy key selection, not an end-to-end authorized read",
        }

        result["search_parity"] = []
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE docs(text,page_id,section)")
            for query, body in [("은빛나침반", "은빛\n나침반"),
                                ("Alpha한글", "alpha한글"), ("쌀밥", "쌀 밥")]:
                db.execute("DELETE FROM docs")
                db.execute("INSERT INTO docs VALUES(?,?,?)", (body, "page", "section"))
                plan = LexicalQuery.parse(query)
                sql, args = plan.predicate()
                matched = db.execute("SELECT count(*) FROM docs WHERE " + sql, args).fetchone()[0] > 0
                result["search_parity"].append({"query": query, "body": body,
                                               "sql_match": matched,
                                               "record_match": plan.matches_record(body)})
        finally:
            db.close()

    release = Path("/var/tmp/sb-candidate-f142a76/releases/0eefce70378a2b0051ee0d8c159a542d1fd9f554")
    result["candidate_present"] = release.is_dir()
    if release.is_dir():
        result["candidate_wheel_sha256"] = hashlib.sha256(
            (release / "second_brain-1.0.0-py3-none-any.whl").read_bytes()).hexdigest()
        result["installed_equal_to_source"] = {
            name: any(path.read_bytes() == (Path("sb") / name).read_bytes()
                      for path in release.glob(".venv/lib/python*/site-packages/sb/" + name))
            for name in ("vault.py", "revoked_keys.py", "search_query.py")}
    return result


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
