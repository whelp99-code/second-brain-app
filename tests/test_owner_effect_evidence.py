"""A correction must not retain the original in its daily evidence appendix."""
import sqlite3
from contextlib import closing
from pathlib import Path

from sb.contracts import PageSpec, SourceCite
from sb.generation_runtime import GenerationMutationService
from sb.generation_runtime_models import (
    GenerationAuthority,
    GenerationMutation,
    GenerationOperation,
)
from sb.store import Run, SourceItem
from sb.store.cas import ContentAddressedStore
from sb.store.ledger import Ledger
from sb.vault import Vault
from tests.knowledge import stamp_knowledge
from tests.test_web import NoPreviousHash, request, running
from tests.test_web_effect_recovery import payload_for
from tests.test_web_lifecycle import NOW, PAGE, URL, ready


def test_correction_removes_source_evidence_but_preserves_other_lines(tmp_path: Path) -> None:
    config, root = ready(tmp_path)
    keep = "Unrelated statement stays unchanged."
    def seed(staging: Path) -> None:
        original = b"[M13-TEST] M13SENTexample"
        digest = ContentAddressedStore(staging).put(original)
        cite = SourceCite(digest[:8], "inbox:m13-test.md", digest)
        body = (f"Review M13SENTexample.[^{cite.sid}]\n\n{keep}\n\n"
                f"- origin={cite.origin} hash={digest} [^{cite.sid}] text={original.decode()}")
        (staging / (PAGE + ".md")).unlink()
        _ = Vault(staging).write_pages([PageSpec(PAGE, "Daily", body, [cite], "active")],
                                  "evidence-seed", NoPreviousHash())
        stamp_knowledge(staging)
        with Ledger(staging) as ledger:
            ledger.upsert_source_item(SourceItem("inbox", "inbox:m13-test.md", "v1",
                digest, "seed", "seed"))
            ledger.upsert_source_item(SourceItem("inbox", "inbox:unrelated.md", "v1",
                "a" * 64, "seed", "seed"))
            ledger.set_cursor("inbox", "preserved-position", "2026-09-27T00:00:00Z")
            ledger.record_run(Run("seed", "2026-09-27T00:00:00Z",
                "2026-09-27T00:00:01Z", None, "ok"))
    service = GenerationMutationService.from_config(config)
    try:
        _ = service.mutate(GenerationMutation("evidence-seed", GenerationOperation.RUN, NOW,
            GenerationAuthority(None, None), seed))
    finally:
        service.close()
    with closing(sqlite3.connect(f"file:{root}/.sb/ledger.db?mode=ro", uri=True)) as db:
        preserved = {table: db.execute(f'SELECT * FROM "{table}"').fetchall()
                     for table in ("source_item", "cursor", "run", "bound_knowledge")}
    with running(config) as base:
        _, page = request(base + URL)
        assert request(base + URL + "/correct", method="POST",
                        payload=payload_for(page, "Reviewed."))[0] == 200
        assert request(base + "/api/search?q=M13SENTexample") == (200, {"results": []})
    body = (root / (PAGE + ".md")).read_text()
    assert keep in body
    assert "M13SENTexample" not in body
    with closing(sqlite3.connect(f"file:{root}/.sb/ledger.db?mode=ro", uri=True)) as db:
        for table, rows in preserved.items():
            after = db.execute(f'SELECT * FROM "{table}"').fetchall()
            assert set(rows) <= set(after), table
