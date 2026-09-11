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
from sb.pipeline import StageReport, _Compiled, run_compile
from sb.scoped_read_policy import scoped_policy
from sb.search_query import LexicalQuery, normalize
from sb.store.cas import ContentAddressedStore
from sb.vault import _committed_bytes_match
from tests.test_access_claims import KEY
from tests.vault_test_support import (
    CAS_SID,
    CitedPageFixture,
    MemoryLedger,
    cited_page,
    ready,
)


def managed_compile_edit_probe(root: Path) -> dict:
    active = root / "share/vault"
    vault = ready(active)
    config = Config(raw={
        "vault_root": str(active), "share_root": str(root / "share"),
        "state_root": str(root / "state"), "request_root": str(root / "requests"),
        "provider_instance_id": "provider:review", "provider_release_sha": "a" * 40,
    })
    page_id = "daily/2026-09-11"

    def page(body):
        return cited_page(CitedPageFixture(page_id=page_id, body_md=f"{body}[^{CAS_SID}]"))

    vault.write_pages([page("Original")], "seed", MemoryLedger())
    path = active / f"{page_id}.md"
    path.write_text(path.read_text() + "\nUSER_EDIT_KEEP_THIS\n")
    observed = {"compiler": "fixture; real run_compile generation staging and Vault writer"}

    def stage(ledger, staged_vault, run_id):
        del ledger
        staged_page = staged_vault.root / f"{page_id}.md"
        compiled = _Compiled(staged_vault.root, ContentAddressedStore(staged_vault.root))
        observed["marker_before"] = compiled.last_compiled_hash(page_id)
        observed["edit_before"] = "USER_EDIT_KEEP_THIS" in staged_page.read_text()
        observed["staged_page_matches_head"] = _committed_bytes_match(staged_vault.root, staged_page)
        written = staged_vault.write_pages([page("Corrected")], run_id, compiled)
        observed["proposals"] = written.proposals
        observed["pages"] = written.pages
        return StageReport((), written.pages, written.conflicts, 0, False)

    outcome = run_compile(config, compiler=stage)
    observed["exit_code"] = outcome.exit_code
    observed["edit_after"] = "USER_EDIT_KEEP_THIS" in path.read_text()
    observed["active_is_symlink"] = active.is_symlink()
    return observed


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
        result["managed_compile_human_edit"] = managed_compile_edit_probe(root / "managed")

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
            db.execute("CREATE TABLE docs(text,page_id,section,compact,normalize_id,normalize_section)")
            for query, body in [("은빛나침반", "은빛\n나침반"),
                                ("Alpha한글", "alpha한글"), ("쌀밥", "쌀 밥"),
                                ("은빛나침반", "은빛\u00a0나침반"),
                                ("은빛나침반", "은빛\u3000나침반"),
                                ("STRASSE한글", "Straße한글")]:
                db.execute("DELETE FROM docs")
                db.execute("INSERT INTO docs VALUES(?,?,?,?,?,?)",
                           (body, "page", "section", normalize(body), normalize("page"), normalize("section")))
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
